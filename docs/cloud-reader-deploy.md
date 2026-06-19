# Cloud Reader — xem dữ liệu lịch sử khi Pi ở xa/offline

Khi Raspberry Pi + Polar ở xa hoặc tắt, người giám sát **vẫn cần xem dữ liệu
các ngày trước** (đã được Pi đồng bộ lên MongoDB Atlas). Dịch vụ **Cloud Reader**
(`src/api/cloud_reader.py`) giải quyết việc này: một API read-only đọc thẳng
MongoDB Atlas, **không cần Pi**.

## Phân tầng dữ liệu

| Loại | Nguồn | Đường đi |
|---|---|---|
| Realtime (nhịp tim live, cảnh báo tức thời) | Polar → Pi | App ↔ Pi qua **Tailscale** (Pi phải online) |
| Lịch sử / báo cáo theo ngày | **MongoDB Atlas** | App ↔ **Cloud Reader** (Pi có thể offline) |

Cloud Reader chỉ phục vụ phần lịch sử. Nó **nhẹ** (chỉ `fastapi`, `uvicorn`,
`pymongo` — không kéo theo sklearn/bleak), chạy được trên dyno PaaS miễn phí.

## Endpoint

- `GET /health` — công khai, kiểm tra kết nối Mongo (dùng cho health check PaaS).
- `GET /daily-report?date=YYYY-MM-DD&patient_id=polar_h10`
- `GET /daily-report/available-days?patient_id=polar_h10`

Tất cả (trừ `/health`) yêu cầu header `X-API-Key` khi bật auth.

## Biến môi trường

| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `MONGODB_URI` | ✅ | Cùng URI Atlas mà Pi đang sync |
| `MONGODB_DB` | — | Mặc định `elderly_care` |
| `CLOUD_API_KEY` | nên có | Khóa bí mật; app gửi qua `X-API-Key`. Không đặt thì fallback `API_KEY` |
| `CLOUD_API_AUTH_ENABLED` | — | Mặc định `1`. Chỉ đặt `0` khi test local |

## Deploy lên Render (blueprint có sẵn)

1. Push repo này lên GitHub.
2. Render → **New → Blueprint** → trỏ vào repo (đã có `render.yaml`).
3. Đặt **Environment** (secret): `MONGODB_URI`, `CLOUD_API_KEY`.
4. Deploy → nhận URL HTTPS công khai, ví dụ
   `https://elderly-care-cloud-reader.onrender.com`.
5. Kiểm tra: mở `…/health` (phải thấy `mongodb_reachable: true`).

> Railway/Fly tương tự: build `pip install -r requirements-cloud.txt`,
> start `uvicorn src.api.cloud_reader:app --host 0.0.0.0 --port $PORT`
> (Railway đọc `Procfile` sẵn có). Cùng bộ env vars.

## Trỏ app Flutter vào Cloud Reader

Vai trò **Người giám sát**:
1. **Địa chỉ / Cloud URL** = URL HTTPS của Cloud Reader.
2. **API key** = đúng giá trị `CLOUD_API_KEY`.
3. Tab **Báo cáo → icon lịch** → chọn ngày → xem báo cáo (đọc từ cloud, không
   cần Pi).

Realtime (tab Tổng quan) vẫn cần Pi online qua Tailscale; xem
[remote-access-tailscale.md](remote-access-tailscale.md).

## Bảo mật

- Dữ liệu ECG là PII y tế → **luôn bật `CLOUD_API_AUTH_ENABLED=1`** và dùng
  `CLOUD_API_KEY` đủ dài/ngẫu nhiên khi expose ra internet.
- Endpoint chỉ read-only; không có route ghi/xóa.
