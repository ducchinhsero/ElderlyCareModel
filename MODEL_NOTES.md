# MODEL_NOTES.md — Tài liệu tham chiếu folder model code

> File này tổng hợp toàn bộ kiến trúc, schema, API endpoint, và breaking changes của folder
> `ElderlyCareModel` để AI có thể sửa folder `app` (frontend / mobile) cho phù hợp với
> backend mới. Đọc tài liệu này TRƯỚC khi modify app.
>
> Tất cả đường dẫn dưới đây là relative so với root của repo `ElderlyCareModel`.

---

## 1. Tổng quan kiến trúc

Hệ thống đã được **rebuild khỏi mô hình anomaly `normal/abnormal` chung chung** sang
một pipeline đa-module:

```
Polar H10 (BLE)
   ├── ECG 130 Hz
   └── ACC 25 Hz (3 trục, mG)
        │
        ▼
   predict_ecg()  ──►  Output JSON gồm 10+ nhóm trường (xem mục 3)
        │
        ▼
   Lưu SQLite (predictions, events, raw_signal_chunks, …)
        │
        ▼
   Dashboard / REST API / WebSocket / MongoDB sync
```

Các module chính:

| Module | File chính | Output | Vai trò |
|---|---|---|---|
| Signal Quality | `src/features/ecg_features.py::evaluate_signal_quality` | `good/fair/poor` + score + reasons | Chặn false alarm khi tín hiệu xấu |
| Rhythm (feature) | `src/inference/rhythm_inference.py::RhythmFeaturePredictor` | `normal/possible_afib/other_rhythm/noise` | Production default classifier |
| Rhythm (CNN) | `src/inference/rhythm_cnn_inference.py::RhythmCnnPredictor` | Cùng 4 class | Optional, cần `torch` + file `.pt` |
| Ectopy (PVC/PAC) | `src/inference/ectopy_inference.py::EctopyFeaturePredictor` | `normal/pvc/pac/mixed_ectopic/other` | Detect ngoại tâm thu |
| Stress | `src/inference/stress_inference.py::StressPredictor` | `non_stress/stress/unknown` | WESAD, 300s rolling RR buffer |
| HR Event | `src/inference/hr_event.py::detect_hr_event` | `tachycardia_at_rest/bradycardia/normal_hr/unknown` | Rule-based với activity context |
| AF Episode | `src/inference/af_episode_tracker.py::AFEpisodeTracker` | episode/burden | Tích lũy theo bệnh nhân |
| Alert Engine | `src/inference/alert_engine.py::map_rhythm_to_alert` | level + message cho rhythm | Mapping rhythm → alert |
| ACC / Sensor Context | `src/features/acc_features.py::summarize_acc_window` | activity, fall, hr_context_alert | Rule-based |
| Anomaly (legacy) | `src/calibration/anomaly_calibration.py` + IsolationForest | `normal/abnormal/unknown` | Giữ làm phụ trợ, có thể calibrate per-patient |
| Personal Baseline | `src/calibration/personal_baseline.py` | 7-day baseline JSON, comparisons | So sánh recent vs cá nhân |
| Guided Baseline | `src/calibration/guided_baseline.py` | session REST/WALK/ACTIVE | Hướng dẫn người dùng thu baseline |
| Daily Health | `src/assessment/daily_health_assessment.py` | findings + level | Đánh giá 24h |
| Temporal Report | `src/assessment/temporal_health_report.py` | realtime + daily + long_term | Phân tầng thời gian |
| Storage | `src/storage/ecg_storage.py` (SQLite) | predictions/events/raw_chunks/snapshots | Local persistent storage |
| Background Sync | `src/storage/background_sync.py` + `mongodb_sync.py` | Optional MongoDB sync | Cloud sync metadata |

> **Sample rate chuẩn**: ECG **130 Hz**, window 30 giây (3900 samples), ACC **25 Hz**.

---

## 2. Cấu trúc thư mục

```
ElderlyCareModel/
├── pipeline.py                       # wrapper, import từ src/api/pipeline.py
├── src/
│   ├── api/pipeline.py               # FastAPI app + Polar BLE + predict_ecg
│   ├── preprocessing.py              # RHYTHM_LABELS, resample, normalize, split_into_windows
│   ├── features/
│   │   ├── ecg_features.py           # bandpass, R-peak, signal_quality, HRV, anomaly features
│   │   ├── rhythm_features.py        # 41 cột rhythm features
│   │   ├── ectopy_features.py        # 48 cột (rhythm + 7 ectopy-specific)
│   │   ├── stress_features.py        # 12 HRV features (WESAD)
│   │   └── acc_features.py           # Polar PMD ACC parser + activity + fall + hr_context
│   ├── inference/
│   │   ├── rhythm_inference.py
│   │   ├── rhythm_cnn_inference.py
│   │   ├── ectopy_inference.py
│   │   ├── stress_inference.py       # + RollingRRBuffer
│   │   ├── hr_event.py
│   │   ├── af_episode_tracker.py
│   │   └── alert_engine.py
│   ├── calibration/
│   │   ├── anomaly_calibration.py
│   │   ├── personal_baseline.py
│   │   ├── guided_baseline.py
│   │   ├── calibrate_real_data.py
│   │   └── calibrate_sensor_context.py
│   ├── assessment/
│   │   ├── daily_health_assessment.py
│   │   └── temporal_health_report.py
│   ├── storage/
│   │   ├── ecg_storage.py            # SQLite schema + queries + event builder
│   │   ├── background_sync.py
│   │   └── mongodb_sync.py
│   ├── config/
│   │   ├── env_loader.py
│   │   └── runtime_config.py         # load sensor_context_config.json
│   ├── training/                     # train_rhythm_features.py, train_rhythm_cnn.py, …
│   ├── dataset_builders/             # build_cinc2017.py, build_afdb.py, build_mitdb_ectopy.py, …
│   └── services/                     # collect_real_data.py, soak_test.py
├── models/
│   ├── stress/                       # rf_model.pkl, svm_pipeline.pkl, scaler_final.pkl, model_metadata.json, stress_feature_schema.json
│   ├── rhythm/                       # rhythm_feature_model.pkl, rhythm_scaler.pkl, rhythm_feature_schema.json, label_map.json, rhythm_decision_config.json, rhythm_cnn_model.pt, rhythm_cnn_metadata.json
│   ├── ectopy/                       # ectopy_feature_model.pkl, ectopy_scaler.pkl, ectopy_feature_schema.json, label_map.json
│   ├── anomaly_legacy/               # isolation_forest_model.pkl, anomaly_scaler.pkl, anomaly_feature_schema.json
│   ├── runtime/                      # sensor_context_config.json (per-user calibrated thresholds)
│   └── metrics/                      # *_metrics.json, confusion matrices, threshold tuning
├── data_raw/                         # (external) cinc2017, afdb, nstdb, mitdb, wesad, real_data
├── data_processed/                   # X.npy, y.npy
├── dataset/realtime_logs/            # (external) SQLite + predictions.jsonl + raw ECG/ACC + personal_baseline
├── docs/                             # nhiều file phân tích y khoa và roadmap
└── tests/
```

---

## 3. Output JSON của `/ingest-ecg` (và `predict_ecg`)

**Đây là response quan trọng nhất cho app.** App KHÔNG ĐƯỢC tự suy đoán fields từ tên cũ.
Trường mới được thêm so với code cũ chỉ có `anomaly` và `stress`/`emotion`.

```jsonc
{
  "patient_id": "polar_h10",
  "prediction_id": "uuid",                 // thêm bởi save_prediction
  "session_id": "20260524",                // YYYYMMDD
  "collection_session_id": "polar_h10:20260524",
  "timestamp": "2026-05-24T10:30:00+07:00",
  "timestamp_epoch": 1748068200.0,
  "sample_rate_hz": 130.0,
  "window_count": 5,
  "heart_rate_bpm": 82.4,                  // có thể null

  "stress": {                              // ←— THAY THẾ "emotion"
    "label": "non_stress | stress | unknown",
    "value": 0,                            // 0|1|null
    "confidence": 0.81,
    "probabilities": {"non_stress": 0.81, "stress": 0.19},
    "model_version": "soft_voting_rf_svm_wesad",
    "window_seconds": 300.0,
    "reason": null,
    "rr_count": 312,                       // chỉ có khi predict thật
    "coverage_seconds": 280.4
  },

  "anomaly": {                             // Legacy IsolationForest, giữ song song
    "label": "normal | abnormal | unknown",
    "value": 0,                            // 0|1|null
    "anomaly_windows": 0,
    "total_windows": 4,
    "model_source": "polar_calibrated | generic_mitbih_ptbdb",
    "mean_decision_score": 0.12,
    "decision_threshold": null,            // hoặc số, hoặc null
    "max_morphology_z": 4.5,               // chỉ khi distribution guard
    "reason": "..."                        // nếu unknown
  },

  "rhythm": {                              // ←— MODULE MỚI QUAN TRỌNG
    "label": "normal | possible_afib | other_rhythm | noise | unknown",
    "class_id": 1,                         // 0..3 hoặc null
    "confidence": 0.78,
    "probabilities": {
      "normal": 0.10,
      "possible_afib": 0.78,
      "other_rhythm": 0.08,
      "noise": 0.04
    },
    "possible_afib_probability": 0.78,
    "window_count": 1,
    "model_source": "rhythm_feature_model | rhythm_cnn_model",
    "afib_decision": {                     // metadata về ngưỡng quyết định
      "mode": "probability_only | argmax_and_threshold",
      "episode_threshold": 0.05,
      "alert_threshold": 0.28,
      "label_for_alert": "possible_afib"
    },
    "reason": "..."                        // chỉ khi unknown
  },

  "ectopy": {                              // ←— MODULE MỚI: PVC/PAC
    "label": "normal | pvc | pac | mixed_ectopic | other | unknown",
    "class_id": 1,
    "confidence": 0.72,
    "probabilities": {"normal": ..., "pvc": ..., "pac": ..., "mixed_ectopic": ..., "other": ...},
    "pvc_probability": 0.45,               // = P(pvc) + P(mixed_ectopic)
    "pac_probability": 0.22,
    "ectopic_probability": 0.67,           // tổng PVC+PAC+mixed
    "window_count": 1,
    "model_source": "ectopy_feature_model"
  },

  "hr_event": {                            // ←— RULE: HR + activity
    "label": "tachycardia_at_rest | bradycardia | normal_hr | unknown",
    "tachycardia": false,
    "bradycardia": false,
    "heart_rate_bpm": 82.4,
    "activity_state": "rest",
    "duration_sec": 30.0,
    "min_duration_sec": 29.0,
    "reason": "..."
  },

  "af_episode": {                          // ←— TRACK theo bệnh nhân
    "active": true,
    "current_episode_duration_sec": 120.0,
    "af_episode_count": 3,
    "longest_af_episode_sec": 240.0,
    "total_af_duration_sec": 600.0,
    "af_burden_percent": 8.3,
    "decision_mode": "probability_only",
    "afib_probability_threshold": 0.05
  },

  "rhythm_alert": {                        // ←— MAPPING rhythm → alert
    "level": "normal | medium | high | critical | unknown",
    "message": "Possible AFib pattern detected. Continue monitoring."
  },

  "signal_quality": {
    "label": "good | fair | poor",
    "score": 0.85,                         // 0..1
    "reasons": ["..."],                    // array các lý do giảm score
    "metrics": {
      "sample_count": 3900,
      "duration_seconds": 30.0,
      "nan_ratio": 0.0,
      "zero_ratio": 0.0,
      "amplitude_std": 215.4,
      "amplitude_range": 2300.0,
      "r_peak_count": 35,
      "valid_rr_ratio": 0.96,
      "rr_outlier_ratio": 0.05
    }
  },

  "risk": {                                // Risk trend dựa trên anomaly + stress + history
    "level": "low | medium | high | unknown",
    "score": 0.32,
    "reason": "Recent abnormal ratio 8%, ..."
  },

  "sensor_context": {                      // ←— ACC TỪ POLAR
    "activity_state": "REST | SLOW_WALK | WALK | ACTIVE | UNKNOWN",
    "activity_features": {
      "sample_count": 750,
      "sample_rate_hz": 25,
      "acc_vm_mean": 1023.4,
      "acc_vm_std": 18.5,
      "acc_vm_max": 1100.2,
      "acc_vm_range": 200.5,
      "acc_x_std": 6.2,
      "acc_y_std": 8.1,
      "acc_z_std": 4.4,
      "acc_energy": 1048576.0
    },
    "fall": {
      "impact_spike": false,
      "free_fall": false,
      "post_still": false,
      "fall_candidate": false,
      "strong_fall": false,
      "impact_only": false,
      "confidence": 0.0,
      "reason": "",
      "peak_vm": 0.0,
      "min_before_1s": 0.0,
      "std_after_5s": 0.0,
      "n_impacts": 0,
      "fall_offset_s": -1.0,
      "activity_state": "REST",
      "calibrated_thresholds": {"impact_threshold_mg": 2000.0, ...}
    },
    "hr_context_alert": {
      "level": "SAFE | WATCH | ALERT | CRITICAL",
      "reason": "...",
      "threshold_bpm": 130.0
    }
  },

  "alert_level": "normal | medium | high | critical | unknown",
  "message": "Possible AFib episode detected.",

  // Các trường lưu storage trả về sau khi save_prediction
  "raw_ecg_path": null,                    // null trừ khi SAVE_LEGACY_RAW_CSV=1
  "raw_acc_path": null,
  "raw_ecg_chunk_ids": ["uuid", ...],      // ID các chunk trong raw_signal_chunks
  "raw_acc_chunk_ids": ["uuid", ...]
}
```

### 3.1. Quy tắc đọc field cho app

- Khi `signal_quality.label == "poor"`: rhythm, ectopy, stress, anomaly, af_episode, hr_event đều có thể là `unknown`. App phải hiển thị message lý do thay vì các giá trị rỗng.
- `alert_level` đã được **rhythm-first** (xem `_rhythm_first_alert` trong `src/api/pipeline.py:622-644`): ưu tiên rhythm_alert level > risk > anomaly > legacy.
- `sensor_context.fall.strong_fall == true` → alert critical bất kể rhythm.
- `sensor_context.fall.fall_candidate == true` → alert ít nhất `high`.
- Stress alert bị **suppress** khi activity là WALK/ACTIVE và không có anomaly (xem `_suppress_activity_stress_alert`).

### 3.2. Labels chuẩn

| Module | Labels | Class IDs |
|---|---|---|
| `rhythm.label` | `normal`, `possible_afib`, `other_rhythm`, `noise`, `unknown` | 0..3, null |
| `ectopy.label` | `normal`, `pvc`, `pac`, `mixed_ectopic`, `other`, `unknown` | 0..4, null |
| `stress.label` | `non_stress`, `stress`, `unknown` | 0,1,null |
| `anomaly.label` | `normal`, `abnormal`, `unknown` | value: 0,1,null |
| `hr_event.label` | `tachycardia_at_rest`, `bradycardia`, `normal_hr`, `unknown` | — |
| `signal_quality.label` | `good`, `fair`, `poor` | — |
| `sensor_context.activity_state` | `REST`, `SLOW_WALK`, `WALK`, `ACTIVE`, `UNKNOWN` | — |
| `sensor_context.hr_context_alert.level` | `SAFE`, `WATCH`, `ALERT`, `CRITICAL` | — |
| `alert_level` / `rhythm_alert.level` / `risk.level` | `normal`, `medium`, `high`, `critical`, `unknown` (risk dùng `low/medium/high/unknown`) | — |

---

## 4. REST API endpoints đầy đủ

Tất cả định nghĩa tại `src/api/pipeline.py:1883-2407`. Server: `uvicorn src.api.pipeline:app --reload` (mặc định http://127.0.0.1:8000).

### 4.1. Realtime / monitoring

| Method | Path | Mô tả | Query / Body chính |
|---|---|---|---|
| GET | `/health` | Trạng thái mọi model (loaded, error), config paths | — |
| GET | `/dashboard` | HTML dashboard (browser) | — |
| GET | `/latest-result` | `{latest_result, history (last 50), polar}` | — |
| WS  | `/ws/vitals` | Push realtime mỗi prediction mới qua WebSocket. Payload: `{type:"vitals", latest_result, timestamp}` | — |
| GET | `/latest-ecg` | `{prediction, samples[], source}` (downsample về ≤ max_samples) | `patient_id?`, `max_samples=1000` |
| GET | `/history` | `{items:[predictions]}` | `patient_id?`, `days=1`, `limit=100` |
| POST | `/ingest-ecg` | Predict từ body. Body: `{patient_id, sample_rate_hz, timestamp?, ecg_samples[], acc_samples?, acc_sample_rate_hz?}` | — |

### 4.2. Polar BLE collector

| Method | Path | Body | Mô tả |
|---|---|---|---|
| POST | `/polar/start` | `{address?, chunk_seconds?}` | Start background collector. Mặc định address = `24:AC:AC:13:EB:86`, chunk_seconds=30 |
| POST | `/polar/stop` | — | Cancel background task |

### 4.3. Assessment

| Method | Path | Query | Mô tả |
|---|---|---|---|
| GET | `/risk-summary` | `patient_id?`, `days=1` | `{level, score, reason}` |
| GET | `/session-summary` | `patient_id?`, `days=1` | Sessions + overall counts |
| GET | `/daily-summary` | `patient_id?`, `days=7` | Theo từng ngày |
| GET | `/daily-health-assessment` | `patient_id?`, `hours=24` | Findings + recommendations, level từ `low/medium/high/critical/unknown` |
| GET | `/health-report` | `patient_id?`, `realtime_minutes=5`, `daily_hours=24`, `long_term_days=7` | 3 layers: realtime / daily / long_term + personal_baseline comparisons |
| GET | `/events` | `patient_id?`, `days=1`, `limit=200` | `{event_count, events[]}` — event_type ∈ {`af_suspicion`, `tachycardia`, `bradycardia`, `ectopy_suspicion`, `stress_suspicion`, `hr_context`, `fall_candidate`, `poor_signal`} |
| POST | `/events/rebuild` | `{patient_id?, days?, limit?}` | Build lại event timeline từ predictions |

### 4.4. Storage / Sync

| Method | Path | Mô tả |
|---|---|---|
| GET | `/storage/status` | Counts mỗi table + raw chunks |
| GET | `/storage/raw-chunks` | `patient_id?`, `hours=24`, `signal_type?`, `limit=1000` (không kèm payload) |
| GET | `/storage/raw-chunks/{chunk_id}` | Metadata 1 chunk |
| GET | `/storage/collection-sessions` | `patient_id?`, `hours=24`, `limit=200` |
| GET | `/storage/assessment-snapshots` | `patient_id?`, `hours=24`, `snapshot_type?`, `limit=100` |
| POST | `/storage/sync-mongodb` | Sync ngay (alias `/sync/mongodb`) |
| POST | `/sync/mongodb` | Body: `{patient_id?, days?, limit?, include_raw_samples?}` |
| POST | `/storage/purge-synced` | `{retention_hours?, limit?}` |
| GET | `/storage/sync-scheduler/status` | Background scheduler status |
| POST | `/storage/sync-scheduler/start` | Body: BackgroundSyncConfig fields (interval_seconds, patient_id, days, limit, purge_after_sync, ...) |
| POST | `/storage/sync-scheduler/stop` | — |
| POST | `/storage/sync-scheduler/run-once` | Trigger 1 lần với config overrides |

### 4.5. Baseline (legacy anomaly per-patient)

| Method | Path | Body | Mô tả |
|---|---|---|---|
| POST | `/baseline/mark-current-session` | `{patient_id?, session_id?, contamination=0.03}` | Train IsolationForest mới từ session hiện tại |
| POST | `/baseline/calibrate-real-data` | `{patient_id, person_id, input_dir?, states=["rest"], contamination=0.03}` | Calibrate từ data_raw/real_data |
| GET | `/baseline/status` | `patient_id=polar_h10` | `{patient_id, calibrated, metadata}` |

### 4.6. Personal Baseline (statistic 7-day)

| Method | Path | Body | Mô tả |
|---|---|---|---|
| POST | `/personal-baseline/calibrate` | `{patient_id?, days=2, min_predictions=20, include_alert_windows=false}` | Build 1 lần |
| POST | `/personal-baseline/update-progressive` | `{patient_id?, target_days=7, min_predictions=20, include_alert_windows=false}` | Update theo từng ngày, status: `not_ready / warming_up / ready` |
| GET | `/personal-baseline/status` | `patient_id=polar_h10` | `{patient_id, calibrated, calibration, baseline}` |

### 4.7. Guided Baseline (hướng dẫn user thu REST/WALK/ACTIVE)

| Method | Path | Body | Mô tả |
|---|---|---|---|
| GET | `/guided-baseline/status` | `patient_id?`, `target_days=7` | `{status, day_count, target_days, progress_ratio, segment_plan, latest_session}` |
| POST | `/guided-baseline/start` | `{patient_id?, target_days=7}` | Tạo session mới + 3 segments (REST 300s, WALK 300s, ACTIVE 180s) |
| POST | `/guided-baseline/segment/complete` | `{patient_id?, session_id, segment_type, started_at, ended_at, allow_skip=false}` | Validate windows (signal quality + activity match) |
| POST | `/guided-baseline/complete-day` | `{patient_id?, session_id, target_days=7}` | Close session, update personal baseline từ guided history |

**SEGMENT_PLAN** (cố định trong `guided_baseline.py:16-39`):
```jsonc
[
  {"segment_type":"REST",   "expected_activity":"REST",   "duration_seconds":300, "instruction":"Sit or lie down quietly..."},
  {"segment_type":"WALK",   "expected_activity":"WALK",   "duration_seconds":300, "instruction":"Walk slowly..."},
  {"segment_type":"ACTIVE", "expected_activity":"ACTIVE", "duration_seconds":180, "instruction":"Do light daily movement...", "skippable": true}
]
```

---

## 5. Breaking changes so với code cũ (cũng là DASHBOARD CŨ)

> Đây là phần app cần thay đổi NHIỀU NHẤT.

### 5.1. `emotion` → `stress`

- **Cũ**: response có `emotion: {label, confidence, probabilities: {happy/sad/neutral/...}}`.
- **Mới**: response có `stress: {label, value, confidence, probabilities: {non_stress, stress}, model_version, window_seconds, reason, rr_count, coverage_seconds}`.
- App PHẢI rename UI "Emotion" → "Stress" và đổi labels.
- Khi load history từ DB cũ, `_stress_from_legacy_emotion()` (storage) sẽ tự map `emotion.label="stress"` ↔ stress, các nhãn `neutral/relaxed` ↔ non_stress, còn lại unknown. App có thể dựa vào `stress.model_version == "legacy_emotion_fallback"` để hiển thị badge "from legacy".

### 5.2. Anomaly không còn là model chính

- App ĐỪNG dùng `anomaly.label` làm trạng thái chính. Dùng `rhythm.label` + `rhythm_alert.level` + `af_episode` thay thế.
- `anomaly` vẫn có giá trị tham khảo, đặc biệt khi đã calibrate per-patient (`anomaly.model_source == "polar_calibrated"`).

### 5.3. Thêm các card / view BẮT BUỘC

App phải render được:
- **Rhythm status** + confidence + AFib probability (%).
- **PVC/PAC**: ectopy.label + pvc%/pac%.
- **AF episode**: active flag + current duration + burden%.
- **HR event** label.
- **Signal quality** label + reasons.
- **Activity** state + ACC VM std.
- **Fall**: strong/possible/impact/clear + peak VM.
- **HR context alert** level (SAFE/WATCH/ALERT/CRITICAL).
- **Personal baseline** state + comparisons.
- **Daily health assessment** + findings table.
- **Health report** layered (realtime/daily/long_term).
- **Event timeline** từ `/events`.

Tham chiếu chi tiết HTML/JS của dashboard cũ ở `src/api/pipeline.py:1216-1881` (chỉ là reference, app không cần dùng HTML này).

### 5.4. Heart rate

- `heart_rate_bpm` có thể là `null`. App phải fallback hiển thị `--`.

### 5.5. `/ingest-ecg` body

- Mới support `acc_samples` và `acc_sample_rate_hz`. App có thể bỏ qua nếu không thu ACC.
- `acc_samples` chấp nhận list các tuple `(x, y, z)` hoặc `(x, y, z, vm)` hoặc dict `{x_mg, y_mg, z_mg, vm_mg?}` (mG).

### 5.6. WebSocket

- Endpoint mới `/ws/vitals` push mọi prediction. Payload: `{type:"vitals", latest_result, timestamp}`. App nên ưu tiên WS thay vì polling `/latest-result` 2s/lần.

### 5.7. Alert levels

- Cũ thường chỉ có `normal / abnormal`.
- Mới: `normal / medium / high / critical / unknown`. App phải có 5 màu/state.
- `risk.level` dùng `low / medium / high / unknown` (KHÔNG có "normal"). Cẩn thận đừng so sánh chéo.

### 5.8. Event types

App nên hỗ trợ tô màu / icon theo `event_type`:
- `af_suspicion` (severity medium/high/critical)
- `tachycardia` (medium)
- `bradycardia` (medium)
- `ectopy_suspicion` (medium, label = pvc/pac/mixed_ectopic)
- `stress_suspicion` (medium)
- `hr_context` (medium nếu WATCH, high nếu ALERT/CRITICAL)
- `fall_candidate` (critical nếu strong_fall, else high)
- `poor_signal` (unknown)

### 5.9. Storage chunk format

- ECG/ACC giờ lưu dưới dạng **compressed BLOB** trong SQLite (`raw_signal_chunks`), không phải CSV. App muốn lấy raw ECG → dùng `/latest-ecg` (đã decode + downsample) hoặc query `/storage/raw-chunks`.
- Legacy CSV chỉ được tạo khi env `SAVE_LEGACY_RAW_CSV=1`.

---

## 6. Environment variables ảnh hưởng đến app behavior

| Env | Default | Mô tả |
|---|---|---|
| `MODEL_ROOT` | `models` | Folder gốc models |
| `STRESS_MODEL_DIR` | `models/stress` | — |
| `RHYTHM_MODEL_PATH` | `models/rhythm/rhythm_feature_model.pkl` | — |
| `RHYTHM_CNN_MODEL_PATH` | `models/rhythm/rhythm_cnn_model.pt` | — |
| `RHYTHM_PREDICTOR_MODE` | `feature` | `feature / cnn / auto` |
| `RHYTHM_AFIB_DECISION_MODE` | `probability_only` (override config) | — |
| `RHYTHM_AFIB_EPISODE_THRESHOLD` | 0.05 (từ rhythm_decision_config.json) | — |
| `RHYTHM_AFIB_ALERT_THRESHOLD` | 0.28 | — |
| `ANOMALY_MODEL_PATH` | `models/anomaly_legacy/isolation_forest_model.pkl` | — |
| `SENSOR_CONTEXT_CONFIG_PATH` | `models/runtime/sensor_context_config.json` | — |
| `SENSOR_CONTEXT_CONFIG_DISABLED` | unset | Set `1` để bỏ calibrated thresholds |
| `ALERT_WEBHOOK_URL` | unset | POST event khi alert >= medium |
| `ALERT_WEBHOOK_LEVELS` | `medium,high,critical` | — |
| `MONGODB_URI` | unset | Bật MongoDB sync |
| `MONGODB_DB` | `elderly_care` | — |
| `MONGODB_SYNC_ENABLED` | false | Auto-start scheduler |
| `MONGODB_SYNC_INTERVAL_SECONDS` | 300 | — |
| `SAVE_LEGACY_RAW_CSV` | 0 | Set `1` để bật CSV raw |

---

## 7. Constants quan trọng (hard-coded)

```python
# src/preprocessing.py
TARGET_SAMPLE_RATE_HZ = 130
WINDOW_SECONDS = 30
SAMPLES_PER_WINDOW = 3900

# src/api/pipeline.py
REALTIME_SAMPLE_RATE_HZ = 130
WINDOW_SIZE = 10              # anomaly window (số RR)
STEP_SIZE = 5

# src/features/acc_features.py
FS_ACC_HZ = 25
# ACC_VM_STD thresholds (mặc định, có thể override qua sensor_context_config):
#   < 20  mG → REST
#   < 80  mG → SLOW_WALK
#   < 300 mG → WALK
#   ≥ 300 mG → ACTIVE
FALL_IMPACT_THRESHOLD_MG = 2000
FALL_STRONG_IMPACT_MG = 2800
FALL_FREE_FALL_THRESHOLD_MG = 500

# src/features/stress_features.py
STRESS_WINDOW_SECONDS = 300.0
STRESS_STEP_SECONDS = 60.0
MIN_RR_PER_WINDOW = 20

# src/inference/hr_event.py
MIN_RELIABLE_HR_EVENT_SECONDS = 29.0

# Polar BLE UUIDs (src/api/pipeline.py:206-210)
HR_UUID         = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL     = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA        = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
POLAR_DEVICE_NAME = "Polar H10"
DEFAULT_POLAR_ADDRESS = "24:AC:AC:13:EB:86"
```

---

## 8. SQLite schema (tham khảo nếu app đọc DB trực tiếp)

DB path: `dataset/realtime_logs/ecg_monitor.db`. Schema đầy đủ ở `src/storage/ecg_storage.py:67-293`.

Bảng chính:
- `predictions` (prediction_id PK, session_id, patient_id, timestamp, timestamp_epoch, sample_rate_hz, window_count, heart_rate_bpm, **emotion_json, stress_json, anomaly_json, rhythm_json, ectopy_json, hr_event_json, af_episode_json, rhythm_alert_json, signal_quality_json, risk_json, sensor_context_json**, alert_level, message, raw_ecg_path, raw_acc_path, raw_ecg_chunk_ids_json, raw_acc_chunk_ids_json, created_at). `emotion_json` được giữ để backward compat.
- `events` (event_id PK, prediction_id, session_id, patient_id, timestamp, timestamp_epoch, event_type, severity, label, message, heart_rate_bpm, activity_state, metadata_json).
- `raw_signal_chunks` (chunk_id PK, signal_type ∈ {ecg, acc}, timestamp_start_unix, sample_rate_hz, sample_count, channel_count, encoding, **payload_blob** zlib-compressed, is_baseline_usable, is_synced, …). Encoding: `int32_le_zlib` cho ECG, `float32x4_le_zlib` cho ACC (x_mg,y_mg,z_mg,vm_mg).
- `guided_baseline_sessions`, `guided_baseline_segments`.
- `collection_sessions`, `collection_segments`.
- `assessment_snapshots` (snapshot_type ∈ {risk_summary, session_summary, daily_summary, daily_health_assessment, health_report}, payload_json, period_json).

---

## 9. Lifecycle khuyến nghị cho app

```
1. App khởi động
   ├── (Optional) connect WS /ws/vitals
   └── poll GET /health để biết model nào loaded

2. User bấm "Start Polar"
   └── POST /polar/start  → backend tự stream + predict mỗi 30s
                            → push qua WS / cập nhật /latest-result

3. UI render mỗi prediction
   ├── GET /latest-result        (hoặc nhận từ WS)
   ├── GET /latest-ecg           (vẽ waveform)
   ├── GET /session-summary?days=1
   ├── GET /daily-health-assessment?hours=24
   ├── GET /health-report?...
   └── GET /events?days=1&limit=20

4. User bấm "Update 7-Day Baseline"
   └── POST /personal-baseline/update-progressive {patient_id, target_days:7, …}

5. Lần đầu: Guided baseline flow
   POST /guided-baseline/start
     → render 3 segment cards với instruction từ segment_plan
     → user click "Start REST" → app gọi
        POST /guided-baseline/segment/complete {session_id, segment_type:"REST", started_at, ended_at}
     → tương tự WALK, ACTIVE
     → POST /guided-baseline/complete-day {session_id}

6. User bấm "Stop"
   └── POST /polar/stop
```

---

## 10. Pitfalls / quirks app dev cần biết

1. `RhythmFeaturePredictor` và `EctopyFeaturePredictor` **validate strict schema** lúc load. Nếu file `*_feature_schema.json` không khớp `RHYTHM_FEATURE_COLUMNS` / `ECTOPY_FEATURE_COLUMNS`, predictor sẽ trả `{label: "unknown", reason: "...schema mismatch..."}`. App phải hiển thị gracefully.
2. `rhythm_cnn_predictor.loaded` có thể = false nếu chưa có file `.pt` hoặc thiếu `torch`. Khi đó `model_source` của rhythm sẽ là `rhythm_feature_model` (do `RHYTHM_PREDICTOR_MODE` fallback). App có thể show badge "CNN unavailable" dựa vào `health.rhythm_cnn_model_loaded`.
3. `_get_af_tracker(patient_id)` lưu state trong RAM. Khi restart server, AF burden/count reset về 0 trừ khi rebuild từ history. App KHÔNG nên tin tuyệt đối `af_episode.af_burden_percent` qua restart; có thể dùng `compute_session_summary` thay.
4. Stress dùng **rolling RR buffer 300s, step 60s**. Trong 1–5 phút đầu sẽ luôn trả `unknown` với reason `warming_up_stress_window`. App cần show "warming up" thay vì error.
5. `signal_quality.label = "poor"` short-circuit toàn bộ pipeline. App cần highlight phần này thật rõ vì sẽ mute mọi card khác.
6. `sensor_context = {}` (object rỗng) khi không gửi ACC samples. App phải null-safe trên mọi field bên trong.
7. Timestamps: backend đa số dùng ISO 8601 UTC. `timestamp_epoch` (Unix seconds float) chỉ có ở row từ DB.
8. `compute_*` endpoints (risk-summary, session-summary, daily-health-assessment, health-report) đều **save snapshot** vào `assessment_snapshots`. App có thể query lịch sử snapshots qua `/storage/assessment-snapshots`.
9. CORS đã mở `*` cho mọi origin (`src/api/pipeline.py:1198-1204`). App web frontend trên domain khác kết nối được ngay.
10. Polar collector LƯU sample khi chạy. Nếu app gọi `/ingest-ecg` thủ công song song với Polar đang chạy → sẽ có duplicate predictions cùng patient_id.

---

## 11. Tham chiếu nhanh code

| Cần làm | File:line |
|---|---|
| Hiểu output `predict_ecg` | `src/api/pipeline.py:750-913` |
| Sửa ngưỡng alert rhythm | `src/inference/alert_engine.py` + `models/runtime/sensor_context_config.json::rhythm_alert` |
| Sửa quy tắc HR event | `src/inference/hr_event.py:17-64` |
| Thêm event type mới | `src/storage/ecg_storage.py::build_events_for_prediction:727-843` |
| Stress feature list | `src/features/stress_features.py:8-21` |
| Rhythm feature list | `src/features/rhythm_features.py:11-53` |
| Ectopy feature list | `src/features/ectopy_features.py:21-29` |
| Activity classification | `src/features/acc_features.py:126-130` |
| Fall detection | `src/features/acc_features.py:133-259` |
| AF episode logic | `src/inference/af_episode_tracker.py:20-77` |
| Personal baseline build | `src/calibration/personal_baseline.py:197-291` |
| Guided baseline plan | `src/calibration/guided_baseline.py:16-39` |
| Dashboard HTML cũ (reference) | `src/api/pipeline.py:1216-1881` |
| FastAPI endpoints | `src/api/pipeline.py:1883-2407` |

---

## 12. Checklist khi modify folder `app`

- [ ] Rename mọi reference "emotion" / "Emotion" → "stress" / "Stress" trong UI, model layer, API client.
- [ ] Bỏ field cũ `emotion.probabilities` (vui/buồn/neutral) khỏi UI.
- [ ] Thêm card / màn hình cho 8 module mới: rhythm, ectopy, AF episode, HR event, signal quality, activity, fall, hr_context_alert.
- [ ] Cập nhật alert levels: thêm `medium / critical / unknown` ngoài `normal / high`.
- [ ] Hỗ trợ `risk.level` riêng (`low / medium / high / unknown`).
- [ ] Render `signal_quality.reasons` (array) khi label != good/fair.
- [ ] Render `findings[]` từ `/daily-health-assessment` và 3-layer report từ `/health-report`.
- [ ] Render `events[]` từ `/events` với filter theo `event_type` và `severity`.
- [ ] Hỗ trợ Personal Baseline UI: comparisons (HR delta, REST HR delta, AF/anomaly/ectopy delta), trạng thái `not_ready/warming_up/ready`.
- [ ] Hỗ trợ Guided Baseline UI: 7-day flow + REST/WALK/ACTIVE segments + instruction tiếng Việt/Anh.
- [ ] Kết nối WebSocket `/ws/vitals` thay vì polling `/latest-result`.
- [ ] Xử lý null cho `heart_rate_bpm`, fields trong `sensor_context`, `stress` warming-up case.
- [ ] Cập nhật waveform endpoint: chuyển sang `/latest-ecg` (downsampled tới `max_samples` qua query).
- [ ] Update mọi `POST /ingest-ecg` payload: thêm `acc_samples` nếu có, sample_rate đúng 130.
- [ ] Theo dõi `/health` để hiển thị badge "model not loaded" (rhythm_cnn_model_loaded, ectopy_model_loaded, …).
- [ ] Nếu app có tính năng MongoDB sync trigger, gắn vào `/sync/mongodb` hoặc `/storage/sync-scheduler/*`.

---

_File này là single source of truth khi AI sửa folder `app`. Nếu phát hiện model thay đổi (rename label, thêm field), update tài liệu này trước, sau đó update app._
