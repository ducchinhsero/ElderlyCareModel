# Kien Truc Tich Hop Stress Detection

Pham vi: tich hop model `thhuy12/StressDetection` vao backend ElderlyCareModel va thay public output `emotion` cu bang `stress`.

## Quyet dinh ky thuat

- Khong dung Git submodule.
- Khong dung emotion model 3 lop trong API chinh.
- Public output moi la `stress`.
- Label stress la binary: `non_stress`, `stress`, `unknown`.
- WESAD dataset mac dinh nam tai `data_raw/wesad`.
- WESAD path co the override bang bien moi truong `WESAD_ROOT` hoac CLI `--wesad-root`.
- Artifact model nam tai `models/stress/`.

## Artifact contract

Sau khi train, folder `models/stress/` can co:

```text
models/stress/rf_model.pkl
models/stress/svm_pipeline.pkl
models/stress/scaler_final.pkl
models/stress/model_metadata.json
models/stress/stress_feature_schema.json
models/metrics/stress_metrics.json
```

Trong GitHub chi nen commit `.gitkeep`, schema/metadata nho neu can. File `.pkl` khong commit.

## Feature contract

Stress model dung RR/HRV feature 12 cot:

```text
mean_rr
sdnn
rmssd
pnn50
lf_power
hf_power
lf_hf_ratio
lf_nu
hf_nu
sd1
sd2
sd1_sd2_ratio
```

Training va inference phai dung dung thu tu cot tren.

## Training

Lenh train:

```powershell
python -m src.training.train_stress_wesad --wesad-root data_raw/wesad --skip-importance
```

Training loader doc WESAD dang:

```text
data_raw/wesad/S2/S2.pkl
data_raw/wesad/S3/S3.pkl
...
data_raw/wesad/S17/S17.pkl
```

Nhãn WESAD:

- `1 -> non_stress`
- `2 -> stress`
- cac label khac bi loai khoi stress training v1.

## Realtime inference

StressDetection train theo window 300 giay, step 60 giay. Pipeline realtime thu Polar theo chunk ngan 30 giay, nen khong duoc ep stress predict tu tung chunk 30 giay.

Backend giu rolling RR buffer theo `patient_id`:

```text
Polar ECG chunk 30s
-> detect R-peaks
-> RR intervals
-> append rolling RR buffer 5-6 phut
-> chi predict stress khi buffer du window
```

Khi chua du du lieu, output:

```json
{
  "stress": {
    "label": "unknown",
    "value": null,
    "confidence": 0.0,
    "probabilities": {
      "non_stress": 0.0,
      "stress": 0.0
    },
    "model_version": "soft_voting_rf_svm_wesad",
    "window_seconds": 300.0,
    "reason": "warming_up_stress_window"
  }
}
```

Stress chi predict khi signal quality la `good` hoac `fair`. Signal quality kem thi `stress.label = unknown`.

## API output contract

`/ingest-ecg`, `/latest-result`, `/history`, `/health-report` tra public field:

```json
{
  "stress": {
    "label": "non_stress|stress|unknown",
    "value": 0,
    "confidence": 0.83,
    "probabilities": {
      "non_stress": 0.17,
      "stress": 0.83
    },
    "model_version": "soft_voting_rf_svm_wesad",
    "window_seconds": 300.0,
    "reason": null
  }
}
```

Khong dung public `emotion` nua. SQLite van giu cot `emotion_json` de DB cu khong loi, nhung row moi ghi `stress_json` va API moi chi tra `stress`.

## Alert/risk/report

- Rhythm/AFib/PVC/PAC/fall/signal quality van uu tien cao hon stress.
- Stress chi nang alert toi da `medium`.
- Neu activity la `WALK` hoac `ACTIVE`, stress-only alert bi suppress de tranh false positive do van dong.
- Daily health assessment tong hop `stress_pattern` khi stress lap lai trong tin hieu dang tin cay.

## Health endpoint

`GET /health` can co:

```json
{
  "stress_model_loaded": true,
  "stress_model_error": null,
  "stress_model_dir": "models/stress",
  "stress_model_window_seconds": 300.0
}
```

## Test gate

```powershell
python -m py_compile src\features\stress_features.py src\inference\stress_inference.py src\training\train_stress_wesad.py src\api\pipeline.py src\storage\ecg_storage.py
python -m unittest discover -s tests -q
```

## Viec Flutter app can doi

- Doi UI card/field tu `emotion` sang `stress`.
- Neu `stress.reason = warming_up_stress_window`, hien thi "dang thu du lieu nen stress chua san sang".
- Khong hien thi stress la chan doan y khoa; day chi la tin hieu sang loc sinh ly.
