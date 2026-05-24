import os
import pickle
import json
from copy import deepcopy

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import GroupKFold

from src.features.ecg_features import (
    EMOTION_FEATURE_COLUMNS,
    EMOTION_LABELS,
    extract_emotion_feature_rows,
    save_feature_schema,
)


DATASET_PATH = "dataset/WESAD"
OUTPUT_DATASET_PATH = "dataset/wesad_modified/emotion_dataset.csv"
MODEL_PATH = "models/emotion/emotion_model.pkl"
SCHEMA_PATH = "models/emotion/emotion_feature_schema.json"
METRICS_PATH = "models/emotion/emotion_metrics.json"
WESAD_SAMPLE_RATE_HZ = 700
WINDOW_SIZE = 10
STEP_SIZE = 10

# WESAD labels used for emotion training:
# 1 = baseline/neutral, 2 = stress, 4 = meditation/relaxed.
ALLOWED_LABELS = set(EMOTION_LABELS.keys())


def load_wesad_subjects(dataset_path):
    patients_data = {}
    for subject in os.listdir(dataset_path):
        subject_path = os.path.join(dataset_path, subject)
        if not os.path.isdir(subject_path):
            continue

        file_path = os.path.join(subject_path, f"{subject}.pkl")
        if not os.path.exists(file_path):
            continue

        with open(file_path, "rb") as f:
            data = pickle.load(f, encoding="latin1")

        ecg = data["signal"]["chest"]["ECG"].flatten()
        labels = data["label"]
        df = pd.DataFrame({"ECG": ecg, "label": labels})
        patients_data[subject] = df[df["label"].isin(ALLOWED_LABELS)].reset_index(drop=True)

    return patients_data


def build_emotion_dataset(patients_data):
    rows = []
    for subject, patient_df in patients_data.items():
        feature_rows = extract_emotion_feature_rows(
            patient_df["ECG"].to_numpy(),
            sample_rate_hz=WESAD_SAMPLE_RATE_HZ,
            labels=patient_df["label"].to_numpy(),
            window_size=WINDOW_SIZE,
            step_size=STEP_SIZE,
            filter_signal=True,
        )

        for row in feature_rows:
            if row.get("label") not in ALLOWED_LABELS:
                continue
            row["subject"] = subject
            rows.append(row)

    return pd.DataFrame(rows)


def train_emotion_model(df):
    df = df.dropna().reset_index(drop=True)
    X = df[EMOTION_FEATURE_COLUMNS]
    y = df["label"]
    groups = df["subject"]

    n_splits = min(6, groups.nunique())
    if n_splits < 2:
        raise ValueError("Need at least 2 different subjects for GroupKFold.")

    gkf = GroupKFold(n_splits=n_splits)
    fold_scores = []
    best_score = -np.inf
    best_forest = None
    best_fold = None

    for fold_idx, (train_idx, test_idx) in enumerate(gkf.split(X, y, groups=groups), start=1):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

        forest = RandomForestClassifier(
            n_estimators=400,
            random_state=42,
            n_jobs=-1,
            class_weight="balanced",
        )
        forest.fit(X_train, y_train)
        fold_pred = forest.predict(X_test)
        fold_score = accuracy_score(y_test, fold_pred)
        fold_scores.append(fold_score)

        if fold_score > best_score:
            best_score = fold_score
            best_forest = deepcopy(forest)
            best_fold = fold_idx

    print("Dataset shape:", df.shape)
    print("Features:", EMOTION_FEATURE_COLUMNS)
    print("Classes:", EMOTION_LABELS)
    print("Number of subjects:", groups.nunique())
    print("GroupKFold splits:", n_splits)
    print("Accuracy per fold:", np.array(fold_scores))
    print("Mean accuracy:", np.mean(fold_scores))
    print("Std accuracy:", np.std(fold_scores))
    print("Best fold:", best_fold)
    print("Best fold accuracy:", best_score)

    y_pred_all = best_forest.predict(X)
    print("Accuracy on full dataset:", accuracy_score(y, y_pred_all))
    report = classification_report(
        y,
        y_pred_all,
        labels=list(EMOTION_LABELS.keys()),
        target_names=[EMOTION_LABELS[x] for x in EMOTION_LABELS],
        zero_division=0,
        output_dict=True,
    )
    print(classification_report(
        y,
        y_pred_all,
        labels=list(EMOTION_LABELS.keys()),
        target_names=[EMOTION_LABELS[x] for x in EMOTION_LABELS],
        zero_division=0,
    ))

    cm = confusion_matrix(y, y_pred_all, labels=list(EMOTION_LABELS.keys()))
    plt.figure(figsize=(6, 5))
    sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=[EMOTION_LABELS[x] for x in EMOTION_LABELS],
        yticklabels=[EMOTION_LABELS[x] for x in EMOTION_LABELS],
    )
    plt.title("Confusion Matrix - emotion model")
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()
    plt.show()

    metrics = {
        "features": EMOTION_FEATURE_COLUMNS,
        "classes": EMOTION_LABELS,
        "fold_scores": [float(x) for x in fold_scores],
        "mean_accuracy": float(np.mean(fold_scores)),
        "std_accuracy": float(np.std(fold_scores)),
        "best_fold": int(best_fold),
        "best_fold_accuracy": float(best_score),
        "full_dataset_accuracy": float(accuracy_score(y, y_pred_all)),
        "classification_report": report,
    }
    with open(METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"Saved emotion metrics to {METRICS_PATH}")

    return best_forest


def main():
    os.makedirs(os.path.dirname(OUTPUT_DATASET_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    patients_data = load_wesad_subjects(DATASET_PATH)
    if not patients_data:
        raise FileNotFoundError(f"No WESAD subjects found in {DATASET_PATH}")

    emotion_df = build_emotion_dataset(patients_data)
    if emotion_df.empty:
        raise ValueError("No emotion feature rows were generated from WESAD.")

    emotion_df.to_csv(OUTPUT_DATASET_PATH, index=False)
    model = train_emotion_model(emotion_df)
    joblib.dump(model, MODEL_PATH)
    save_feature_schema(SCHEMA_PATH, EMOTION_FEATURE_COLUMNS)
    print(f"Saved emotion model to {MODEL_PATH}")
    print(f"Saved emotion feature schema to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
