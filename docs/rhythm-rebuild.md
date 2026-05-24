# Rhythm rebuild workflow

This document tracks the new rhythm-classification path from `mission.md`.

## Phase 1: Build CinC 2017 rhythm windows

Put the PhysioNet/CinC 2017 training files under:

```text
data_raw/cinc2017/
  REFERENCE.csv
  A00001.mat
  A00001.hea
  ...
```

Build fixed windows:

```powershell
python -m src.dataset_builders.build_cinc2017 `
  --input-dir data_raw/cinc2017 `
  --output-dir data_processed/rhythm
```

Output:

```text
data_processed/rhythm/X.npy
data_processed/rhythm/y.npy
data_processed/rhythm/metadata.csv
data_processed/rhythm/label_map.json
data_processed/rhythm/build_summary.json
```

Target format:

- sample rate: `130 Hz`
- window length: `30 seconds`
- samples per window: `3900`
- labels: `normal`, `possible_afib`, `other_rhythm`, `noise`

## Phase 2: Train feature baseline

```powershell
python -m src.training.train_rhythm_features `
  --dataset-dir data_processed/rhythm `
  --model-dir models/rhythm `
  --metrics-dir models/metrics
```

Output:

```text
models/rhythm/rhythm_feature_model.pkl
models/rhythm/rhythm_scaler.pkl
models/rhythm/rhythm_feature_schema.json
models/rhythm/label_map.json
models/metrics/rhythm_feature_metrics.json
models/metrics/rhythm_feature_confusion_matrix.png
```

The existing realtime dashboard is not switched to this model yet. That should
happen only after the dataset build and validation metrics are acceptable.

## Phase 3: Add NSTDB noise augmentation

Install `wfdb` if needed:

```powershell
python -m pip install -r requirements.txt
```

Put MIT-BIH Noise Stress Test Database records under:

```text
data_raw/nstdb/
  bw.dat
  bw.hea
  em.dat
  em.hea
  ma.dat
  ma.hea
  ...
```

Create an augmented rhythm dataset:

```powershell
python -m src.dataset_builders.augment_rhythm_with_nstdb `
  --input-dir data_processed/rhythm `
  --nstdb-dir data_raw/nstdb `
  --output-dir data_processed/rhythm_nstdb_augmented `
  --augmented-count 1600
```

Then retrain on the augmented dataset:

```powershell
python -m src.training.train_rhythm_features `
  --dataset-dir data_processed/rhythm_nstdb_augmented `
  --model-dir models/rhythm `
  --metrics-dir models/metrics
```

## Phase 4: AFDB long-term evaluation

Build AFDB windows:

```powershell
python -m src.dataset_builders.build_afdb `
  --input-dir data_raw/afdb `
  --output-dir data_processed/afdb_windows
```

Evaluate the current rhythm model for AF window detection, episodes, and burden:

```powershell
python -m src.training.evaluate_long_term_afdb `
  --dataset-dir data_processed/afdb_windows `
  --model-dir models/rhythm `
  --metrics-dir models/metrics `
  --afib-probability-threshold 0.1 `
  --decision-mode probability_only
```

Output:

```text
data_processed/afdb_windows/X_windows.npy
data_processed/afdb_windows/y_windows.npy
data_processed/afdb_windows/metadata.csv
data_processed/afdb_windows/episode_metadata.csv
models/metrics/afdb_long_term_metrics.json
models/metrics/afdb_rhythm_eval_cache.npz
```

Phase G currently uses `probability_only` for AF episode tracking, with two
consecutive 30-second windows required before an active AF episode is counted.
This keeps the user-facing rhythm label as the model argmax, but lets the
long-term AF tracker use the AF probability directly. The realtime defaults are:

- `RHYTHM_AFIB_DECISION_MODE=probability_only`
- `RHYTHM_AFIB_EPISODE_THRESHOLD=0.1`
- `RHYTHM_AFIB_ALERT_THRESHOLD=0.3`
