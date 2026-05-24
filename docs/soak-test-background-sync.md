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

## 2. Soak Test

Soak test là kiểm thử chạy lâu để xem hệ thống có ổn định không. Script sẽ gửi ECG/ACC giả lập vào `/ingest-ecg`, kiểm tra storage, có thể gọi sync định kỳ và ghi log JSONL.

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

## 3. Kiểm tra mất mạng và sync bù

Quy trình test:

1. Chạy API và Polar collector hoặc soak test.
2. Tắt mạng trong vài phút.
3. Xem `/storage/status`, raw chunk chưa sync phải tăng lên.
4. Bật mạng lại.
5. Gọi `/storage/sync-scheduler/run-once` hoặc chờ scheduler tự chạy.
6. Kiểm tra MongoDB có thêm document và local raw chunk đã sync được purge theo chính sách.

## 4. Tiêu chí pass cho chạy dài hạn

Hệ thống được xem là ổn định sơ bộ nếu sau vài giờ:

- API không crash;
- dashboard vẫn cập nhật;
- `logs/background_sync.log` không có lỗi lặp liên tục;
- `logs/background_sync_runs.jsonl` có `status: ok` sau khi mạng ổn định;
- raw chunk chưa sync không tăng vô hạn khi mạng đã hoạt động;
- purge không xóa chunk chưa sync;
- `/storage/status` vẫn trả JSON bình thường.

