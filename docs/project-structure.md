# Project structure

This project is being reorganized around the rhythm-classification roadmap in
`mission.md`. The current realtime prototype remains runnable from root
`pipeline.py`, while new training and inference work should be added under
`src/`.

## Top-level folders

- `data_raw/`: original external datasets before preprocessing.
- `data_processed/`: generated fixed-rate windows and labels.
- `models/`: trained model artifacts, schemas, and metrics.
- `src/`: new modular source layout for dataset builders, features, training,
  inference, API, services, storage, and dashboard code.
- `dataset/realtime_logs/`: runtime SQLite database, raw Polar ECG/ACC logs,
  anomaly calibration artifacts, and progressive personal baseline JSON.
- `legacy/`: old notebooks/scripts kept for reference only.
- `docs/`: mission, integration notes, and architecture documents.
- `tests/`: unit tests.

## New model target

The anomaly model is now legacy. The rebuild target is:

```text
Polar H10 ECG/RR/ACC
-> signal quality
-> rhythm classification
-> AF episode detection
-> AF burden
-> progressive personal baseline comparison
-> context-aware alert
```

Primary rhythm labels:

```text
0 normal
1 possible_afib
2 other_rhythm
3 noise
```

## Current compatibility note

Root `pipeline.py` still runs the current dashboard/API. It now loads existing
emotion and legacy anomaly artifacts from `models/` instead of root files.
The API also exposes `POST /personal-baseline/update-progressive` and
`GET /personal-baseline/status` for 7-day patient-specific baseline operation.
