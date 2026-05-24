# Ke hoach tich hop ACC tu ecg_acc_collector.py

## Muc tieu

Tich hop du lieu gia toc tu Polar H10 vao pipeline hien tai theo huong rule-based v1. He thong van giu nguyen prediction ECG/stress/anomaly hien co, dong thoi bo sung ngu canh van dong, phat hien nga va canh bao HR theo activity.

Nguon thuat toan chinh la `D:\DATN\PolarH10\ecg_acc_collector.py`. Cac collector thu nghiem `data_collector_acc_*`, `polar_realtime_processor.py`, `polar_data_collector.py` chi dung de doi chieu khi debug BLE, khong dua vao implementation chinh.

## Yeu cau v1

- ECG-only flow phai tiep tuc hoat dong khi khong co ACC.
- ACC khong thay doi schema feature cua emotion/anomaly model hien tai.
- Polar collector chay dual stream ECG 130 Hz va ACC 25 Hz.
- Ket qua prediction co them `sensor_context` gom `activity_state`, `activity_features`, `fall`, `hr_context_alert`.
- Raw ACC duoc luu song song raw ECG theo prediction/session.
- Dashboard hien thi tom tat activity, fall status, impact va HR context alert.

## Thiet ke trien khai

- `acc_features.py` gom parser va rule-based feature:
  - `parse_acc_packet` doc PMD ACC type `0x02`, header 10 byte, frame type 8/16/24-bit.
  - `classify_activity` phan loai REST/SLOW_WALK/WALK/ACTIVE theo `acc_vm_std`.
  - `detect_fall` tim chu ky free-fall -> impact -> post-still bang cac nguong tu `ecg_acc_collector.py`.
  - `summarize_acc_window` tao `sensor_context` cho pipeline.
- `pipeline.py`:
  - Gui `ECG_START_CMD` va `ACC_START_CMD` sau khi da bat notify `PMD_DATA`.
  - Neu ACC stream loi, tiep tuc ECG-only va ghi loi vao `polar_status`.
  - `predict_ecg` nhan optional `acc_samples` va `acc_sample_rate_hz`.
  - `strong_fall` uu tien canh bao `critical`; `fall_candidate` uu tien `high` neu alert ECG hien tai thap hon.
- `ecg_storage.py`:
  - Migration nhe them `sensor_context_json` va `raw_acc_path`.
  - Record cu thieu ACC van doc duoc voi `sensor_context = {}`.
  - Raw ACC CSV co cot `sample_index`, `time_seconds`, `x_mg`, `y_mg`, `z_mg`, `vm_mg`.

## Lo trinh cai tien model

- V1: rule-based ACC context, khong retrain model.
- V2: thu dataset ECG+ACC co label `fall`, `activity`, `normal_activity`, `stress_context`.
- V3: huan luyen fusion model ECG+ACC de giam false positive khi HR tang do van dong va tang do tin cay phat hien nguy co.

## Acceptance

- Unit tests cho ACC parser/activity/fall pass.
- ECG feature tests hien tai van pass.
- `predict_ecg` tra ket qua binh thuong khi khong co ACC.
- `predict_ecg` tra `sensor_context` khi co ACC.
- Dashboard `/dashboard` hien thi duoc activity va fall status tu `/latest-result`.
