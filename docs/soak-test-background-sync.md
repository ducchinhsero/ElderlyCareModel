# Soak Test, Background Sync Scheduler, Logs

Tài liệu này dùng để kiểm tra hệ thống khi chạy lâu trên máy tính hoặc Raspberry Pi.

## 1. Background MongoDB Sync Scheduler

Scheduler chạy nền trong FastAPI để:

- đồng bộ SQLite local lên MongoDB;
- chỉ sync raw ECG/ACC chunk chưa đồng bộ;
- purge raw chunk local đã sync sau thời gian giữ lại;
- ghi log vận hành vào `logs/background_sync.log`;
- ghi từng lần chạy dạng JSONL vào `logs/background_sync_runs.jsonl`.

### Bật scheduler bằng `.env`

Thêm các biến sau vào `.env`:

```env
MONGODB_SYNC_ENABLED=1
MONGODB_SYNC_INTERVAL_SECONDS=300
MONGODB_SYNC_DAYS=1
MONGODB_SYNC_LIMIT=5000
MONGODB_SYNC_PURGE_AFTER_SYNC=1
MONGODB_SYNC_PURGE_RETENTION_HOURS=24
MONGODB_SYNC_PURGE_LIMIT=10000
MONGODB_SYNC_RUN_IMMEDIATELY=1
```

Không ghi MongoDB URI trực tiếp trong tài liệu hoặc commit.

### Endpoint điều khiển

```powershell
curl http://127.0.0.1:8000/storage/sync-scheduler/status
```

Chạy một lần thủ công:

```powershell
curl -X POST http://127.0.0.1:8000/storage/sync-scheduler/run-once `
  -H "Content-Type: application/json" `
  -d "{\"patient_id\":\"polar_h10\",\"days\":1,\"limit\":5000,\"purge_after_sync\":true}"
```

Bắt đầu scheduler thủ công:

```powershell
curl -X POST http://127.0.0.1:8000/storage/sync-scheduler/start `
  -H "Content-Type: application/json" `
  -d "{\"interval_seconds\":300,\"patient_id\":\"polar_h10\",\"days\":1}"
```

Dừng scheduler:

```powershell
curl -X POST http://127.0.0.1:8000/storage/sync-scheduler/stop
```

## 2. Soak Test Synthetic

Soak test synthetic là kiểm thử chạy lâu bằng ECG/ACC giả lập. Script sẽ gửi dữ liệu vào `/ingest-ecg`, kiểm tra storage, có thể gọi sync định kỳ và ghi log JSONL. Test này dùng để kiểm tra API/storage, không thay thế test Polar H10 thật.

### Chạy API

```powershell
uvicorn pipeline:app --host 127.0.0.1 --port 8000 --app-dir .
```

### Chạy soak test 30 phút

```powershell
python -m src.services.soak_test `
  --base-url http://127.0.0.1:8000 `
  --patient-id soak_test `
  --duration-minutes 30 `
  --interval-seconds 30 `
  --window-seconds 30 `
  --check-storage `
  --sync-every 10 `
  --purge-after-sync
```

Log kết quả nằm ở:

```text
logs/soak_test_runs.jsonl
```

Mỗi dòng là một JSON record gồm:

- thời điểm gửi dữ liệu;
- HTTP status;
- nhịp tim, rhythm, signal quality, risk;
- số raw ECG/ACC chunk;
- storage status;
- kết quả sync nếu có.

## 3. Soak Test Polar H10 thật trên Raspberry 24 giờ

Với test thật, không gửi ECG giả lập. Backend phải đang chạy trên Pi và Polar collector phải được start.

### Chuẩn bị

```bash
uvicorn pipeline:app --host 0.0.0.0 --port 8000 --app-dir .
```

Start Polar:

```bash
curl -X POST http://127.0.0.1:8000/polar/start
```

Kiểm tra:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/latest-result
curl http://127.0.0.1:8000/storage/status
```

### Chạy monitor 24 giờ

Chạy trên Pi hoặc một máy trong cùng LAN:

```bash
python -m src.services.pi_runtime_monitor \
  --base-url http://127.0.0.1:8000 \
  --patient-id polar_h10 \
  --duration-hours 24 \
  --interval-seconds 60 \
  --output logs/pi_soak_24h.jsonl
```

Nếu API auth đã bật:

```bash
python -m src.services.pi_runtime_monitor \
  --base-url http://127.0.0.1:8000 \
  --patient-id polar_h10 \
  --duration-hours 24 \
  --interval-seconds 60 \
  --api-key "$API_KEY" \
  --output logs/pi_soak_24h.jsonl
```

Monitor ghi:

- `/health`: model status, MQTT, Polar reconnect counters.
- `/latest-result`: prediction mới nhất.
- `/storage/status`: prediction count, DB/WAL size, raw chunks chưa sync.
- `/storage/sync-scheduler/status`: trạng thái sync nền.
- `/events`: event timeline gần nhất.
- CPU/RAM nếu có `psutil`.

### Review alert sai

Máy không thể tự biết alert đúng/sai nếu không có nhãn thật. Sau khi chạy 24 giờ, tạo file review thủ công nếu cần:

```csv
timestamp,event_type,severity,is_false_alert,note
2026-05-28T10:30:00+07:00,fall_candidate,high,true,Nguoi dung dang van dong manh
```

Lưu tại:

```text
logs/alert_review.csv
```

### Xuất report

```bash
python -m src.services.build_soak_report \
  --input logs/pi_soak_24h.jsonl \
  --alert-review logs/alert_review.csv \
  --summary-output logs/pi_soak_24h_summary.json \
  --report-output logs/pi_soak_24h_report.md
```

Report gồm:

- số prediction tăng thêm;
- số reconnect;
- max prediction gap;
- CPU/RAM min/avg/max;
- DB size đầu/cuối;
- số raw chunks chưa sync;
- MongoDB sync status;
- alert count theo loại;
- false alert count nếu đã review.

## 4. Kiểm tra MQTT với app/caregiver thật

Cài broker trên Pi:

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

`.env` tối thiểu:

```env
MQTT_ENABLED=1
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_TOPIC_PREFIX=elderly_care
MQTT_ALERT_MIN_LEVEL=medium
```

Theo dõi topic:

```bash
mosquitto_sub -h localhost -t "elderly_care/#" -v
```

Cần kiểm tra với app/caregiver:

- nhận `elderly_care/<patient_id>/vitals/live`;
- nhận `elderly_care/<patient_id>/alert`;
- mở lại app vẫn thấy retained latest alert;
- khi Pi/backend mất kết nối, app thấy `elderly_care/service/status` offline.

## 5. Kiểm tra mất mạng và sync bù

Quy trình test:

1. Chạy API và Polar collector hoặc soak test.
2. Tắt mạng trong vài phút.
3. Xem `/storage/status`, raw chunk chưa sync phải tăng lên.
4. Bật mạng lại.
5. Gọi `/storage/sync-scheduler/run-once` hoặc chờ scheduler tự chạy.
6. Kiểm tra MongoDB có thêm document và local raw chunk đã sync được purge theo chính sách.

## 6. Tiêu chí pass cho chạy dài hạn

Hệ thống được xem là ổn định sơ bộ nếu sau 24 giờ:

- API không crash;
- dashboard vẫn cập nhật;
- `logs/pi_soak_24h_report.md` được tạo thành công;
- RAM process không tăng liên tục;
- reconnect count thấp hoặc có hồi phục rõ ràng;
- `logs/background_sync.log` không có lỗi lặp liên tục;
- `logs/background_sync_runs.jsonl` có `status: ok` sau khi mạng ổn định;
- raw chunk chưa sync không tăng vô hạn khi mạng đã hoạt động;
- purge không xóa chunk chưa sync;
- MQTT app/caregiver nhận được alert retained;
- `/storage/status` vẫn trả JSON bình thường.
