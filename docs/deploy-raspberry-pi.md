# Hướng dẫn Deploy ElderlyCareModel lên Raspberry Pi

Ngày cập nhật: 2026-05-25
Phiên bản hệ thống: pipeline với 5 model (rhythm, ectopy, stress, anomaly_legacy, sensor_context)
Đối tượng: kỹ sư triển khai chạy backend 24/7 trên Raspberry Pi 4/5 thu Polar H10 BLE,
lưu SQLite local, đồng bộ MongoDB Atlas (tuỳ chọn), phục vụ Flutter app qua HTTP/WebSocket.

---

## Mục lục

1. [Tổng quan kiến trúc deploy](#1-tổng-quan-kiến-trúc-deploy)
2. [Yêu cầu phần cứng + phần mềm](#2-yêu-cầu-phần-cứng--phần-mềm)
3. [Bước 0: Chuẩn bị gói deploy trên PC](#bước-0-chuẩn-bị-gói-deploy-trên-pc)
4. [Bước 1: Flash Raspberry Pi OS](#bước-1-flash-raspberry-pi-os)
5. [Bước 2: Đăng nhập SSH lần đầu](#bước-2-đăng-nhập-ssh-lần-đầu)
6. [Bước 3: Cài lib hệ thống + Bluetooth](#bước-3-cài-lib-hệ-thống--bluetooth)
7. [Bước 4: Chuyển zip từ PC sang Pi](#bước-4-chuyển-zip-từ-pc-sang-pi)
8. [Bước 5: Giải nén + tạo virtualenv Python](#bước-5-giải-nén--tạo-virtualenv-python)
9. [Bước 6: Cài Python dependencies](#bước-6-cài-python-dependencies)
10. [Bước 7: Cấu hình `.env`](#bước-7-cấu-hình-env)
11. [Bước 8: Pair Polar H10 qua Bluetooth](#bước-8-pair-polar-h10-qua-bluetooth)
12. [Bước 9: Test foreground (chạy thử bằng tay)](#bước-9-test-foreground-chạy-thử-bằng-tay)
13. [Bước 10: Setup systemd service (chạy 24/7)](#bước-10-setup-systemd-service-chạy-247)
14. [Bước 11: Smoke test sau khi systemd chạy](#bước-11-smoke-test-sau-khi-systemd-chạy)
15. [Bước 12: Cron jobs bảo trì](#bước-12-cron-jobs-bảo-trì)
16. [Bước 13: Test reboot survival](#bước-13-test-reboot-survival)
17. [Bước 14: Soak test 6–24 giờ](#bước-14-soak-test-624-giờ)
18. [Troubleshooting](#troubleshooting)
19. [Quy trình cập nhật (deploy bản mới)](#quy-trình-cập-nhật-deploy-bản-mới)
20. [Rollback khi update fail](#rollback-khi-update-fail)
21. [Phụ lục: lệnh vận hành thường dùng](#phụ-lục-lệnh-vận-hành-thường-dùng)

---

## 1. Tổng quan kiến trúc deploy

```
┌──────────────────────────────────────────────────────────────────┐
│  Polar H10 (BLE) ──► Raspberry Pi 4/5 ──► WiFi router            │
│     ECG @ 130Hz       FastAPI :8000        Flutter app           │
│     ACC @ 25Hz        SQLite local         MongoDB Atlas         │
└──────────────────────────────────────────────────────────────────┘
            │
            ▼
   uvicorn (systemd service)
            │
            ├─► load_models() at boot (5 .pkl + 4 .json)
            ├─► BLE collector (bleak) ─── connects to Polar H10
            ├─► SQLite WAL DB at /home/<user>/elderly_care/data/
            ├─► background_sync to MongoDB (mỗi 5 phút, tuỳ chọn)
            └─► HTTP REST + WebSocket /ws/vitals cho Flutter
```

Output cuối cùng:

- Service tự khởi động khi Pi boot
- Tự reconnect Polar khi rớt BLE
- Tự sync SQLite lên MongoDB (nếu bật)
- Tự purge raw chunks đã sync sau 24h
- Tự VACUUM SQLite + integrity check hàng tuần

---

## 2. Yêu cầu phần cứng + phần mềm

### Phần cứng

| Mục | Khuyến nghị | Tối thiểu | Ghi chú |
|-----|------------|-----------|---------|
| Pi model | Pi 5 (8GB) hoặc Pi 4 (4GB) | Pi 4 (2GB) | Pi 3 không đủ ổn định cho sklearn + BLE + sync |
| OS | Raspberry Pi OS 64-bit Bookworm Lite | — | 64-bit khuyến nghị cho scientific Python wheels |
| SD card | 32GB Class A2 (Samsung EVO Plus, SanDisk Extreme) | 16GB | Class A1 chạy được nhưng SQLite chậm |
| Nguồn | USB-C 5V/3A chính hãng | 5V/2.5A | Nguồn yếu → BLE rớt, kernel panic |
| Tản nhiệt | Heatsink + fan PWM | Heatsink thụ động | Khi inference CPU 50–75°C, nóng quá throttle |
| Mạng | Ethernet hoặc WiFi 5GHz | WiFi 2.4GHz | Atlas TLS handshake yếu mạng → sync chậm |
| Bluetooth | Built-in BLE 5.0 (Pi 4/5 có sẵn) | — | Polar H10 dùng BLE 4.0+ |

### Phần mềm (sẽ cài ở bước 3 và 6)

- Python 3.11+ (Bookworm có sẵn)
- BlueZ + bluez-tools
- SQLite 3
- Python lib: scikit-learn, fastapi, uvicorn, bleak, neurokit2, pymongo, wfdb, scipy, numpy, pandas, joblib, httpx, astropy, paho-mqtt

---

## Bước 0: Chuẩn bị gói deploy trên PC

Trên máy phát triển (Windows), chạy script `pack_for_pi.ps1` ở root project:

```powershell
cd D:\DATN\elderly_care-amine\elderly_care-amine
.\pack_for_pi.ps1
```

Script này:

- Copy `src/` + `models/` + `pipeline.py` + `requirements.txt` + `MODEL_NOTES.md`
- Loại bỏ `src/training/`, `src/dataset_builders/`, `src/evaluation/`, metrics PNG, `__pycache__`
- Nén ra `D:\DATN\elderly_care-amine\elderly_care-amine\elderly_care_deploy.zip`

Xác nhận zip chứa đủ artifact:

```powershell
$arch = [System.IO.Compression.ZipFile]::OpenRead("D:\DATN\elderly_care-amine\elderly_care-amine\elderly_care_deploy.zip")
$arch.Entries | Where-Object FullName -match '\.(pkl|json)$' | Sort-Object FullName | Select-Object FullName, Length
$arch.Dispose()
```

Phải có 9 file `.pkl` + các file `.json` schema/config.

---

## Bước 1: Flash Raspberry Pi OS

1. Tải **Raspberry Pi Imager**: https://www.raspberrypi.com/software/
2. Cắm SD card vào PC qua đầu đọc thẻ
3. Mở Imager:
   - **Device**: Raspberry Pi 4 (hoặc 5)
   - **OS**: Raspberry Pi OS (64-bit) → **Bookworm Lite** (KHÔNG cần GUI, tiết kiệm RAM)
   - **Storage**: SD card
4. Bấm **Ctrl+Shift+X** (Advanced options) — bắt buộc cấu hình trước khi flash:
   - ☑ Set hostname: `elderlycare` (khuyến nghị để app dùng `elderlycare.local`, không cần tìm IP thủ công)
   - ☑ Enable SSH (password authentication)
   - ☑ Set username/password: ví dụ `custard` / `<mật khẩu>`
   - ☑ Configure wireless LAN: SSID + password WiFi
   - ☑ Set locale: `Asia/Ho_Chi_Minh`, keyboard `us`
5. **Write** → đợi 5–10 phút
6. Cắm SD card vào Pi → cấp nguồn → đợi 1–2 phút cho boot lần đầu

**Lưu ý:** Username dùng trong toàn bộ tài liệu này là `custard`. Nếu bạn dùng username khác (như `pi`, `huyma`...), **thay tất cả `/home/custard/` thành `/home/<username>/`** trong các lệnh dưới.

---

## Bước 2: Đăng nhập SSH lần đầu

Trên PC Windows (PowerShell hoặc Windows Terminal):

```powershell
ssh custard@elderlycare.local
```

Lần đầu sẽ hỏi "Are you sure you want to continue connecting?" → gõ `yes` → nhập password.

**Nếu `elderlycare.local` không resolve**: kiểm tra `avahi-daemon`, cùng Wi-Fi/LAN, hoặc tìm IP Pi trên admin router rồi:

```powershell
ssh custard@<IP_PI>
```

Verify đã login đúng Pi:

```bash
uname -a
# Phải in: Linux raspberrypi 6.x ... aarch64
```

Nếu thấy `armv7l` thay vì `aarch64` → bạn đã flash bản 32-bit. Nên flash lại bản 64-bit để cài scientific Python wheels ổn định hơn.

---

## Bước 3: Cài lib hệ thống + Bluetooth

```bash
sudo apt update && sudo apt upgrade -y

sudo apt install -y \
    python3-pip python3-venv python3-dev \
    libatlas-base-dev libopenblas-dev gfortran \
    bluetooth bluez libbluetooth-dev \
    libffi-dev libssl-dev \
    sqlite3 git unzip nano htop \
    libgomp1 avahi-daemon
```

Quá trình mất 5–15 phút tuỳ tốc độ mạng.

Bật Bluetooth và verify:

```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
sudo systemctl enable --now avahi-daemon
sleep 2
hciconfig hci0
```

Kỳ vọng thấy:

```
hci0:   Type: Primary  Bus: UART
        BD Address: XX:XX:XX:XX:XX:XX  ACL MTU: ...
        UP RUNNING
        ...
```

Nếu thấy `DOWN`:

```bash
sudo hciconfig hci0 up
```

Vẫn fail → reboot Pi (`sudo reboot`) + check lại sau khi boot.

---

## Bước 4: Chuyển zip từ PC sang Pi

**Trên PC Windows (mở PowerShell mới, KHÔNG phải SSH terminal):**

```powershell
scp D:\DATN\elderly_care-amine\elderly_care-amine\elderly_care_deploy.zip elcaprj@elderlycare.local:/home/elcaprj/
```

Verify trên Pi:

```bash
ls -lh /home/elcaprj/elderly_care_deploy.zip
```

Phải thấy size ~4.2M.

---

## Bước 5: Giải nén + tạo virtualenv Python

```bash
cd /home/elcaprj
unzip elderly_care_deploy.zip -d elderly_care
cd elderly_care
ls
```

Phải thấy: `src/  models/  pipeline.py  requirements.txt  MODEL_NOTES.md`

Tạo virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
```

Tạo thư mục data/logs (absolute path):

```bash
mkdir -p /home/elcaprj/elderly_care/data
mkdir -p /home/elcaprj/elderly_care/logs
```

---

## Bước 6: Cài Python dependencies

### 6.1 — Cài production dependencies

```bash
source /home/elcaprj/elderly_care/.venv/bin/activate
pip install -r requirements.txt
```

Production realtime dùng rhythm feature model, nên không cần PyTorch/Torch trên Raspberry Pi.

### 6.2 — Optional: cài CNN research dependencies

```bash
pip install -r requirements-research.txt
```

Chỉ dùng bước này nếu muốn chạy lại CNN rhythm research. Không cần cho demo realtime.

### 6.3 — Verify

```bash
python -c "import sklearn, neurokit2, bleak, fastapi, pymongo; print('OK', sklearn.__version__)"
```

Phải in `OK 1.8.0` không lỗi. Artifact rhythm/ectopy hiện tại được train bằng `scikit-learn==1.8.0`; nếu Pi đang cài `1.9.0`, pickle model có thể lỗi `_loss` và rhythm/ectopy sẽ thành `unknown`.

File `requirements.txt` đã pin `scikit-learn==1.8.0`, nên chạy lại:

```bash
pip install -r requirements.txt
```

Lệnh sửa nhanh nếu version vẫn sai:

```bash
pip install --force-reinstall --no-cache-dir scikit-learn==1.8.0
```

---

## Bước 7: Cấu hình `.env`

```bash
nano /home/custard/elderly_care/.env
```

Dán toàn bộ template dưới (sửa giá trị MAC + MongoDB tuỳ tình huống):

```ini
# =============================================================
# ELDERLY CARE PI CONFIG
# =============================================================

# ---- Polar H10 BLE ----
# Thay bằng MAC của Polar H10 cụ thể (lấy ở Bước 8)
POLAR_H10_MAC=24:AC:AC:13:EB:86

# ---- Storage ----
# Relative path is resolved from WorkingDirectory=/home/elcaprj/elderly_care.
# This avoids accidentally writing to another Linux user's home folder.
ECG_DATA_DIR=./data
SAVE_LEGACY_RAW_CSV=0

# ---- MongoDB Atlas (để URI rỗng nếu chưa có cloud) ----
MONGODB_URI=
MONGODB_DB=elderly_care
MONGODB_BULK_BATCH_SIZE=200

# ---- Background sync scheduler ----
# Đặt MONGODB_SYNC_ENABLED=1 khi muốn bật auto-sync
MONGODB_SYNC_ENABLED=0
MONGODB_SYNC_INTERVAL_SECONDS=300
MONGODB_SYNC_DAYS=1
MONGODB_SYNC_LIMIT=5000
MONGODB_SYNC_INCLUDE_RAW_SAMPLES=0
MONGODB_SYNC_PURGE_AFTER_SYNC=1
MONGODB_SYNC_PURGE_RETENTION_HOURS=24
MONGODB_SYNC_PURGE_LIMIT=10000
MONGODB_SYNC_RUN_IMMEDIATELY=1
MONGODB_SYNC_LOG_PATH=logs/background_sync.log
MONGODB_SYNC_RUN_LOG_PATH=logs/background_sync_runs.jsonl

# ---- API server ----
API_HOST=0.0.0.0
API_PORT=8000

# ---- Logging ----
LOG_LEVEL=INFO

# ---- Polar collector auto-start ----
# Set to 1 on production Raspberry Pi after POLAR_H10_MAC is correct.
POLAR_AUTO_START=1
POLAR_AUTO_START_CHUNK_SECONDS=10
```

Save: `Ctrl+O` → `Enter` → `Ctrl+X`

⚠ Lưu ý quan trọng:

- `POLAR_H10_MAC` PHẢI giống MAC pair ở Bước 8 (cùng Pi vẫn pair được cho nhiều Polar H10 khác nhau)
- `ECG_DATA_DIR=./data` là cấu hình khuyến nghị khi systemd có `WorkingDirectory=/home/elcaprj/elderly_care`
- KHÔNG commit `.env` lên git (đã có `.env` trong `.gitignore` của project gốc)

---

## Bước 8: Pair Polar H10 qua Bluetooth

### 8.1 — Chuẩn bị Polar (BẮT BUỘC, hay quên)

Polar H10 chỉ active BLE khi cảm nhận da. Để khô trên bàn = OFF hoàn toàn.

- ☑ **Đeo Polar H10 lên ngực** đúng tư thế (dưới ngực, mặt trước Polar úp vào da)
- ☑ **Làm ướt 2 cực dây strap** bằng nước hoặc gel ECG (rất quan trọng)
- ☑ **Đóng app Polar Flow** trên điện thoại (Polar chỉ kết nối 1 thiết bị tại 1 thời điểm)
- ☑ Đợi 5–10 giây để Polar wake up

### 8.2 — Scan tìm MAC

```bash
sudo timeout 15 bluetoothctl --timeout 10 scan on 2>&1 | grep -i polar
```

Kỳ vọng:

```
[NEW] Device 24:AC:AC:13:EB:86 Polar H10 ABCDEF12
```

→ MAC = `24:AC:AC:13:EB:86` (6 cặp hex)

Nếu không thấy → quay lại 8.1 (Polar chưa active).

### 8.3 — Pair + trust + connect

```bash
bluetoothctl
```

Trong shell `bluetoothctl`:

```
power on
agent on
default-agent
scan on
```

Đợi 10–20s thấy MAC Polar:

```
scan off
trust 24:AC:AC:13:EB:86
pair 24:AC:AC:13:EB:86
connect 24:AC:AC:13:EB:86
info 24:AC:AC:13:EB:86
```

Lệnh `info` phải in:

```
Paired: yes
Trusted: yes
Connected: yes (hoặc no, không sao)
```

Thoát:

```
disconnect 24:AC:AC:13:EB:86
exit
```

(Disconnect bluetoothctl để bleak có thể tự connect, không bị conflict.)

### 8.4 — Cập nhật `.env` nếu MAC khác

Nếu MAC khác với template ở Bước 7, sửa:

```bash
nano /home/custard/elderly_care/.env
# Sửa dòng POLAR_H10_MAC=24:AC:AC:13:EB:86
```

---

## Bước 9: Test foreground (chạy thử bằng tay)

Mục đích: verify backend load model đủ, server lên port 8000 OK trước khi cài systemd.

```bash
cd /home/custard/elderly_care
source .venv/bin/activate
uvicorn src.api.pipeline:app --host 0.0.0.0 --port 8000
```

Kỳ vọng thấy log:

```
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Mở SSH terminal #2 (giữ terminal #1 chạy uvicorn):

```bash
ssh custard@elderlycare.local
curl -s http://localhost:8000/health | python3 -m json.tool
```

Kỳ vọng:

```json
{
  "status": "ok",
  "sklearn_version": "1.8.0",
  "required_sklearn_version": "1.8.0",
  "sklearn_version_ok": true,
  "stress_model_loaded": true,
  "anomaly_enabled": true,
  "anomaly_calibration_enabled": false,
  "anomaly_runtime_status": "enabled_global_legacy",
  "anomaly_model_loaded": true,
  "rhythm_model_loaded": true,
  "ectopy_model_loaded": true,
  "rhythm_decision_config_loaded": true,
  "sensor_context_config_loaded": true,
  ...
}
```

Trong dashboard browser từ PC: `http://elderlycare.local:8000/dashboard` cũng phải lên.

Sau khi verify OK, quay lại terminal #1 nhấn **`Ctrl+C`** để dừng uvicorn. Sang Bước 10.

---

## Bước 10: Setup systemd service (chạy 24/7)

### 10.1 — Tạo unit file

```bash
sudo cp /home/elcaprj/elderly_care/deploy/systemd/elderly-care.service /etc/systemd/system/elderly-care.service
sudo nano /etc/systemd/system/elderly-care.service
```

Dán:

```ini
[Unit]
Description=Elderly Care ECG/ACC Pipeline (FastAPI)
After=network-online.target bluetooth.target
Wants=network-online.target bluetooth.target

[Service]
Type=simple
User=elcaprj
Group=elcaprj
WorkingDirectory=/home/elcaprj/elderly_care
EnvironmentFile=/home/elcaprj/elderly_care/.env
ExecStart=/home/elcaprj/elderly_care/.venv/bin/uvicorn src.api.pipeline:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
StandardOutput=append:/home/elcaprj/elderly_care/logs/uvicorn.log
StandardError=append:/home/elcaprj/elderly_care/logs/uvicorn.err.log

# BLE permissions (CAP_NET_RAW cần cho bleak)
AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN

# Resource caps cho Pi (Pi 4 4GB)
MemoryMax=1500M
TasksMax=200

[Install]
WantedBy=multi-user.target
```

Save: `Ctrl+O` → `Enter` → `Ctrl+X`

### 10.2 — Reload systemd + enable + start

```bash
sudo systemctl daemon-reload
sudo systemctl enable elderly-care
sudo systemctl start elderly-care
sleep 5
sudo systemctl status elderly-care --no-pager
```

Kỳ vọng:

```
● elderly-care.service - Elderly Care ECG/ACC Pipeline (FastAPI)
     Loaded: loaded (/etc/systemd/system/elderly-care.service; enabled; ...)
     Active: active (running) since ...
     Main PID: NNNNN (uvicorn)
     ...
```

Nếu thấy `failed`:

```bash
sudo systemctl status elderly-care --no-pager
tail -50 /home/custard/elderly_care/logs/uvicorn.err.log
```

→ Đọc lỗi, sửa, restart: `sudo systemctl restart elderly-care`

---

## Bước 11: Smoke test sau khi systemd chạy

```bash
echo "=== Service status ==="
sudo systemctl is-active elderly-care

echo "=== Health ==="
curl -s http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'status={d[\"status\"]}, sklearn={d[\"sklearn_version\"]}, sklearn_ok={d[\"sklearn_version_ok\"]}, models_ok={all([d[\"rhythm_model_loaded\"], d[\"stress_model_loaded\"], d[\"ectopy_model_loaded\"], d[\"anomaly_model_loaded\"]])}, anomaly={d[\"anomaly_runtime_status\"]}, calibration={d[\"anomaly_calibration_enabled\"]}, polar_addr={d[\"polar\"][\"address\"]}')"

echo "=== Storage ==="
curl -s http://localhost:8000/storage/status | python3 -m json.tool | head -15

echo "=== Process ==="
ps aux | grep "[u]vicorn"

echo "=== Listening port ==="
sudo ss -tlnp | grep 8000
```

Owner của process uvicorn phải là `custard`, KHÔNG phải user đăng nhập terminal.

### Test BLE collector

Đảm bảo Polar đã đeo lên ngực + strap ướt + app phone đóng.

```bash
curl -X POST http://localhost:8000/polar/start
sleep 3
curl -s http://localhost:8000/health | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d['polar']
print(f'running={p[\"running\"]}, address={p[\"address\"]}, last_error={p[\"last_error\"]}')
"
```

Đợi 60 giây cho chunk ECG đầu tiên hoàn thành:

```bash
sleep 60
curl -s http://localhost:8000/latest-result | python3 -m json.tool
```

Kỳ vọng có `heart_rate_bpm`, `rhythm`, `stress`, `signal_quality`, `alert_level`.

**Nếu lỗi `Device with address ... was not found`** → xem [Troubleshooting](#troubleshooting) phần BLE.

---

## Bước 12: Cron jobs bảo trì

```bash
crontab -e
# Chọn 1 (nano) nếu hỏi editor
```

Dán vào cuối file:

```cron
# Integrity check SQLite hằng ngày 03:00
0 3 * * * cd /home/custard/elderly_care && /home/custard/elderly_care/.venv/bin/python -c "from src.storage.ecg_storage import integrity_check; import json; print(json.dumps(integrity_check()))" >> /home/custard/elderly_care/logs/integrity.log 2>&1

# WAL checkpoint Chủ Nhật 04:00 (truncate WAL file để khỏi phình)
0 4 * * 0 sqlite3 /home/custard/elderly_care/data/ecg_monitor.db "PRAGMA wal_checkpoint(TRUNCATE);" >> /home/custard/elderly_care/logs/wal.log 2>&1

# Xoá log uvicorn cũ hằng tháng (>50MB)
0 5 1 * * find /home/custard/elderly_care/logs -name "*.log*" -size +50M -delete
```

Save + thoát. Verify:

```bash
crontab -l
```

---

## Bước 13: Test reboot survival

Đây là test cuối — đảm bảo service tự động chạy khi Pi mất điện rồi boot lại.

```bash
sudo reboot
```

Pi mất kết nối ~30 giây. SSH lại:

```bash
ssh custard@elderlycare.local
```

Verify service đã tự khởi động:

```bash
sudo systemctl status elderly-care --no-pager | head -5
curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"
```

In ra `ok` = systemd hoạt động đúng. **Service đã 24/7-ready.**

---

## Bước 14: Soak test 6–24 giờ

Sau khi tất cả ổn, chạy soak test để đảm bảo không có memory leak hay BLE rớt sau nhiều giờ:

```bash
# Từ PC hoặc Pi khác
ssh custard@elderlycare.local

# Đảm bảo Polar đang đeo
curl -X POST http://localhost:8000/polar/start

# Trên PC dev (KHÔNG phải Pi), chạy soak test client
# (cần code src/services/soak_test.py — chỉ có ở dev environment, không trong deploy zip)
python -m src.services.soak_test \
    --base-url http://elderlycare.local:8000 \
    --duration-minutes 360 \
    --check-storage \
    --sync-every 10 \
    --purge-after-sync
```

Trong lúc soak test chạy, monitor Pi từ SSH:

```bash
# Tab 1: log realtime
tail -f /home/custard/elderly_care/logs/uvicorn.log

# Tab 2: tài nguyên
htop
# Quan sát RAM uvicorn, CPU%, nhiệt độ

# Tab 3: DB size
watch -n 60 "ls -lh /home/custard/elderly_care/data/ecg_monitor.db"

# Tab 4: nhiệt độ CPU
watch -n 30 vcgencmd measure_temp
```

Tiêu chí PASS sau 6h:

| Chỉ số | Ngưỡng |
|--------|--------|
| RAM uvicorn | <800MB (Pi 4 4GB) |
| CPU% trung bình | <50% |
| Nhiệt độ CPU | <75°C |
| DB size growth | ~2–5MB/giờ (raw chunks) |
| BLE reconnect | 0 lần (hoặc <3 lần do trượt strap) |
| MongoDB sync (nếu bật) | 100% success |
| Service crash | 0 |

---

## Troubleshooting

### A. Lỗi BLE: `Device with address ... was not found`

**Nguyên nhân theo thứ tự phổ biến:**

1. **Polar chưa active** (90% trường hợp) — chưa đeo / strap khô
2. App Polar Flow trên điện thoại đang connect
3. Polar hết pin
4. BLE adapter Pi stuck

**Fix tuần tự:**

```bash
# 1. Verify Polar đang advertise
sudo timeout 15 bluetoothctl --timeout 10 scan on 2>&1 | grep -i polar
# Phải thấy [NEW] Device 24:AC:AC:13:EB:86 Polar H10 ...
# Nếu không → đeo lại + làm ướt strap + đóng app phone

# 2. Reset BLE adapter
sudo systemctl restart bluetooth
sleep 3
sudo hciconfig hci0 up

# 3. Restart Polar collector
curl -X POST http://localhost:8000/polar/stop
sleep 2
echo -e "disconnect 24:AC:AC:13:EB:86\nexit" | bluetoothctl
sleep 2
curl -X POST http://localhost:8000/polar/start
sleep 8

# 4. Xem log
tail -20 /home/custard/elderly_care/logs/uvicorn.log
```

**Nếu vẫn fail sau 4 bước trên — re-pair toàn bộ:**

```bash
sudo systemctl stop elderly-care
echo -e "remove 24:AC:AC:13:EB:86\nexit" | bluetoothctl
sudo systemctl restart bluetooth
sleep 5

# Pair lại (Polar đang đeo + ướt)
bluetoothctl
# Trong shell: power on / agent on / scan on / scan off / trust / pair / info / exit

sudo systemctl start elderly-care
```

---

### B. Service crash loop trong systemd

Triệu chứng: `sudo systemctl status` show `failed` + restart liên tục.

```bash
# Xem lỗi cụ thể
sudo systemctl status elderly-care --no-pager
tail -50 /home/custard/elderly_care/logs/uvicorn.err.log
```

Các lỗi phổ biến:

| Lỗi | Nguyên nhân | Fix |
|-----|------------|-----|
| `ModuleNotFoundError: torch` khi chạy CNN research | venv chưa cài dependency nghiên cứu | `pip install -r requirements-research.txt` |
| `Permission denied: .../data/ecg_monitor.db` | systemd user khác chủ folder | `sudo chown -R custard:custard /home/custard/elderly_care` |
| `FileNotFoundError: models/...` | WorkingDirectory sai | Verify systemd unit có `WorkingDirectory=/home/custard/elderly_care` |
| `ValueError: MONGODB_URI is not configured` | EnvironmentFile không load | Đảm bảo `.env` có đúng format `KEY=VALUE` không space, không quote |
| `Address already in use` (port 8000) | Có process khác chiếm port | `sudo lsof -i:8000` → kill |

---

### C. `mongodb_sync_configured: false` dù đã set MONGODB_URI

Nguyên nhân: `.env` không load.

```bash
# Verify env file readable bởi systemd user
sudo -u custard cat /home/custard/elderly_care/.env | grep MONGODB_URI

# Restart service
sudo systemctl restart elderly-care

# Verify
curl -s http://localhost:8000/health | python3 -c "import sys,json; print(json.load(sys.stdin)['mongodb_sync_configured'])"
```

Nếu vẫn `false` → kiểm tra dấu cách thừa trong `.env`:

```ini
# SAI
MONGODB_URI = mongodb+srv://...
MONGODB_URI="mongodb+srv://..."

# ĐÚNG
MONGODB_URI=mongodb+srv://...
```

---

### D. `database is locked`

Hiếm gặp do code đã bật WAL + busy_timeout=30s. Nếu vẫn xảy ra:

```bash
# Force WAL checkpoint
sqlite3 /home/custard/elderly_care/data/ecg_monitor.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Integrity check
/home/custard/elderly_care/.venv/bin/python -c "from src.storage.ecg_storage import integrity_check; import json; print(json.dumps(integrity_check()))"

# Nếu corrupt → restore từ backup hoặc xoá DB
sudo systemctl stop elderly-care
mv /home/custard/elderly_care/data/ecg_monitor.db /home/custard/elderly_care/data/ecg_monitor.db.corrupt
sudo systemctl start elderly-care
# DB mới sẽ tự tạo khi connection đầu
```

---

### E. RAM tăng dần (leak)

```bash
# Monitor RAM của uvicorn
watch -n 30 "ps aux | grep '[u]vicorn' | awk '{print \$6/1024 \"MB\"}'"
```

Nếu RAM > 1GB sau 6h, kiểm tra:

1. `MONGODB_SYNC_PURGE_AFTER_SYNC=1` trong `.env` (purge raw chunks đã sync)
2. `MONGODB_SYNC_PURGE_RETENTION_HOURS=24` không quá lớn
3. Bật `MemoryMax=1500M` trong systemd unit (cap cứng)

---

### F. CPU 100% liên tục

```bash
# Check process nào tốn CPU
htop
# Press F6 → sort by CPU%
```

Nếu uvicorn 100% liên tục:

1. Window step quá ngắn → trong code mặc định 5s, không sửa được qua env
2. Có request /storage/raw-chunks?include_payload=true gọi liên tục từ dashboard → check Flutter app
3. Multiple Polar reconnect (BLE flapping) → strap lỏng

---

### G. Pi reboot mất pairing Polar

Đôi khi sau reboot, `bluetoothctl info <MAC>` show `Paired: no`. Pair lại:

```bash
bluetoothctl
# power on / agent on / scan on / scan off
# trust <MAC> / pair <MAC> / exit
```

Vì đã `trust` lần trước nên pair sẽ nhanh, không cần PIN.

---

### H. Service không restart sau khi `sudo systemctl restart`

```bash
# Force kill + reset failed state
sudo systemctl reset-failed elderly-care
sudo systemctl stop elderly-care
sleep 3
sudo pkill -f "uvicorn src.api.pipeline" 2>/dev/null
sudo systemctl start elderly-care
sleep 5
sudo systemctl status elderly-care --no-pager
```

---

## Quy trình cập nhật (deploy bản mới)

Khi có bản code mới từ dev (zip mới):

### Trên PC

```powershell
# Tạo zip mới
& "C:\Users\<user>\Desktop\ElderlyCareModel\pack_for_pi.ps1"

# Copy sang Pi
scp C:\Users\<user>\Desktop\elderly_care_deploy.zip custard@elderlycare.local:/home/custard/
```

### Trên Pi

```bash
cd /home/custard

# 1. Backup state hiện tại
sudo systemctl stop elderly-care
cp /home/custard/elderly_care/.env /home/custard/.env.backup
cp -r /home/custard/elderly_care/data /home/custard/data.backup
cp -r /home/custard/elderly_care/.venv /home/custard/.venv.backup  # backup venv

# 2. Xoá code cũ + giải nén mới
rm -rf elderly_care
unzip elderly_care_deploy.zip -d elderly_care

# 3. Restore state
cp /home/custard/.env.backup elderly_care/.env
cp -r /home/custard/data.backup elderly_care/data
cp -r /home/custard/.venv.backup elderly_care/.venv

mkdir -p elderly_care/logs

# 4. Verify
cd elderly_care
source .venv/bin/activate
python -c "import sklearn, neurokit2, fastapi, bleak"

# 5. Update deps nếu requirements.txt thay đổi (so sánh với cũ)
# pip install --upgrade ...

# 6. Restart service
sudo systemctl start elderly-care
sleep 5
sudo systemctl status elderly-care --no-pager

# 7. Smoke test
curl -s http://localhost:8000/health | python3 -m json.tool | head -20

# 8. Nếu OK, xoá backup
rm /home/custard/.env.backup
rm -rf /home/custard/data.backup
rm -rf /home/custard/.venv.backup
```

---

## Rollback khi update fail

Nếu sau update service không chạy được:

```bash
cd /home/custard
sudo systemctl stop elderly-care

# Restore từ backup
rm -rf elderly_care
mv .venv.backup elderly_care/.venv  # KHÔNG, rollback đúng cách dưới

# (Cách đúng — bạn cần backup zip cũ trước khi update)
# unzip elderly_care_deploy.zip.OLD -d elderly_care
# cp .env.backup elderly_care/.env
# cp -r data.backup elderly_care/data
# cp -r .venv.backup elderly_care/.venv

sudo systemctl start elderly-care
```

→ **Best practice**: trước mỗi update, copy zip cũ thành `elderly_care_deploy.zip.OLD` để có rollback target.

---

## Phụ lục: lệnh vận hành thường dùng

### Setup production tu dong

Sau khi giai nen `elderly_care_deploy.zip` tren Raspberry Pi, co the cai toan bo production bang mot lenh:

```bash
cd /home/elcaprj/elderly_care
bash scripts/install_pi_production.sh
```

Script nay tu dong:

- dat hostname thanh `elderlycare`
- cai va bat `avahi-daemon`, app truy cap qua `http://elderlycare.local:8000`
- cai system packages cho Python, Bluetooth/BlueZ, NetworkManager, mDNS, Mosquitto, SQLite
- tao/cap nhat `.venv`
- cai `requirements.txt`
- tao/cap nhat `.env`
- bat `POLAR_AUTO_START=1`
- tao `data/` va `logs/`
- cai, enable, restart `elderly-care.service`
- cai, enable, restart `elderly-care-wifi-provisioner.service`
- smoke test endpoint `/health`

Neu muon set MAC Polar ngay khi cai:

```bash
cd /home/elcaprj/elderly_care
POLAR_H10_MAC=24:AC:AC:13:EB:86 bash scripts/install_pi_production.sh
```

Neu muon cau hinh MongoDB sync ngay khi cai:

```bash
cd /home/elcaprj/elderly_care
POLAR_H10_MAC=24:AC:AC:13:EB:86 MONGODB_SYNC_ENABLED=1 MONGODB_URI='mongodb+srv://...' bash scripts/install_pi_production.sh
```

Sau khi chay xong, app nguoi deo nhap `elderlycare.local` hoac `http://elderlycare.local:8000`.

### Service control

```bash
sudo systemctl status elderly-care        # trạng thái
sudo systemctl restart elderly-care       # restart
sudo systemctl stop elderly-care          # dừng
sudo systemctl start elderly-care         # khởi động
sudo systemctl disable elderly-care       # tắt auto-start
sudo systemctl enable elderly-care        # bật auto-start
```

### Log viewing

```bash
# Log uvicorn (do StandardOutput=append: → đi vào file)
tail -f /home/custard/elderly_care/logs/uvicorn.log
tail -f /home/custard/elderly_care/logs/uvicorn.err.log

# Log background sync
tail -f /home/custard/elderly_care/logs/background_sync.log

# Log integrity check (cron)
tail -f /home/custard/elderly_care/logs/integrity.log

# Log systemd journal (chỉ stderr/startup, không có stdout của uvicorn)
sudo journalctl -u elderly-care -n 100 --no-pager
sudo journalctl -u elderly-care -f
```

### API endpoints quan trọng

```bash
# Health (verify model loaded + polar status)
curl -s http://localhost:8000/health | python3 -m json.tool

# Storage status (DB size, chunk count)
curl -s http://localhost:8000/storage/status | python3 -m json.tool

# Polar control
curl -X POST http://localhost:8000/polar/start
curl -X POST http://localhost:8000/polar/stop

# Latest prediction
curl -s http://localhost:8000/latest-result | python3 -m json.tool

# History
curl -s "http://localhost:8000/history?limit=10" | python3 -m json.tool

# Manual MongoDB sync
curl -X POST http://localhost:8000/storage/sync-mongodb \
  -H "Content-Type: application/json" \
  -d '{"patient_id":"polar_h10","days":1,"limit":5000}'

# Purge synced chunks
curl -X POST http://localhost:8000/storage/purge-synced \
  -H "Content-Type: application/json" \
  -d '{"retention_hours":24,"limit":10000}'

# Scheduler control
curl -s http://localhost:8000/storage/sync-scheduler/status | python3 -m json.tool
curl -X POST http://localhost:8000/storage/sync-scheduler/start
curl -X POST http://localhost:8000/storage/sync-scheduler/stop
curl -X POST http://localhost:8000/storage/sync-scheduler/run-once

# Dashboard (browser)
# http://elderlycare.local:8000/dashboard
# http://elderlycare.local:8000/docs   (Swagger)
```

### Bluetooth control

```bash
# Status BLE adapter
hciconfig hci0

# Restart Bluetooth
sudo systemctl restart bluetooth
sleep 3 && sudo hciconfig hci0 up

# Scan
sudo timeout 15 bluetoothctl --timeout 10 scan on 2>&1 | grep -i polar

# Info Polar
bluetoothctl info 24:AC:AC:13:EB:86

# Re-pair (Polar đang đeo)
echo -e "remove 24:AC:AC:13:EB:86\nexit" | bluetoothctl
bluetoothctl
# scan on / ... / pair / trust / exit
```

### Tài nguyên hệ thống

```bash
# CPU/RAM
htop

# Nhiệt độ
vcgencmd measure_temp

# Disk
df -h /
du -sh /home/custard/elderly_care/data/

# Network
ss -tlnp | grep 8000
ip addr show wlan0

# Process
ps aux | grep "[u]vicorn"
```

### Storage (SQLite)

```bash
# DB size
ls -lh /home/custard/elderly_care/data/

# Integrity check
/home/custard/elderly_care/.venv/bin/python -c "from src.storage.ecg_storage import integrity_check; import json; print(json.dumps(integrity_check()))"

# WAL checkpoint
sqlite3 /home/custard/elderly_care/data/ecg_monitor.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Stats
sqlite3 /home/custard/elderly_care/data/ecg_monitor.db "SELECT COUNT(*) FROM predictions; SELECT COUNT(*) FROM raw_signal_chunks; SELECT COUNT(*) FROM events;"

# VACUUM (defragment)
sqlite3 /home/custard/elderly_care/data/ecg_monitor.db "VACUUM;"
```

---

## Checklist hoàn tất deploy

Đánh dấu sau khi xác nhận từng mục:

- [ ] OS Pi: 64-bit Bookworm, SSH OK
- [ ] Bluetooth `UP RUNNING`
- [ ] zip giải nén vào `/home/custard/elderly_care/`
- [ ] venv tạo xong, `import sklearn, bleak, fastapi` không lỗi
- [ ] `.env` có `POLAR_H10_MAC` đúng + `ECG_DATA_DIR` absolute
- [ ] Polar H10 paired + trusted trong `bluetoothctl info`
- [ ] foreground `uvicorn` test trả `/health` = ok với `*_model_loaded: true`
- [ ] `elderly-care.service` enabled + active (running)
- [ ] Process `uvicorn` owner = `custard` (KHÔNG phải bạn login)
- [ ] `curl /polar/start` → đợi 60s → `/latest-result` có `heart_rate_bpm`
- [ ] Cron jobs added (integrity, wal, log clean)
- [ ] Reboot test: Pi tự khởi động service
- [ ] (Tuỳ chọn) Soak test 6h pass với RAM <800MB, CPU <50%, BLE không rớt

---

## Tham khảo các tài liệu khác

- `MODEL_NOTES.md` — chi tiết model + API endpoints
- `docs/trang-thai-he-thong-va-roadmap.md` — kiến trúc tổng thể + roadmap
- `docs/integration-plan.md` — tích hợp ACC từ Polar
- `docs/soak-test-background-sync.md` — soak test MongoDB sync chi tiết
- `docs/van-hanh-he-thong-app-model-cloud.md` — vận hành end-to-end app + cloud

---

Hết.
 
---

## Phu luc: Wi-Fi provisioning production

Neu Raspberry Pi duoc dua sang nha moi va khong con truy cap duoc Wi-Fi cu, su dung captive portal AP Mode -> Client Mode trong:

```text
docs/wifi-provisioning-production.md
```

Service production moi:

```text
elderly-care-wifi-provisioner.service
```

Trang thai provisioning duoc backend tra trong `/health` tai field `network_provisioning`.
