
External data folders not tracked by GitHub:

Some folders are intentionally excluded from GitHub because they contain large datasets, local runtime data, or personal ECG/ACC recordings. Download them from the project Google Drive and place them back into the project root with the same paths.

Google Drive:

- https://drive.google.com/drive/folders/1MxtozBqBwf7SvtdJsg9ONMA4V-0SLR6G?usp=drive_link

Expected local paths after download:

```text
dataset/realtime_logs/
dataset/collected/
data_raw/
```

Notes:

- `dataset/realtime_logs/`: local SQLite database, raw realtime ECG/ACC chunks, personal baseline, calibration/runtime logs.
- `dataset/collected/`: personal ECG/ACC recordings collected from real users for calibration/evaluation.
- `data_raw/`: original large public datasets such as WESAD, CinC 2017, AFDB, MITDB, NSTDB. GitHub only keeps `.gitkeep` placeholders.
- Do not commit these folders unless the team explicitly decides to use Git LFS or a separate private data repository.

System documentation:

- `docs/model-storage-alert-system.md`: model choice, storage flow, alert flow.
- `docs/so-sanh-rhythm-cnn-feature-model.md`: detailed CNN vs feature rhythm comparison.
- `docs/wifi-provisioning-production.md`: AP Mode -> Client Mode Wi-Fi setup for Raspberry Pi production.
- `docs/deploy-raspberry-pi.md`: Raspberry Pi deployment and production installer.

Raspberry production install:

```bash
cd /home/elcaprj/elderly_care
bash scripts/install_pi_production.sh
```

This one-shot installer sets hostname `elderlycare`, enables `elderlycare.local`, installs system/Python dependencies, creates `.env`, enables Polar auto-start, and installs the backend + Wi-Fi provisioning systemd services.

Optional one-line production configuration:

```bash
POLAR_H10_MAC=24:AC:AC:13:EB:86 MONGODB_SYNC_ENABLED=1 MONGODB_URI='mongodb+srv://...' bash scripts/install_pi_production.sh
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Optional research dependencies for CNN rhythm experiments:

```bash
pip install -r requirements-research.txt
```

Train models:

```bash
python -m src.training.train_stress_wesad --wesad-root data_raw/wesad
python -m src.training.train_anomaly_legacy
python -m src.training.train_rhythm_features --dataset-dir data_processed/rhythm --model-dir models/rhythm
python -m src.training.tune_rhythm_thresholds --dataset-dir data_processed/rhythm --model-dir models/rhythm --metrics-dir models/metrics --target-recall 0.90 --precision-floor 0.80 --apply
python -m src.dataset_builders.build_mitdb_ectopy --input-dir data_raw/mitdb --output-dir data_processed/mitdb_ectopy
python -m src.training.train_ectopy_features --dataset-dir data_processed/mitdb_ectopy --model-dir models/ectopy --metrics-dir models/metrics
```

Research-only CNN comparison:

```bash
python -m src.training.train_rhythm_cnn --dataset-dir data_processed/rhythm --model-dir models/research/rhythm_cnn --metrics-dir models/metrics --epochs 25 --batch-size 128
```

Generated artifacts:

- `models/stress/rf_model.pkl`
- `models/stress/svm_pipeline.pkl`
- `models/stress/scaler_final.pkl`
- `models/stress/model_metadata.json`
- `models/stress/stress_feature_schema.json`
- `models/metrics/stress_metrics.json`
- `isolation_forest_model.pkl`
- `anomaly_scaler.pkl`
- `anomaly_feature_schema.json`
- `models/rhythm/rhythm_feature_model.pkl`
- `models/rhythm/rhythm_scaler.pkl`
- `models/rhythm/rhythm_feature_schema.json`
- `models/rhythm/rhythm_decision_config.json`
- `models/metrics/rhythm_threshold_tuning.json`
- `models/ectopy/ectopy_feature_model.pkl`
- `models/ectopy/ectopy_scaler.pkl`
- `models/ectopy/ectopy_feature_schema.json`

Research-only CNN artifacts:

- `models/research/rhythm_cnn/rhythm_cnn_model.pt`
- `models/research/rhythm_cnn/rhythm_cnn_metadata.json`
- `models/metrics/rhythm_cnn_metrics.json`
- `models/metrics/rhythm_cnn_confusion_matrix.png`

PVC/PAC ectopy labels:

- `normal`
- `pvc`
- `pac`
- `mixed_ectopic`
- `other`

Rhythm inference mode:

- Production realtime always uses `rhythm_feature_model`.
- CNN rhythm is kept only for research/comparison and is not imported by `src.api.pipeline`.
- Current model choice: feature model, because it is stronger on macro F1, AFib recall, noise recall, and lighter for Raspberry Pi.

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

Long-running Raspberry Pi validation:

```bash
python -m src.services.pi_runtime_monitor --base-url http://127.0.0.1:8000 --patient-id polar_h10 --duration-hours 24 --interval-seconds 60 --output logs/pi_soak_24h.jsonl
python -m src.services.build_soak_report --input logs/pi_soak_24h.jsonl --alert-review logs/alert_review.csv --summary-output logs/pi_soak_24h_summary.json --report-output logs/pi_soak_24h_report.md
```

API key protection before exposing outside LAN/VPN:

```env
API_AUTH_ENABLED=1
API_KEY=<secret>
API_PUBLIC_PATHS=/health,/dashboard
ALLOWED_ORIGINS=https://your-app-domain.example
```

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

Stress labels:

- `non_stress`
- `stress`
- `unknown`

Stress realtime inference uses a rolling RR buffer. The WESAD stress model is trained on 300-second windows with 60-second step, so `/ingest-ecg` returns `stress.label = "unknown"` with `reason = "warming_up_stress_window"` until enough reliable RR intervals have accumulated.

Realtime predictions are also appended to:

```text
dataset/realtime_logs/predictions.jsonl
```

Realtime storage:

- SQLite metadata: `dataset/realtime_logs/ecg_monitor.db`
- Raw ECG/ACC chunks: SQLite table `raw_signal_chunks` stores compressed BLOB chunks and links them to predictions/sessions.
- Optional legacy raw CSV export: set `SAVE_LEGACY_RAW_CSV=1`.
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

Raw ECG/ACC chunks can be synced to MongoDB by the storage sync endpoints/scheduler. Local chunks are purged only after successful sync and retention checks.

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

After changing stress feature extraction, retrain the WESAD stress model before relying on stress predictions:

```bash
python -m src.training.train_stress_wesad --wesad-root data_raw/wesad --skip-importance
```
