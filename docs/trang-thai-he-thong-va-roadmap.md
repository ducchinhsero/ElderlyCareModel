# Trang Thai He Thong Va Roadmap Phat Trien

Ngay cap nhat: 2026-05-24  
Du an: Elderly Care ECG/ACC monitoring with Polar H10, edge AI, Flutter app, MongoDB sync

## 1. Muc tieu chinh cua he thong

He thong duoc xay dung de theo doi suc khoe nguoi cao tuoi theo thoi gian thuc bang Polar H10 va ung dung Flutter. Backend chay tren may tinh/Raspberry Pi lam edge server, thu ECG/ACC, xu ly model, luu tru local, dong bo cloud va tra output cho app.

Muc tieu san pham:

- Theo doi realtime: heart rate, rhythm status, AFib suspicion, PVC/PAC-like activity, signal quality, fall/activity context.
- Bao cao suc khoe theo thoi gian: hien tai, 24 gio, 7 ngay.
- Canh bao bat thuong: AF suspicion, tachycardia, bradycardia, ectopy, fall candidate, poor signal.
- Hieu chinh baseline ca nhan 7 ngay co huong dan REST/WALK/ACTIVE.
- Luu raw ECG/ACC day du de phuc vu calibration, phan tich dai han va mo rong model benh ly.
- Dong bo MongoDB Atlas de phuc vu cloud/caregiver/backup.

He thong chi dua ra risk/suspicion/screening output, khong ket luan chan doan y khoa chac chan.

## 2. Kien truc hien tai

Luồng chinh:

```text
Polar H10 / Flutter App
        ↓
FastAPI backend tren edge
        ↓
Xu ly ECG/ACC + model inference
        ↓
SQLite local buffer + raw ECG/ACC BLOB chunks
        ↓
MongoDB Atlas sync
        ↓
Flutter app dashboard/report/alerts
```

Backend entrypoint:

```powershell
uvicorn pipeline:app --host 0.0.0.0 --port 8000 --app-dir .
```

Dashboard backend:

```text
http://127.0.0.1:8000/dashboard
```

Flutter app folder:

```text
D:\DATN\app
```

Backend folder:

```text
D:\DATN\elderly_care-amine\elderly_care-amine
```

## 2.1 Thu muc du lieu ngoai GitHub

Cac thu muc sau khong day len GitHub vi chua du lieu lon, du lieu runtime local hoac ECG/ACC ca nhan:

```text
dataset/realtime_logs/
dataset/collected/
data_raw/
```

Nguoi phat trien can tai tu Google Drive va dat dung vao project root:

```text
https://drive.google.com/drive/folders/1MxtozBqBwf7SvtdJsg9ONMA4V-0SLR6G?usp=drive_link
```

Y nghia:

- `dataset/realtime_logs/`: SQLite runtime DB, raw ECG/ACC chunks, personal baseline, calibration data, sync/log runtime.
- `dataset/collected/`: du lieu ECG/ACC ca nhan da thu thuc te, dung cho calibration/evaluation.
- `data_raw/`: dataset goc lon nhu WESAD, CinC 2017, AFDB, MITDB, NSTDB. GitHub chi giu `.gitkeep`.

Khong commit cac thu muc tren len GitHub neu chua co quy uoc Git LFS/private data repository.

## 3. Cac phan da hoan thanh

### 3.1 Realtime ECG pipeline

Da co:

- Thu ECG/ACC tu Polar H10.
- Xu ly ECG theo sample rate client gui hoac Polar H10 realtime.
- Signal quality check.
- Tachycardia/bradycardia rule theo context.
- Fall/activity context tu ACC.
- Output JSON qua `/latest-result`.
- Dashboard backend hien waveform, signal quality, risk, rhythm, activity, fall.

Endpoint lien quan:

- `GET /latest-result`
- `GET /latest-ecg`
- `POST /polar/start`
- `POST /polar/stop`
- `POST /ingest-ecg`

### 3.2 Rhythm model

Da co:

- Rhythm feature model cho:
  - `normal`
  - `possible_afib`
  - `other_rhythm`
  - `noise`
- CNN rhythm model da train va so sanh, nhung feature model hien tot hon theo ket qua gan nhat.
- Feature model duoc chon lam model chinh hien tai.
- Co bao cao so sanh CNN vs feature model trong:

```text
docs/so-sanh-rhythm-cnn-feature-model.md
```

Ket luan hien tai:

- Feature rhythm model dung duoc cho demo va screening.
- Chua du manh de coi la chan doan y khoa.
- Can tiep tuc cai thien dataset, threshold tuning, calibration ca nhan va validation tren du lieu thuc.

### 3.3 PVC/PAC / ectopy model

Da them phase MIT-BIH Arrhythmia mo rong PVC/PAC.

Da co:

- Ectopy feature model.
- Output PVC/PAC-like activity.
- Event `ectopy_suspicion`.
- Hien thi trong app/report.

### 3.4 Daily Health Assessment va Health Report

Da co:

- `/daily-health-assessment`
- `/health-report`
- Bao cao 3 tang thoi gian:
  - realtime
  - 24 gio
  - long-term 7 ngay
- Output gom:
  - overall level
  - data quality
  - findings
  - evidence
  - recommendations
  - disclaimer

Luu y wording:

- Dung “risk”, “suspicion”, “screening”.
- Khong dung “ban mac benh X”.

### 3.5 Event timeline

Da co bang `events` trong SQLite.

Loai event hien co:

- `af_suspicion`
- `ectopy_suspicion`
- `tachycardia`
- `bradycardia`
- `fall_candidate`
- `poor_signal`
- `hr_context`

Endpoint:

- `GET /events`
- `POST /events/rebuild`

### 3.6 Guided 7-Day Personal Baseline

Da chuyen baseline 7 ngay tu thu dong sang flow co huong dan.

Flow moi:

- Moi ngay app huong dan nguoi dung lam:
  - `REST`: 5 phut
  - `WALK`: 5 phut
  - `ACTIVE`: 3 phut, van dong nhe, co the skip neu khong an toan
- Timer chi chay khi:
  - signal quality `good` hoac `fair`
  - activity khop trang thai yeu cau
- Khi segment dat, raw chunks lien quan duoc danh dau usable cho baseline.

Endpoint:

- `GET /guided-baseline/status`
- `POST /guided-baseline/start`
- `POST /guided-baseline/segment/complete`
- `POST /guided-baseline/complete-day`

Flutter:

- Profile co guided baseline wizard.
- Dashboard co banner nhac tien do baseline.

### 3.7 Storage local tren SQLite

Da nang cap storage theo huong chuyen nghiep cho Raspberry:

- Khong luu tung ECG sample thanh tung row.
- Luu raw ECG/ACC theo chunk 5 giay.
- Luu payload dang BLOB nen bang zlib.

Bang moi:

- `raw_signal_chunks`
- `collection_sessions`
- `collection_segments`
- `assessment_snapshots`
- `guided_baseline_sessions`
- `guided_baseline_segments`

Bang cu van dung:

- `predictions`
- `events`

Encoding:

- ECG: `int32_le_zlib`
- ACC: `float32x4_le_zlib`

CSV raw legacy da tat mac dinh:

```env
SAVE_LEGACY_RAW_CSV=0
```

Neu can debug legacy CSV:

```env
SAVE_LEGACY_RAW_CSV=1
```

Endpoint storage:

- `GET /storage/status`
- `GET /storage/raw-chunks`
- `GET /storage/raw-chunks/{chunk_id}`
- `GET /storage/collection-sessions`
- `GET /storage/assessment-snapshots`
- `POST /storage/sync-mongodb`
- `POST /storage/purge-synced`
- `GET /storage/sync-scheduler/status`
- `POST /storage/sync-scheduler/start`
- `POST /storage/sync-scheduler/stop`
- `POST /storage/sync-scheduler/run-once`

### 3.8 MongoDB Atlas sync

Da cau hinh MongoDB Atlas qua `.env`.

File `.env` khong duoc dua vao git vi `.gitignore` da co:

```text
.env
```

Bien moi truong can co:

```env
MONGODB_URI=<secret>
MONGODB_DB=elderly_care
SAVE_LEGACY_RAW_CSV=0
```

Da them env loader de backend tu doc `.env` ke ca khi chay tu cwd khac.

MongoDB collections du kien:

- `predictions`
- `events`
- `raw_signal_chunks`
- `collection_sessions`
- `collection_segments`
- `assessment_snapshots`
- `personal_baselines`
- `session_summaries`
- `risk_summaries`
- `sync_runs`

Da test:

- MongoDB ping ok.
- `/health` tra `mongodb_sync_configured: true` sau khi restart server.
- Sync thu cong voi du lieu gioi han nho tra `status: synced`.

### 3.9 Background sync scheduler va soak test

Da them:

- Background MongoDB sync scheduler trong `src/storage/background_sync.py`.
- Scheduler co the tu start khi `.env` co `MONGODB_SYNC_ENABLED=1`.
- Moi cycle sync SQLite len MongoDB, sau do purge raw chunks da sync neu bat `purge_after_sync`.
- Log text: `logs/background_sync.log`.
- Log JSONL tung lan sync: `logs/background_sync_runs.jsonl`.
- Soak test HTTP: `src/services/soak_test.py`.
- Tai lieu van hanh: `docs/soak-test-background-sync.md`.

Lenh soak test mau:

```powershell
python -m src.services.soak_test --base-url http://127.0.0.1:8000 --duration-minutes 30 --check-storage --sync-every 10 --purge-after-sync
```

## 4. Cac phan chua hoan thanh hoac can lam tiep

### 4.1 Can chay thu background sync tren thiet bi that

Background sync scheduler da co trong code, nhung can chay soak test voi Polar H10/Raspberry:

- Bat `MONGODB_SYNC_ENABLED=1`.
- Chay API lien tuc vai gio den 1 ngay.
- Kiem tra log `logs/background_sync.log`.
- Kiem tra JSONL `logs/background_sync_runs.jsonl`.
- Kiem tra MongoDB co document moi.
- Kiem tra SQLite khong tang vo han khi mang on dinh.

### 4.2 Chua test soak test dai han tren Raspberry bang Polar that

Can test tren Raspberry Pi:

- Chay lien tuc 6-24 gio.
- Kiem tra CPU/RAM.
- Kiem tra dung luong SQLite.
- Kiem tra Bluetooth Polar reconnect.
- Kiem tra MongoDB sync khi mat mang roi co mang lai.

### 4.3 Chua co production retention policy day du

Da co purge endpoint:

```text
POST /storage/purge-synced
```

Nhung can quy dinh ro:

- raw chunks giu local bao lau.
- baseline chunks giu bao lau.
- MongoDB raw chunks giu bao lau.
- co nen archive/export theo ngay hay khong.

Mac dinh hien tai:

- Chua xoa chunk chua sync.
- Chua xoa chunk baseline usable.
- Chi xoa chunk da sync va qua `retention_hours`.

### 4.4 Stress model da co adapter tich hop

Emotion model 3 lop cu da duoc thay trong API chinh bang stress model binary.

Can luu y:

- Public output moi la `stress`, khong dung `emotion`.
- Artifact nam tai `models/stress/`.
- Training entrypoint: `python -m src.training.train_stress_wesad --wesad-root data_raw/wesad`.
- Realtime stress can rolling RR buffer khoang 300 giay; khi chua du du lieu se tra `unknown`.

### 4.5 Model benh ly dai han chua hoan thanh

Da co nen tang:

- daily health assessment
- event timeline
- long-term report
- raw ECG/ACC storage
- MongoDB sync

Chua co:

- model chan doan benh ly dai han duoc train/validate rieng.
- clinical-grade diagnosis.
- validation tren du lieu thuc 1-7 ngay cua nhieu nguoi.

Huong tiep theo:

- Xay model/rule layer cho:
  - AF burden dai han
  - repeated tachy/brady events
  - PVC/PAC burden
  - poor signal corrected trend
  - fall/activity risk
- Output phai la “can trao doi nhan vien y te” hoac “nen di kham neu lap lai/co trieu chung”, khong chan doan chac chan.

### 4.6 App cloud/caregiver flow chua hoan tat hoan toan

Flutter app da co UI bao cao/canh bao/baseline.

Can lam tiep:

- Ket noi app caregiver voi cloud API that su neu backend duoc deploy cloud.
- Dinh nghia luong data tu Raspberry len cloud backend.
- Push notification that su qua FCM hoac backend notification service.

### 4.7 Chua dong goi Raspberry deployment

Can lam:

- Tao service systemd cho backend.
- Tao `.env.example`.
- Tao script start/stop.
- Tao script backup DB.
- Tao health monitor/restart neu Polar collector crash.

## 5. Trang thai on dinh hien tai

Ket luan ngan gon:

```text
He thong da on cho demo local va kiem thu chuc nang backend.
Chua nen coi la production-stable neu chua chay soak test tren Raspberry 1-2 ngay.
```

Da kiem tra gan nhat:

- `python -m py_compile` cho cac module storage/MongoDB/API: pass.
- `python -m unittest discover -s tests -q`: pass, 77 tests.
- FastAPI TestClient:
  - `/health`: MongoDB configured true.
  - `/storage/status`: ok.
- MongoDB Atlas:
  - ping ok.
  - database: `elderly_care`.
- Model health:
  - rhythm model loaded true.
  - ectopy model loaded true.

Can kiem tra bang tay sau khi restart uvicorn:

```text
http://127.0.0.1:8000/health
```

Ket qua mong muon:

```json
{
  "mongodb_sync_configured": true,
  "rhythm_model_loaded": true,
  "ectopy_model_loaded": true
}
```

Neu `mongodb_sync_configured` van la `false`:

- Restart uvicorn.
- Dam bao chay tu folder backend.
- Kiem tra `.env` co `MONGODB_URI`.
- Dam bao khong copy URI vao code/report.

## 6. Lenh van hanh quan trong

Chay backend:

```powershell
cd D:\DATN\elderly_care-amine\elderly_care-amine
.\.venv\Scripts\Activate.ps1
uvicorn pipeline:app --host 0.0.0.0 --port 8000 --app-dir .
```

Kiem tra health:

```text
http://127.0.0.1:8000/health
```

Kiem tra storage:

```text
http://127.0.0.1:8000/storage/status
```

Sync MongoDB thu cong:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/storage/sync-mongodb" `
  -ContentType "application/json" `
  -Body '{"patient_id":"polar_h10","days":1,"limit":5000}'
```

Purge local chunks da sync:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/storage/purge-synced" `
  -ContentType "application/json" `
  -Body '{"retention_hours":24,"limit":10000}'
```

Chay test backend:

```powershell
python -m unittest discover -s tests -q
```

Build Flutter web:

```powershell
cd D:\DATN\app
flutter build web --no-wasm-dry-run
```

## 7. Nguyen tac phat trien tiep theo

- Khong dua MongoDB URI/password vao markdown, git, log cong khai.
- Khong luu raw ECG tung sample thanh row SQLite.
- Uu tien raw BLOB chunks va metadata/index ro rang.
- Khong xoa raw local neu chua sync MongoDB thanh cong.
- Khong xoa baseline usable chunks neu baseline/calibration can trace lai.
- Output y khoa phai la screening/risk/suspicion, khong chan doan chac chan.
- Stress model WESAD hien co adapter/schema rieng; khi doi artifact phai chay lai unit test va kiem tra `/health`.
- Moi thay doi lon can chay:

```powershell
python -m unittest discover -s tests -q
```

## 8. Viec nen lam ngay tiep theo

Uu tien 1:

- Them background sync scheduler 5 phut/lần.
- Neu sync thanh cong thi purge raw chunks da sync va qua retention.

Uu tien 2:

- Tao `.env.example` khong chua secret.
- Tao tai lieu Raspberry deployment/systemd.

Uu tien 3:

- Chay soak test Polar H10 6-24 gio.
- Ghi lai CPU/RAM/DB size/Mongo sync count/reconnect count.

Uu tien 4:

- Ket noi cloud/app caregiver hoan chinh.
- Them push notification that su.

Uu tien 5:

- Tiep tuc cai thien rhythm/PVC/PAC/long-term disease risk bang du lieu thuc va validation ro rang.
