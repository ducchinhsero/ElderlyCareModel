# Thu Thập Dữ Liệu Riêng Biệt (Real Data Collection)

**Ngày tạo:** 2026-05-28  
**Tính năng:** Collect real ECG/ACC data from Polar H10 wearable sensor  
**Vị trí file:** `src/services/collect_real_data.py`

---

## 1. Tổng quan

Tính năng này cho phép bạn **thu thập dữ liệu ECG và ACC riêng biệt** từ Polar H10 sensor trực tiếp vào các file CSV được lưu trữ có tổ chức.

### **Dữ liệu được thu thập:**
- ✅ **ECG:** Tín hiệu điện tim 130 Hz
- ✅ **ACC:** Gia tốc kế 25/50/100/200 Hz (có thể cấu hình)
- ✅ **RR:** Khoảng thời gian giữa các nhịp tim (ms)
- ✅ **Metadata:** Thông tin session, thống kê chất lượng

---

## 2. Nơi lưu trữ dữ liệu

### **Cấu trúc thư mục:**

```
data_raw/real_data/
├─ chinh/                              ← Person ID
│  ├─ rest/                            ← Activity state
│  │  └─ session_20260520_133721/      ← Session ID (timestamp)
│  │     ├─ ecg.csv
│  │     ├─ acc.csv
│  │     ├─ rr.csv
│  │     └─ metadata.json
│  ├─ walk/
│  │  └─ session_20260520_140000/
│  │     ├─ ecg.csv
│  │     ├─ acc.csv
│  │     ├─ rr.csv
│  │     └─ metadata.json
│  └─ active/
│     └─ session_20260520_150000/
│        └─ ...
├─ amine/                              ← Người khác
│  ├─ rest/
│  ├─ walk/
│  └─ active/
├─ huy/
├─ emna/
└─ vinh/
```

### **Các trạng thái hoạt động (state):**
```
rest    ← Người nằm/ngồi yên tĩnh
walk    ← Người đi bộ chậm
active  ← Người vận động mạnh
```

---

## 3. Các file được lưu

### **3.1 ecg.csv**
```
sample_index,ecg_value_uv,timestamp_iso
0,943,2026-05-20T13:42:39.700753+07:00
1,1076,2026-05-20T13:42:39.708+07:00
2,1210,2026-05-20T13:42:39.716+07:00
...
35186,950,2026-05-20T13:46:09.970+07:00
```

**Chi tiết:**
- **sample_index:** Thứ tự mẫu (0 → 35,186)
- **ecg_value_uv:** Giá trị ECG (µV)
- **timestamp_iso:** Thời gian ISO 8601
- **Frequency:** 130 Hz (7.7 ms giữa mẫu)

### **3.2 acc.csv**
```
sample_index,acc_x_mg,acc_y_mg,acc_z_mg,vector_magnitude_mg,timestamp_iso
0,1000,0,0,1000,2026-05-20T13:42:39.700753+07:00
1,1010,-5,10,1012,2026-05-20T13:42:39.740+07:00
...
13752,995,2,1005,1410,2026-05-20T13:46:35.000+07:00
```

**Chi tiết:**
- **acc_x_mg, acc_y_mg, acc_z_mg:** 3 trục gia tốc (mg)
- **vector_magnitude_mg:** Độ lớn tổng (√(x²+y²+z²))
- **Frequency:** 50 Hz (mặc định, có thể là 25/100/200 Hz)
- **Range:** 8G (mặc định, có thể là 2G/4G)

### **3.3 rr.csv**
```
rr_index,rr_interval_ms
0,923
1,945
2,918
...
358,932
```

**Chi tiết:**
- **rr_interval_ms:** Khoảng RR (R-peak to R-peak) tính bằng ms
- **Dùng để:** Tính heart rate variability (HRV)

### **3.4 metadata.json**
```json
{
  "person_id": "chinh",
  "state": "rest",
  "session_id": "session_20260520_133721",
  "device": "Polar H10",
  "device_address": "24:AC:AC:13:EB:86",
  "created_at": "2026-05-20T13:42:39.700753+07:00",
  "requested_duration_seconds": 300.0,
  "ecg_sample_rate_hz": 130,
  "acc_sample_rate_hz": 50,
  "acc_range_g": 8,
  "ecg_sample_count": 35186,
  "acc_sample_count": 13752,
  "rr_interval_count": 358,
  "ecg_duration_seconds": 270.66,
  "acc_duration_seconds": 275.04,
  "ecg_sample_loss_ratio": 0.08,
  "acc_sample_loss_ratio": 0.05,
  "collection_quality": "ok",
  "files": {
    "ecg": "data_raw\\real_data\\chinh\\rest\\session_20260520_133721\\ecg.csv",
    "acc": "data_raw\\real_data\\chinh\\rest\\session_20260520_133721\\acc.csv",
    "rr": "data_raw\\real_data\\chinh\\rest\\session_20260520_133721\\rr.csv"
  }
}
```

---

## 4. Lệnh để chạy

### **4.1 Cách đơn giản (tự động scan Polar H10)**

```bash
python -m src.services.collect_real_data \
  --person-id chinh \
  --state rest \
  --duration-seconds 330
```

**Ý nghĩa:**
- `--person-id chinh` → Lưu vào `data_raw/real_data/chinh/`
- `--state rest` → Lưu vào `data_raw/real_data/chinh/rest/`
- `--duration-seconds 330` → Thu 330 giây (~5.5 phút), sau khi bỏ ~30s warmup → ~300s usable

**Output:**
```
Saved real-data session: data_raw\real_data\chinh\rest\session_20260520_133721
Samples: ECG=35186 ACC=13752 RR=358
```

### **4.2 Với BLE address cố định**

```bash
python -m src.services.collect_real_data \
  --person-id chinh \
  --state active \
  --duration-seconds 600 \
  --address 24:AC:AC:13:EB:86
```

**Ý nghĩa:**
- `--address 24:AC:AC:13:EB:86` → Kết nối trực tiếp (không scan)
- `--duration-seconds 600` → Thu 10 phút

### **4.3 Cấu hình ACC (Accelerometer)**

```bash
python -m src.services.collect_real_data \
  --person-id chinh \
  --state walk \
  --duration-seconds 300 \
  --acc-sample-rate-hz 100 \
  --acc-range-g 4
```

**Tùy chọn ACC:**
- `--acc-sample-rate-hz`: 25, 50, 100, 200 Hz (mặc định: 50 Hz)
- `--acc-range-g`: 2, 4, 8 G (mặc định: 8 G)

### **4.4 Custom output path**

```bash
python -m src.services.collect_real_data \
  --person-id chinh \
  --state rest \
  --duration-seconds 300 \
  --output-root my_custom_folder/data
```

**Output:**
```
my_custom_folder/data/chinh/rest/session_20260520_140000/
├─ ecg.csv
├─ acc.csv
├─ rr.csv
└─ metadata.json
```

### **4.5 Custom session ID**

```bash
python -m src.services.collect_real_data \
  --person-id chinh \
  --state rest \
  --duration-seconds 300 \
  --session-id chinh_baseline_morning
```

**Output:**
```
data_raw/real_data/chinh/rest/chinh_baseline_morning/
```

---

## 5. Ví dụ sử dụng thực tế

### **Scenario: Thu thập 4 sessions từ 1 người**

```bash
# Session 1: Baseline (người nằm yên)
python -m src.services.collect_real_data \
  --person-id chinh \
  --state rest \
  --duration-seconds 300 \
  --session-id chinh_baseline_20260528_morning

# Session 2: Walking (người đi bộ)
python -m src.services.collect_real_data \
  --person-id chinh \
  --state walk \
  --duration-seconds 300 \
  --session-id chinh_walk_20260528_morning

# Session 3: Active (người vận động)
python -m src.services.collect_real_data \
  --person-id chinh \
  --state active \
  --duration-seconds 300 \
  --session-id chinh_active_20260528_morning

# Session 4: Stress test (người tập lực)
python -m src.services.collect_real_data \
  --person-id chinh \
  --state active \
  --duration-seconds 300 \
  --session-id chinh_stress_20260528_morning
```

**Kết quả:**
```
data_raw/real_data/chinh/
├─ rest/
│  └─ chinh_baseline_20260528_morning/
│     ├─ ecg.csv
│     ├─ acc.csv
│     ├─ rr.csv
│     └─ metadata.json
├─ walk/
│  └─ chinh_walk_20260528_morning/
│     └─ ...
└─ active/
   ├─ chinh_active_20260528_morning/
   │  └─ ...
   └─ chinh_stress_20260528_morning/
      └─ ...
```

---

## 6. Tham số chi tiết

| Tham số | Kiểu | Mặc định | Yêu cầu? | Ý nghĩa |
|---|---|---|---|---|
| `--person-id` | str | - | **Bắt buộc** | Tên người (chinh, amine, huy, ...) |
| `--state` | str (rest/walk/active) | - | **Bắt buộc** | Trạng thái hoạt động |
| `--duration-seconds` | float | 330 | Tuỳ chọn | Thời gian thu (giây) |
| `--address` | str | None | Tuỳ chọn | BLE MAC address; nếu omit → auto scan |
| `--scan-timeout` | float | 20 | Tuỳ chọn | Timeout scan BLE (giây) |
| `--output-root` | str | data_raw/real_data | Tuỳ chọn | Thư mục lưu trữ |
| `--session-id` | str | session_YYYYMMDD_HHMMSS | Tuỳ chọn | ID session tùy chỉnh |
| `--acc-sample-rate-hz` | int (25/50/100/200) | 50 | Tuỳ chọn | ACC frequency |
| `--acc-range-g` | int (2/4/8) | 8 | Tuỳ chọn | ACC range |

---

## 7. Dữ liệu có sẵn trong dự án

### **Người bệnh đã thu thập:**
```
data_raw/real_data/
├─ chinh/      ← ~5 session (rest/walk/active)
├─ amine/      ← ~5 session
├─ huy/        ← ~5 session
├─ emna/       ← ~5 session
└─ vinh/       ← ~5 session
```

### **Sessions mẫu:**
```
data_raw/real_data/chinh/
├─ rest/
│  └─ session_20260520_133721/    (300s, 35K ECG samples)
├─ walk/
│  └─ session_20260520_135000/    (300s, ...)
└─ active/
   └─ session_20260520_140000/    (300s, ...)
```

---

## 8. Liên kết với đánh giá (Evaluation)

Dữ liệu được thu thập có thể được **đánh giá tự động** bằng:

```bash
python -m src.evaluation.evaluate_real_data \
  --input-root data_raw/real_data/chinh/rest/session_20260520_133721 \
  --patient-id chinh \
  --output-root data_processed/real_data_eval
```

**Output:**
```
data_processed/real_data_eval/chinh/
├─ predictions.csv      (rhythm, AF, stress, heart_rate per 30s window)
├─ events.csv           (alerts và anomalies)
├─ summary.json         (overall statistics)
└─ events.json          (detailed event timeline)
```

---

## 9. Best Practices

### **✅ Do's**

```bash
# ✅ Thu nhiều sessions để có dữ liệu phong phú
python -m src.services.collect_real_data --person-id chinh --state rest --duration-seconds 300
python -m src.services.collect_real_data --person-id chinh --state walk --duration-seconds 300

# ✅ Đặt tên descriptive session
--session-id "chinh_morning_rest_baseline"
--session-id "chinh_evening_walk_after_meal"

# ✅ Kiểm tra metadata.json để xác nhận chất lượng
cat data_raw/real_data/chinh/rest/session_20260520_133721/metadata.json

# ✅ Thu tối thiểu 300 giây usable data
--duration-seconds 330  (30s warmup + 300s usable)
```

### **❌ Don'ts**

```bash
# ❌ Quá ngắn (< 300 giây usable)
--duration-seconds 60  # → Cảnh báo "collection_quality": "short"

# ❌ State không hợp lệ
--state sleeping  # → Error: must be one of {rest, walk, active}

# ❌ ACC rate không được hỗ trợ
--acc-sample-rate-hz 75  # → Error: must be one of {25, 50, 100, 200}
```

---

## 10. Troubleshooting

### **Problem: "Could not find Polar H10"**
```
Error: Could not find Polar H10 during BLE scan.

Nguyên nhân:
├─ Polar H10 chưa bật
├─ Không trong phạm vi Bluetooth
├─ Bluetooth gateway đang kết nối device khác

Giải pháp:
├─ Bật Polar H10 trước 30 giây
├─ Để gateway gần Polar H10 (~10m)
├─ Dùng --scan-timeout 30 để scan lâu hơn
└─ Hoặc dùng --address 24:AC:AC:13:EB:86 nếu biết MAC
```

### **Problem: "No ACC samples were collected"**
```
Warning: no ACC samples were collected.

Nguyên nhân:
├─ ACC stream chưa start
├─ BLE connection bị gián đoạn

Giải pháp:
├─ Thử lại session mới
├─ Kiểm tra --acc-sample-rate-hz và --acc-range-g valid
└─ Xem metadata["stats"]["acc_stream_started"]
```

### **Problem: "Collection quality: short"**
```
Warning: usable data is shorter than recommended.
ECG=150.5s, ACC=152.0s. Recommended usable duration is 300s.

Nguyên nhân:
├─ BLE disconnect sớm
├─ Duration quá ngắn

Giải pháp:
├─ Tăng --duration-seconds (khuyến 330s trở lên)
├─ Kiểm tra BLE connection stability
└─ Xem metadata["collection_quality"] và loss ratio
```

---

## Tham khảo

- **File chính:** `src/services/collect_real_data.py`
- **Hàm chính:** `collect_polar_session()`, `save_session()`, `async_main()`
- **Output folder:** `data_raw/real_data/{person_id}/{state}/{session_id}/`
- **Đánh giá:** `src/evaluation/evaluate_real_data.py`
- **Lưu trữ:** `src/storage/ecg_storage.py`
