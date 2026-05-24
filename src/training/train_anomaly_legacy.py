import os

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import IsolationForest
from sklearn.metrics import accuracy_score, confusion_matrix, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

from src.features.ecg_features import (
    ANOMALY_FEATURE_COLUMNS,
    aggregate_morphological_features,
    bandpass_filter,
    detect_r_peaks,
    extract_beat_features,
    extract_hrv_features,
    rr_intervals_ms_from_peaks,
    save_feature_schema,
)


MITBIH_PATH = "dataset/mitbih"
OUTPUT_DATASET_PATH = "dataset/wesad_modified/anomaly_dataset.csv"
MODEL_PATH = "models/anomaly_legacy/isolation_forest_model.pkl"
SCALER_PATH = "models/anomaly_legacy/anomaly_scaler.pkl"
SCHEMA_PATH = "models/anomaly_legacy/anomaly_feature_schema.json"
MITBIH_SAMPLE_RATE_HZ = 125
WINDOW_SIZE = 10
STEP_SIZE = 10
RANDOM_STATE = 42


def load_mitbih_sources(dataset_path):
    mitbih_train = pd.read_csv(os.path.join(dataset_path, "mitbih_train.csv"), header=None)
    mitbih_test = pd.read_csv(os.path.join(dataset_path, "mitbih_test.csv"), header=None)
    ptbdb_abnormal = pd.read_csv(os.path.join(dataset_path, "ptbdb_abnormal.csv"), header=None)
    ptbdb_normal = pd.read_csv(os.path.join(dataset_path, "ptbdb_normal.csv"), header=None)

    mitbih_all = pd.concat([mitbih_train, mitbih_test], ignore_index=True)
    mitbih_normal = mitbih_all[mitbih_all[187] == 0].reset_index(drop=True)
    mitbih_abnormal = mitbih_all[mitbih_all[187] != 0].reset_index(drop=True)

    normal_merged = pd.concat([mitbih_normal, ptbdb_normal], ignore_index=True)
    abnormal_merged = pd.concat([mitbih_abnormal, ptbdb_abnormal], ignore_index=True)
    return normal_merged, abnormal_merged


def collect_rr_and_beat_features(df, label_col=187, sample_rate_hz=125):
    all_rr = []
    all_beat_features = []
    ecg_matrix = df.drop(columns=[label_col]).to_numpy(dtype=float)

    for row in ecg_matrix:
        ecg = bandpass_filter(row, sample_rate_hz)
        peaks = detect_r_peaks(ecg, sample_rate_hz)
        rr_ms = rr_intervals_ms_from_peaks(peaks, sample_rate_hz)
        beat_features = extract_beat_features(ecg, peaks, sample_rate_hz)

        if len(rr_ms) > 0:
            all_rr.extend(rr_ms.tolist())
        if beat_features:
            all_beat_features.extend(beat_features)

    return np.array(all_rr, dtype=float), all_beat_features


def build_windowed_anomaly_rows(rr_ms, beat_features, label, dataset_name):
    rows = []
    limit = min(len(rr_ms), len(beat_features))
    if limit < WINDOW_SIZE:
        return rows

    for start_idx in range(0, limit - WINDOW_SIZE + 1, STEP_SIZE):
        end_idx = start_idx + WINDOW_SIZE
        hrv_feats = extract_hrv_features(rr_ms[start_idx:end_idx])
        morph_feats = aggregate_morphological_features(beat_features[start_idx:end_idx])
        if hrv_feats is None or morph_feats is None:
            continue

        row = {
            **hrv_feats,
            **morph_feats,
            "label": label,
            "dataset": dataset_name,
            "start_idx": start_idx,
            "end_idx": end_idx,
        }
        rows.append(row)

    return rows


def build_anomaly_dataset(normal_df, abnormal_df):
    normal_rr, normal_beats = collect_rr_and_beat_features(
        normal_df, sample_rate_hz=MITBIH_SAMPLE_RATE_HZ
    )
    abnormal_rr, abnormal_beats = collect_rr_and_beat_features(
        abnormal_df, sample_rate_hz=MITBIH_SAMPLE_RATE_HZ
    )

    rows = []
    rows.extend(build_windowed_anomaly_rows(normal_rr, normal_beats, 0, "normal_merged"))
    rows.extend(build_windowed_anomaly_rows(abnormal_rr, abnormal_beats, 1, "abnormal_merged"))
    return pd.DataFrame(rows)


def train_anomaly_model(df):
    df = df.dropna().reset_index(drop=True)
    normal_df = df[df["label"] == 0].copy().reset_index(drop=True)
    abnormal_df = df[df["label"] == 1].copy().reset_index(drop=True)

    if normal_df.empty:
        raise ValueError("Need normal samples to train IsolationForest.")

    normal_train = normal_df.sample(frac=0.8, random_state=RANDOM_STATE)
    normal_test = normal_df.drop(normal_train.index).reset_index(drop=True)
    abnormal_test = abnormal_df.sample(n=min(100, len(abnormal_df)), random_state=RANDOM_STATE)

    train = normal_train.copy()
    test = pd.concat([normal_test, abnormal_test], ignore_index=True).sample(
        frac=1.0, random_state=RANDOM_STATE
    )

    X_train = train[ANOMALY_FEATURE_COLUMNS]
    X_test = test[ANOMALY_FEATURE_COLUMNS]
    y_test = test["label"]

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    isolation_forest = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        max_features=len(ANOMALY_FEATURE_COLUMNS),
        random_state=RANDOM_STATE,
    )
    isolation_forest.fit(X_train_scaled)

    raw_pred = isolation_forest.predict(X_test_scaled)
    y_pred = np.where(raw_pred == -1, 1, 0)

    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = 2 * (precision * recall) / (precision + recall + 1e-10)

    print("Dataset shape:", df.shape)
    print("Features:", ANOMALY_FEATURE_COLUMNS)
    print(f"Accuracy:  {accuracy:.4f}")
    print(f"Precision: {precision:.4f}")
    print(f"Recall:    {recall:.4f}")
    print(f"F1 Score:  {f1:.4f}")

    cm_if = confusion_matrix(y_test, y_pred, labels=[0, 1])
    plt.figure(figsize=(6, 5))
    sns.heatmap(
        cm_if,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=["Normal", "Abnormal"],
        yticklabels=["Normal", "Abnormal"],
    )
    plt.title("Confusion Matrix - Isolation Forest")
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.tight_layout()
    plt.show()

    return isolation_forest, scaler


def main():
    os.makedirs(os.path.dirname(OUTPUT_DATASET_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    normal_df, abnormal_df = load_mitbih_sources(MITBIH_PATH)
    anomaly_df = build_anomaly_dataset(normal_df, abnormal_df)
    if anomaly_df.empty:
        raise ValueError("No anomaly feature rows were generated.")

    anomaly_df.to_csv(OUTPUT_DATASET_PATH, index=False)
    model, scaler = train_anomaly_model(anomaly_df)

    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    save_feature_schema(SCHEMA_PATH, ANOMALY_FEATURE_COLUMNS)
    print(f"Saved anomaly model to {MODEL_PATH}")
    print(f"Saved anomaly scaler to {SCALER_PATH}")
    print(f"Saved anomaly feature schema to {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
