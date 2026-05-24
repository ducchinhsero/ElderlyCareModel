import argparse
import json
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from src.inference.rhythm_cnn_inference import RhythmCnn1D
from src.preprocessing import RHYTHM_LABELS, TARGET_SAMPLE_RATE_HZ, save_json


DEFAULT_DATASET_DIR = "data_processed/rhythm"
DEFAULT_MODEL_DIR = "models/rhythm"
DEFAULT_METRICS_DIR = "models/metrics"
AFIB_CLASS_ID = 1
NOISE_CLASS_ID = 3


def _load_torch():
    try:
        import torch
        from torch.utils.data import DataLoader, Dataset
    except ImportError as exc:
        raise ImportError("PyTorch is required to train the rhythm CNN. Install torch first.") from exc
    return torch, DataLoader, Dataset


def _safe_stratify_labels(y):
    _, counts = np.unique(y, return_counts=True)
    if len(counts) < 2 or np.min(counts) < 2:
        return None
    return y


def _load_groups(dataset_path, expected_rows):
    metadata_path = Path(dataset_path) / "metadata.csv"
    if not metadata_path.exists():
        return None
    metadata = pd.read_csv(metadata_path)
    if "record_id" not in metadata.columns or len(metadata) != expected_rows:
        return None
    return metadata["record_id"].astype(str).to_numpy()


def _split_train_test(X, y, groups=None, test_size=0.2, random_state=42):
    if groups is not None:
        splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
        train_idx, test_idx = next(splitter.split(X, y, groups=groups))
        return train_idx, test_idx, "group_shuffle_split"

    indices = np.arange(len(y))
    stratify = _safe_stratify_labels(y)
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify,
    )
    return train_idx, test_idx, "stratified_random_split" if stratify is not None else "random_split"


def _class_weights(y_train, num_classes):
    counts = np.bincount(y_train.astype(int), minlength=num_classes).astype(float)
    counts = np.maximum(counts, 1.0)
    weights = len(y_train) / (num_classes * counts)
    weights[AFIB_CLASS_ID] *= 1.8
    weights[NOISE_CLASS_ID] *= 1.5
    return weights.astype(np.float32)


def _save_confusion_matrix(cm, labels, path, title):
    target_names = [RHYTHM_LABELS.get(int(label), str(label)) for label in labels]
    plt.figure(figsize=(6, 5))
    plt.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.title(title)
    plt.colorbar()
    tick_marks = np.arange(len(labels))
    plt.xticks(tick_marks, target_names, rotation=30, ha="right")
    plt.yticks(tick_marks, target_names)
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def _make_dataset_class():
    torch, _, Dataset = _load_torch()

    class RhythmWindowDataset(Dataset):
        def __init__(self, X, y):
            self.X = np.asarray(X, dtype=np.float32)
            self.y = np.asarray(y, dtype=np.int64)

        def __len__(self):
            return len(self.y)

        def __getitem__(self, index):
            return torch.from_numpy(self.X[index][None, :]), torch.tensor(self.y[index], dtype=torch.long)

    return RhythmWindowDataset


def _evaluate(model, loader, device):
    torch, _, _ = _load_torch()
    model.eval()
    all_probs = []
    all_labels = []
    with torch.no_grad():
        for X_batch, y_batch in loader:
            X_batch = X_batch.to(device)
            logits = model(X_batch)
            probs = torch.softmax(logits, dim=1).cpu().numpy()
            all_probs.append(probs)
            all_labels.append(y_batch.numpy())
    probs = np.vstack(all_probs)
    labels = np.concatenate(all_labels)
    predictions = np.argmax(probs, axis=1)
    return labels, predictions, probs


def _metrics(y_true, y_pred, probs, X_shape, split_info, sample_rate_hz, epochs_ran):
    labels = sorted(int(label) for label in np.unique(np.concatenate([y_true, y_pred])))
    target_names = [RHYTHM_LABELS.get(label, str(label)) for label in labels]
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=target_names,
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    return {
        "model": "RhythmCnn1D",
        "sample_rate_hz": float(sample_rate_hz),
        "classes": {str(key): value for key, value in RHYTHM_LABELS.items()},
        "dataset_shape": list(X_shape),
        "split": split_info,
        "epochs_ran": int(epochs_ran),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": macro_f1,
        "afib_recall": float(report.get("possible_afib", {}).get("recall", 0.0)),
        "noise_recall": float(report.get("noise", {}).get("recall", 0.0)),
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "labels": labels,
        "mean_prediction_confidence": float(np.mean(np.max(probs, axis=1))),
    }


def _compare_with_feature_baseline(cnn_metrics, metrics_dir):
    baseline_path = Path(metrics_dir) / "rhythm_feature_metrics.json"
    if not baseline_path.exists():
        return {
            "available": False,
            "reason": f"{baseline_path} not found.",
        }
    with open(baseline_path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    keys = ("accuracy", "macro_f1", "afib_recall", "noise_recall")
    return {
        "available": True,
        "baseline_model": baseline.get("selected_model") or baseline.get("model"),
        "cnn_model": cnn_metrics.get("model"),
        "metrics": {
            key: {
                "feature": baseline.get(key),
                "cnn": cnn_metrics.get(key),
                "delta": (
                    float(cnn_metrics.get(key)) - float(baseline.get(key))
                    if baseline.get(key) is not None and cnn_metrics.get(key) is not None
                    else None
                ),
            }
            for key in keys
        },
    }


def train_rhythm_cnn_model(
    dataset_dir=DEFAULT_DATASET_DIR,
    model_dir=DEFAULT_MODEL_DIR,
    metrics_dir=DEFAULT_METRICS_DIR,
    sample_rate_hz=TARGET_SAMPLE_RATE_HZ,
    test_size=0.2,
    epochs=25,
    batch_size=128,
    learning_rate=1e-3,
    weight_decay=1e-4,
    patience=6,
    random_state=42,
    max_train_samples=None,
    device=None,
):
    torch, DataLoader, _ = _load_torch()
    random.seed(random_state)
    np.random.seed(random_state)
    torch.manual_seed(random_state)

    dataset_path = Path(dataset_dir)
    model_path = Path(model_dir)
    metrics_path = Path(metrics_dir)
    X_path = dataset_path / "X.npy"
    y_path = dataset_path / "y.npy"
    if not X_path.exists() or not y_path.exists():
        raise FileNotFoundError(f"Missing {X_path} or {y_path}. Build the rhythm dataset first.")

    X = np.load(X_path).astype(np.float32)
    y = np.load(y_path).astype(np.int64)
    groups = _load_groups(dataset_path, expected_rows=len(y))

    train_idx, test_idx, split_strategy = _split_train_test(
        X,
        y,
        groups=groups,
        test_size=test_size,
        random_state=random_state,
    )
    if max_train_samples is not None and int(max_train_samples) > 0 and len(train_idx) > int(max_train_samples):
        rng = np.random.default_rng(random_state)
        train_idx = rng.choice(train_idx, size=int(max_train_samples), replace=False)

    X_train, y_train = X[train_idx], y[train_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    input_length = int(X.shape[1])
    num_classes = int(max(np.max(y), len(RHYTHM_LABELS) - 1) + 1)
    split_info = {
        "strategy": split_strategy,
        "test_size": float(test_size),
        "train_rows": int(len(train_idx)),
        "test_rows": int(len(test_idx)),
        "train_record_count": int(len(set(groups[train_idx]))) if groups is not None else None,
        "test_record_count": int(len(set(groups[test_idx]))) if groups is not None else None,
        "record_overlap_count": int(len(set(groups[train_idx]) & set(groups[test_idx]))) if groups is not None else None,
    }

    dataset_cls = _make_dataset_class()
    train_loader = DataLoader(
        dataset_cls(X_train, y_train),
        batch_size=int(batch_size),
        shuffle=True,
        num_workers=0,
    )
    test_loader = DataLoader(
        dataset_cls(X_test, y_test),
        batch_size=int(batch_size),
        shuffle=False,
        num_workers=0,
    )

    device_name = device or ("cuda" if torch.cuda.is_available() else "cpu")
    torch_device = torch.device(device_name)
    model = RhythmCnn1D(input_length=input_length, num_classes=num_classes)
    model.to(torch_device)

    class_weights = torch.tensor(_class_weights(y_train, num_classes), dtype=torch.float32).to(torch_device)
    criterion = torch.nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(learning_rate), weight_decay=float(weight_decay))

    best_state = None
    best_macro_f1 = -1.0
    best_epoch = 0
    stale_epochs = 0
    history = []
    for epoch in range(1, int(epochs) + 1):
        model.train()
        train_loss = 0.0
        for X_batch, y_batch in train_loader:
            X_batch = X_batch.to(torch_device)
            y_batch = y_batch.to(torch_device)
            optimizer.zero_grad()
            loss = criterion(model(X_batch), y_batch)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * len(y_batch)

        y_true, y_pred, _ = _evaluate(model, test_loader, torch_device)
        macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
        epoch_row = {
            "epoch": int(epoch),
            "train_loss": float(train_loss / max(1, len(train_loader.dataset))),
            "val_macro_f1": macro_f1,
            "val_accuracy": float(accuracy_score(y_true, y_pred)),
        }
        history.append(epoch_row)
        if macro_f1 > best_macro_f1:
            best_macro_f1 = macro_f1
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= int(patience):
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    y_true, y_pred, probs = _evaluate(model, test_loader, torch_device)
    metrics = _metrics(
        y_true,
        y_pred,
        probs,
        X_shape=X.shape,
        split_info=split_info,
        sample_rate_hz=sample_rate_hz,
        epochs_ran=len(history),
    )
    metrics["best_epoch"] = int(best_epoch)
    metrics["training_history"] = history
    metrics["device"] = str(torch_device)
    metrics["input_length"] = input_length
    metrics["feature_baseline_comparison"] = _compare_with_feature_baseline(metrics, metrics_path)

    model_path.mkdir(parents=True, exist_ok=True)
    metrics_path.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "input_length": input_length,
            "num_classes": num_classes,
            "sample_rate_hz": float(sample_rate_hz),
        },
        model_path / "rhythm_cnn_model.pt",
    )
    save_json(
        model_path / "rhythm_cnn_metadata.json",
        {
            "model": "RhythmCnn1D",
            "input_length": input_length,
            "num_classes": num_classes,
            "sample_rate_hz": float(sample_rate_hz),
            "window_seconds": float(input_length / float(sample_rate_hz)),
            "labels": {str(key): value for key, value in RHYTHM_LABELS.items()},
            "dropout": 0.25,
        },
    )
    save_json(metrics_path / "rhythm_cnn_metrics.json", metrics)
    _save_confusion_matrix(
        np.asarray(metrics["confusion_matrix"]),
        metrics["labels"],
        metrics_path / "rhythm_cnn_confusion_matrix.png",
        "Rhythm CNN Model",
    )
    return metrics


def parse_args():
    parser = argparse.ArgumentParser(description="Train 1D-CNN rhythm model on raw ECG windows.")
    parser.add_argument("--dataset-dir", default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIR)
    parser.add_argument("--sample-rate-hz", type=float, default=TARGET_SAMPLE_RATE_HZ)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--patience", type=int, default=6)
    parser.add_argument("--max-train-samples", type=int, default=None)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    metrics = train_rhythm_cnn_model(
        dataset_dir=args.dataset_dir,
        model_dir=args.model_dir,
        metrics_dir=args.metrics_dir,
        sample_rate_hz=args.sample_rate_hz,
        test_size=args.test_size,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        patience=args.patience,
        max_train_samples=args.max_train_samples,
        device=args.device,
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
