Download and place in 'dataset' :
- https://www.kaggle.com/datasets/orvile/wesad-wearable-stress-affect-detection-dataset/code?datasetId=7192727&sortBy=voteCount | rename 'WESAD'
- https://www.kaggle.com/code/azazurrehmanbutt/ecg-classification-using-ml-dl | rename 'mitbih'

Install dependencies:

```bash
pip install -r requirements.txt
```

Train models:

```bash
python -m src.training.train_emotion_wesad
python -m src.training.train_anomaly_legacy
python -m src.training.train_rhythm_features --dataset-dir data_processed/rhythm --model-dir models/rhythm
python -m src.training.tune_rhythm_thresholds --dataset-dir data_processed/rhythm --model-dir models/rhythm --metrics-dir models/metrics --target-recall 0.90 --precision-floor 0.80 --apply
python -m src.training.train_rhythm_cnn --dataset-dir data_processed/rhythm --model-dir models/rhythm --metrics-dir models/metrics --epochs 25 --batch-size 128
python -m src.dataset_builders.build_mitdb_ectopy --input-dir data_raw/mitdb --output-dir data_processed/mitdb_ectopy
python -m src.training.train_ectopy_features --dataset-dir data_processed/mitdb_ectopy --model-dir models/ectopy --metrics-dir models/metrics
```

Generated artifacts:

- `emotion_model.pkl`
- `emotion_feature_schema.json`
- `emotion_metrics.json`
- `isolation_forest_model.pkl`
- `anomaly_scaler.pkl`
- `anomaly_feature_schema.json`
- `models/rhythm/rhythm_feature_model.pkl`
- `models/rhythm/rhythm_scaler.pkl`
- `models/rhythm/rhythm_feature_schema.json`
- `models/rhythm/rhythm_decision_config.json`
- `models/metrics/rhythm_threshold_tuning.json`
- `models/rhythm/rhythm_cnn_model.pt`
- `models/rhythm/rhythm_cnn_metadata.json`
- `models/ectopy/ectopy_feature_model.pkl`
- `models/ectopy/ectopy_scaler.pkl`
- `models/ectopy/ectopy_feature_schema.json`

PVC/PAC ectopy labels:

- `normal`
- `pvc`
- `pac`
- `mixed_ectopic`
- `other`

Rhythm inference mode:

- default `RHYTHM_PREDICTOR_MODE=feature`: use the validated feature model for realtime AFib/rhythm alerts.
- `RHYTHM_PREDICTOR_MODE=cnn`: force the CNN model for experiments.
- `RHYTHM_PREDICTOR_MODE=auto`: use CNN if `rhythm_cnn_model.pt` exists, otherwise use feature model.

Current model choice: keep `feature` as production default. The CNN result is close on accuracy but still weaker on macro F1, AFib recall, and noise recall.

Evaluate long-term AF episode behavior:

```bash
python -m src.dataset_builders.build_afdb --input-dir data_raw/afdb --output-dir data_processed/afdb_windows
python -m src.training.evaluate_long_term_afdb --dataset-dir data_processed/afdb_windows --model-dir models/rhythm --metrics-dir models/metrics --decision-mode probability_only --afib-probability-threshold 0.1
```

The long-term evaluation writes:

- `models/metrics/afdb_long_term_metrics.json`
- `models/rhythm/rhythm_decision_config.json`

`src.api.pipeline` automatically loads `models/rhythm/rhythm_decision_config.json` unless environment variables override it.

Run REST API:

```bash
uvicorn src.api.pipeline:app --reload
```

Compatibility wrapper:

```bash
uvicorn pipeline:app --reload
python pipeline.py --bluetooth-demo
```

Open dashboard:

```text
http://127.0.0.1:8000/dashboard
```

Dashboard/API endpoints:

- `GET /latest-result`
- `GET /latest-ecg`
- `GET /history?patient_id=...&days=...`
- `GET /risk-summary?patient_id=...&days=...`
- `GET /health-report?patient_id=...&daily_hours=24&long_term_days=7`
- `GET /events?patient_id=...&days=...&limit=...`
- `POST /personal-baseline/update-progressive`
- `GET /personal-baseline/status?patient_id=...`
- `POST /polar/start`
- `POST /polar/stop`

Predict endpoint:

```http
POST /ingest-ecg
```

Example body:

```json
{
  "patient_id": "chinh",
  "sample_rate_hz": 130,
  "timestamp": "2026-05-14T10:30:00+07:00",
  "ecg_samples": [943, 1076, 1210]
}
```

Emotion labels:

- `neutral`
- `stress`
- `relaxed`

Realtime predictions are also appended to:

```text
dataset/realtime_logs/predictions.jsonl
```

Realtime storage:

- SQLite metadata: `dataset/realtime_logs/ecg_monitor.db`
- Raw ECG windows: `dataset/realtime_logs/raw_ecg/<patient>/<session>/<prediction_id>.csv`
- Raw ACC windows: `dataset/realtime_logs/raw_acc/<patient>/<session>/<prediction_id>.csv`
- Personal baseline JSON: `dataset/realtime_logs/personal_baseline/<patient>/personal_baseline.json`

Progressive 7-day personal baseline:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/personal-baseline/update-progressive `
  -ContentType "application/json" `
  -Body '{"patient_id":"polar_h10","target_days":7,"min_predictions":20,"include_alert_windows":false}'
```

Baseline status values:

- `not_ready`: not enough reliable predictions.
- `warming_up`: enough predictions, but fewer than 7 days.
- `ready`: enough reliable data across the target 7-day period.

Optional MongoDB sync:

Local realtime storage remains SQLite + raw CSV files. MongoDB is used as an optional central/cloud sync target for prediction metadata, events, session summaries, and risk summaries.

```bash
$env:MONGODB_URI="mongodb://localhost:27017"
$env:MONGODB_DB="elderly_care"
python -m src.storage.mongodb_sync --patient-id polar_h10 --days 7
```

API trigger:

```http
POST /sync/mongodb
```

Example body:

```json
{
  "patient_id": "polar_h10",
  "days": 7,
  "limit": 5000
}
```

MongoDB collections:

- `predictions`
- `events`
- `session_summaries`
- `risk_summaries`
- `sync_runs`

Raw ECG/ACC arrays are not pushed to MongoDB by default; MongoDB stores local raw file paths to keep sync lightweight.

Calibrate runtime sensor context from real Polar data:

```bash
python -m src.calibration.calibrate_sensor_context --input-dir data_raw/real_data --person-id chinh --output-path models/runtime/sensor_context_config.json
```

This writes calibrated thresholds for:

- activity classification from ACC VM std
- ACTIVE fall-candidate suppression
- signal quality tolerances
- rhythm alert suppression during activity

`src.api.pipeline` loads `models/runtime/sensor_context_config.json` automatically. Use `SENSOR_CONTEXT_CONFIG_PATH` to point to another config, or set `SENSOR_CONTEXT_CONFIG_DISABLED=1` to fall back to built-in defaults.

After changing feature extraction, retrain the emotion model before relying on emotion predictions:

```bash
python -m src.training.train_emotion_wesad
```
