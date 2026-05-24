# AF Episode - Cơn Rối Loạn Nhịp Xoang Nhĩ

**Ngày tạo:** 2026-05-21  
**Bối cảnh:** Hệ thống Elderly Care ECG phát hiện và theo dõi AF episodes realtime

---

## 1. AF là gì?

### 1.1 Định nghĩa Y tế

**AF = Atrial Fibrillation (Rối loạn nhịp xoang nhĩ)**

- **Bình thường:** Tim đập đều ~60-100 lần/phút; nhĩ co từng nhịp, tạo ECG wave P rõ ràng
- **AF:** Nhĩ rung tự nhiên (quiver) thay vì co nhịp → tín hiệu lộn xộn thay vì điều hòa

### 1.2 ECG Pattern của AF

```
Bình thường (Sinus Rhythm):
┌─┐     ┌─┐     ┌─┐     ┌─┐
│ │P├─┤ │ │P├─┤ │ │P├─┤ │ │P├─┤
└─┘     └─┘     └─┘     └─┘
  ↑ Wave P rõ ràng
  ↑ RR interval đều

AF (Atrial Fibrillation):
       ╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲╱╲
      ╱  ╲      (baseline rung loạn)  
    ╱        ╲╱╲╱╱╲╱╲╱╲╱╲╱
   ╱
  ↑ Không có wave P
  ↑ RR interval bất thường (irregular)
```

### 1.3 Nguy hiểm của AF

| Jeopardy | Chi tiết |
|---|---|
| **Stroke Risk** | AF làm máu trong nhĩ đông tắc → cục máu → stroke |
| **Heart Failure** | Tim bơm không hiệu quả → suy tim theo thời gian |
| **Syncope** | AF kèm HR nhanh có thể gây chóng mặt/bất tỉnh |
| **Sudden Death** | Hiếm nhưng có thể nếu AF degenerates thành VF |

### 1.4 Tương quan tuổi

- **Người trẻ:** AF hiếm (<0.1% ở 40 tuổi)
- **Người cao tuổi:** AF phổ biến (>5% ở 65 tuổi, >10% ở 80 tuổi)
- **Lý do:** Tuổi → perturb electrical conduction system tim

**→ Đây chính là lý do dự án Elderly Care focus vào AF detection**

---

## 2. AF Episode là gì?

### 2.1 Định nghĩa

**AF Episode = một cơn AF kéo dài từ lúc bắt đầu đến lúc kết thúc**

| Khái niệm | Ý nghĩa |
|---|---|
| **AF event** | 1 cửa sổ 30s có AF (window-level) |
| **AF episode** | Chuỗi liên tiếp AF events (≥ min_consecutive_windows) |
| **Episode start** | Lần đầu tiên đủ liên tiếp windows thỏa AF |
| **Episode end** | Khi không còn AF windows liên tiếp |
| **Episode duration** | Khoảng thời gian từ start → end |

### 2.2 Ví dụ thực tế

```
Timeline 30 giây mỗi cửa sổ (125 cửa sổ = 1 giờ):

Window#  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
Status   N  N  N  AF AF AF N  N  N  AF AF AF AF N  N
         └─────────┘  └─────────────────┘

Threshold: min_consecutive_windows = 2

Kết quả:
- Window 4-6: 3 cửa sổ AF liên tiếp → EPISODE #1 formed
  - Start: 4:00 (index 4 * 30s = 120s)
  - End: 6:30 (index 6 * 30s = 210s)
  - Duration: 90s = 1 phút 30 giây

- Window 10-13: 4 cửa sổ AF liên tiếp → EPISODE #2 formed
  - Start: 9:30
  - End: 13:00
  - Duration: 105s = 1 phút 45 giây
```

### 2.3 min_consecutive_windows = 2 (tại sao?)

**Đơn cửa sổ AF có thể là:**
- ✅ AFib thực sự
- ❌ Nhiễu cảm biến (movement artifact)
- ❌ Anomaly của feature extraction (R-peak detection lỗi)

**Yêu cầu ≥2 liên tiếp:**
- Giảm false positive từ 1 window lẻ
- AF episode thường kéo dài hơn 30 giây (temporal coherence)
- Trade-off: nhận ra AF muộn hơn ~30 giây, nhưng ít false alarm

```
Đơn window AF (reject):     AF AF
                            ||→ Cơ hội bỏ sót
                            ||
Chuỗi ≥2 windows (accept):  AF AF AF
                            ||||||→ Chắc chắn episode
                            ||||||
```

---

## 3. Cách hệ thống phát hiện AF Episode

### 3.1 Architecture trong dự án

```python
# File: src/inference/af_episode_tracker.py
class AFEpisodeTracker:
    def __init__(self, patient_id, episode_threshold=0.05, min_consecutive_windows=2):
        self.patient_id = patient_id
        self.episode_threshold = 0.05      # P(AFib) ≥ 0.05 → gọi là "AF window"
        self.min_consecutive_windows = 2   # Yêu cầu ≥2 liên tiếp
        self.state = {
            "active": False,                # Có cơn AF hiện tại?
            "current_episode_windows": 0,   # Số window trong cơn hiện tại
            "af_episode_count": 0,          # Tổng cộng bao nhiêu cơn
            "total_af_duration_sec": 0,     # Tổng giây AF
            "af_burden_percent": 0.0,       # AF burden = (total AF / total time) * 100
        }
    
    def update(self, rhythm_label, afib_probability):
        """
        Nhận output từ rhythm model mỗi 30 giây
        
        Tham số:
        - rhythm_label: "normal" / "possible_afib" / "other_rhythm" / "noise"
        - afib_probability: 0.0 - 1.0 (P(AFib) từ model)
        
        Hoạt động:
        1. Quyết định window hiện tại có AF không?
           → if afib_probability >= episode_threshold: this_window_is_af = True
        2. Update trạng thái episode:
           - Nếu this_window_is_af:
             - Increment counter
             - Nếu counter >= min_consecutive_windows → Episode formed
           - Nếu không:
             - Nếu episode active → Save episode, increment af_episode_count
             - Reset counter
        3. Tính AF burden
        4. Return state
        """
```

### 3.2 State machine của AF Episode

```
                          ┌──────────────┐
                          │  No Episode  │
                          │ (counter=0)  │
                          └──────────────┘
                                  │
                                  │ Window 1 is AF
                                  ↓
                          ┌──────────────┐
                          │ Possible EP  │
                          │ (counter=1)  │
                          └──────────────┘
                                  │
                     ┌────────────┴────────────┐
                     │                         │
        Window 2 is AF│                 │Window 2 is not AF
                     ↓                         ↓
             ┌──────────────┐         ┌──────────────┐
             │ EPISODE ON   │         │  No Episode  │
             │(active=True) │         │ (counter=0)  │
             │(counter≥2)   │         └──────────────┘
             └──────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
    Next is AF│              │Next is not AF
         │                       │
    (stay on) │              ↓
         │          ┌──────────────┐
         │          │ EPISODE OFF  │
         └─────────→│              │
                    │(save episode)│
                    │(active=False)│
                    │(counter=0)   │
                    └──────────────┘
                            │
                            │ Next is AF
                            ↓
                    ┌──────────────┐
                    │ Possible EP  │
                    │ (counter=1)  │
                    └──────────────┘
```

### 3.3 Realtime flow

```
Timeline:

[Polar H10] → [ECG 30s]
              ↓
         [Extract features]
              ↓
         [HistGradient model]
              ↓
         Output: {"label": "normal", "probabilities": {...}, "afib_prob": 0.12}
              ↓
         [AFEpisodeTracker.update(label, afib_prob)]
              ↓
         Decision tree:
         ├─ if afib_prob >= 0.05:
         │  ├─ consecutive_count++
         │  └─ if consecutive_count >= 2:
         │     └─ Episode formed! active=True
         │
         └─ else:
            ├─ if active==True:
            │  ├─ Save this episode
            │  ├─ af_episode_count++
            │  ├─ total_af_duration += duration
            │  ├─ af_burden = (total_af_duration / total_time) * 100
            │  └─ active=False
            └─ consecutive_count=0
         
         ↓
         Return:
         {
           "active": True/False,
           "current_episode_duration_sec": 120,  // seconds
           "af_episode_count": 2,                // total episodes today
           "total_af_duration_sec": 420,         // 7 minutes total
           "af_burden_percent": 2.3              // 2.3% of day is AF
         }
```

---

## 4. AF Burden - Metric quan trọng

### 4.1 Định nghĩa

```
AF Burden = (Total time in AF / Total monitoring time) × 100 %
```

### 4.2 Ví dụ

```
Monitoring: 24 giờ = 86,400 giây

AF episodes trong ngày:
- Episode 1: 2:00 - 2:15 (900s)
- Episode 2: 5:30 - 5:45 (900s)
- Episode 3: 14:20 - 14:25 (300s)
- Episode 4: 22:10 - 22:45 (2100s)

Total AF time = 900 + 900 + 300 + 2100 = 4200 giây
AF burden = (4200 / 86400) × 100 = 4.86%
```

### 4.3 Clinical significance

| AF Burden | Ý nghĩa |
|---|---|
| **0% (No AF)** | Bình thường |
| **< 0.5%** | Minimal; không cần treatment |
| **0.5% - 5%** | Low burden; monitor; xem xét medication |
| **5% - 20%** | Moderate burden; nên anticoagulation + rate control |
| **> 20%** | High burden; aggressive treatment; xem xét ablation |

**Ví dụ:** Người cao tuổi có AF burden 2.3% / ngày:
- ✅ Không ở mức "paroxysmal AF" (very frequent)
- ⚠️ Nhưng vẫn cần monitor & consider anticoagulation
- 💊 Aspirin hoặc Warfarin để prevent stroke

### 4.4 AFDB long-term evaluation result

Từ `evaluate_long_term_afdb.py` với 28,104 windows (khoảng 14.5 giờ liên tục):

```json
{
  "predicted_af_burden_percent": 32.96,  // Model predict
  "episode_af_burden_percent": 30.66,    // Ground truth
  "af_burden_absolute_error_percent": 6.90  // Sai 6.9%
}
```

**Kết luận:** Model predict AF burden rất chính xác (error < 7%)!

---

## 5. Output AF Episode trong dự án

### 5.1 Từ `/ingest-ecg` API

```json
{
  "af_episode": {
    "active": false,
    "current_episode_duration_sec": 0,
    "af_episode_count": 0,
    "total_af_duration_sec": 0,
    "af_burden_percent": 0.0
  }
}
```

**Diễn giải:**
- `active=False`: Không có cơn AF hiện tại
- `af_episode_count=0`: Chưa từng phát hiện AF episode
- `af_burden_percent=0.0`: 0% thời gian là AF (bình thường)

### 5.2 Khi phát hiện AF episode

```json
{
  "af_episode": {
    "active": true,
    "current_episode_duration_sec": 120,      // 2 phút
    "af_episode_count": 1,                    // Cơn thứ 1
    "total_af_duration_sec": 120,
    "af_burden_percent": 0.08                 // 0.08% (2 min / 24 hours)
  }
}
```

**Diễn giải:**
- `active=True`: Đang trong cơn AF
- `current_episode_duration_sec=120`: Cơn này kéo dài 2 phút
- `af_episode_count=1`: Đây là cơn AF thứ 1 từ khi bắt đầu monitor
- `af_burden_percent=0.08`: Nếu episode kết thúc bây giờ, sẽ là 0.08% / 24 hours

### 5.3 Sau khi episode kết thúc

```json
{
  "af_episode": {
    "active": false,
    "current_episode_duration_sec": 0,       // Không còn cơn hiện tại
    "af_episode_count": 1,                   // Đã ghi nhận 1 cơn
    "total_af_duration_sec": 300,            // Tổng 5 phút AF
    "af_burden_percent": 0.21                // 5 min / 24 hours
  }
}
```

---

## 6. Tại sao AF Episode quan trọng hơn window-level AF?

### 6.1 So sánh

| Aspect | Window-level | Episode-level |
|---|---|---|
| **Granularity** | 30 giây (quá nhỏ, noisy) | Phút đến giờ (clinically meaningful) |
| **False positive** | Cao (1 window lẻ có thể là noise) | Thấp (temporal aggregation) |
| **Temporal coherence** | Không xét | Xét (AF thường liên tiếp) |
| **AF burden** | Không tính | Có (% thời gian AF) |
| **Episode count** | N/A | Có (bao nhiêu cơn / ngày) |
| **Clinical decision** | Khó (quá detail) | Dễ (pattern rõ ràng) |

### 6.2 Ví dụ

```
Scenario: Polar H10 motion artifact 1 cửa sổ

Window-level alert:
├─ Window 42: P(AFib)=0.08 (≥0.05) → "AFib detected!"
├─ → ALERT: "AFib ALERT"
└─ → Person/caregiver panic

Episode-level (min_consecutive_windows=2):
├─ Window 42: AF candidate, count=1 (chờ)
├─ Window 43: No AF, count=0 (bỏ)
├─ → No alert (không đủ liên tiếp)
└─ → Person remains calm ✓
```

**Kết luận:** Episode-level **reduce false alarm** significantly!

---

## 7. Integration trong pipeline.py

### 7.1 Code flow

```python
# src/api/pipeline.py

def predict_ecg(patient_id, ecg_samples, sample_rate_hz, ...):
    # ... signal quality, emotion, anomaly, ...
    
    # 1. Predict rhythm
    rhythm = rhythm_predictor.predict(ecg_samples, sample_rate_hz)
    afib_prob = rhythm.get("probabilities", {}).get("possible_afib", 0.0)
    
    # 2. Update AF episode tracker
    tracker = _get_af_tracker(patient_id)  # Per-patient tracker
    af_episode = tracker.update(
        rhythm_label=rhythm.get("label"),
        afib_probability=afib_prob
    )
    # ↑ Returns: {"active": ..., "af_episode_count": ..., "af_burden_percent": ...}
    
    # 3. Generate alert
    alert = alert_engine.map_rhythm_to_alert(
        rhythm=rhythm,
        confidence=rhythm.get("confidence"),
        af_episode=af_episode,  # Pass AF state
        signal_quality=signal_quality,
        ...
    )
    # ↑ Alert level: "normal" / "medium" / "high" / "critical"
    
    return {
        "rhythm": rhythm,
        "af_episode": af_episode,
        "rhythm_alert": alert,
        ...
    }
```

### 7.2 Tracker persistence

```python
# Per-patient tracker (in-memory dictionary)
_af_trackers = {
    "chinh": AFEpisodeTracker("chinh", ...),
    "amine": AFEpisodeTracker("amine", ...),
    "huy": AFEpisodeTracker("huy", ...),
    ...
}

def _get_af_tracker(patient_id):
    if patient_id not in _af_trackers:
        _af_trackers[patient_id] = AFEpisodeTracker(patient_id, ...)
    return _af_trackers[patient_id]
```

**Lưu ý:** Nếu server restart, tracker reset. Để persist, cần lưu vào database.

---

## 8. Decision Thresholds từ AFDB

### 8.1 rhythm_decision_config.json

```json
{
  "episode_threshold": 0.05,              // P(AFib) ≥ 0.05 → AF window
  "alert_threshold": 0.3,                 // P(AFib) ≥ 0.3 → trigger alert immediately
  "min_consecutive_windows": 2,           // Yêu cầu ≥2 windows liên tiếp → episode
  "selected_metrics": {
    "precision": 0.8894645941278065,      // Episode precision = 89%
    "recall": 0.7355829316193537,         // Episode recall = 74%
    "f1": 0.805237955633734,              // Episode F1 = 80.5%
    "false_episode_per_hour": 0.7941929974380871  // ~0.8 false alarm/hour
  }
}
```

### 8.2 Hai threshold khác nhau (tại sao?)

| Threshold | Giá trị | Dùng để |
|---|---|---|
| `episode_threshold` | 0.05 (5%) | Định nghĩa "AF window" để accumulate episodes |
| `alert_threshold` | 0.3 (30%) | Trigger **immediate alert** nếu 1 window có AF prob cao |

**Logic:**
- P(AFib) = 0.08 (8%):
  - → Ghi nhận vào episode accumulation (episode_threshold=0.05)
  - → Chưa trigger alert (< alert_threshold=0.3)
  
- P(AFib) = 0.35 (35%):
  - → Ghi nhận vào episode accumulation
  - → **Trigger alert ngay** (≥ alert_threshold=0.3) vì cao

**Clinical:** alert_threshold cao → cần chắc chắn trước khi cảnh báo → reduce false alarm

---

## 9. Real-world scenario

### 9.1 Người cao tuổi Chinh (70 tuổi, tiền sử AF)

```
Sáng 8:00 AM:
- Chinh bị tức ngực nhẹ, hơi cảm thấy tim đập nhanh
- Надеть Polar H10 và kết nối app

14 cửa sổ (7 phút) monitoring:
┌─────────────────────────────┐
│ Window | P(AFib) | Status   │
├─────────────────────────────┤
│  1     │ 0.02   │ Normal   │
│  2     │ 0.02   │ Normal   │
│  3     │ 0.08   │ ← AF?    │ counter=1
│  4     │ 0.12   │ ← AF!    │ counter=2 → EPISODE FORMED!
│  5     │ 0.15   │ AF       │
│  6     │ 0.11   │ AF       │
│  7     │ 0.04   │ Normal   │ counter=0 → EPISODE ENDED
│  8     │ 0.02   │ Normal   │
│  9     │ 0.04   │ Normal   │
│ 10     │ 0.06   │ ← AF?    │ counter=1
│ 11     │ 0.01   │ Normal   │ counter=0
│ 12     │ 0.02   │ Normal   │
│ 13     │ 0.03   │ Normal   │
│ 14     │ 0.05   │ ← AF?    │ counter=1
└─────────────────────────────┘

AF Episode Summary:
├─ EPISODE #1: Window 4-6 (90 seconds)
│  └─ Duration: 1.5 minutes
├─ AF episode count: 1
├─ Total AF time: 90 seconds
└─ AF burden: (90 / 420) × 100 = 21.4%
```

**Dashboard shows:**
```
AF STATUS: ⚠️ ACTIVE
├─ Current episode: 1 min 30 sec
├─ Episode count today: 1
├─ AF burden: 21.4%
└─ Recommendation: → Call doctor
```

**Doctor receives:**
- Notification: "Patient Chinh has AF episode detected"
- Data: AF duration 1.5 min, burden 21.4%
- Action: Consider anticoagulation, rate control, ECG confirmation

---

## 10. Limitations & Future Work

### 10.1 Hiện tại

✅ **Có:**
- Window-level AF detection (HistGradient)
- Episode accumulation (min 2 windows)
- AF burden calculation
- Decision thresholds từ AFDB

❌ **Chưa có:**
- Per-patient AF episode threshold learning chuyên biệt. Hệ thống hiện đã có progressive personal baseline 7 ngày ở tầng report để so sánh AF suspicion ratio, nhưng chưa dùng baseline đó để tự chỉnh threshold AF episode.
- Paroxysmal vs persistent AF classification
- AF-triggered stroke risk score
- Database persistence (reset trên server restart)

### 10.2 Cải thiện tương lai

1. **Database storage:**
   - Lưu AF episode timeline vào SQLite
   - Track AF burden trend (1 day, 7 days, 30 days)

2. **Personalization:**
   - Dùng progressive personal baseline 7 ngày làm đầu vào tham khảo cho AF burden theo từng người
   - Adjust thresholds per-patient

3. **Clinical integration:**
   - CHA₂DS₂-VASc score (stroke risk)
   - HAS-BLED score (bleeding risk)
   - Anticoagulation recommendation

4. **Hybrid detection:**
   - ECG + RR interval irregularity + ACC context
   - Reduce motion artifact false positive

---

## Tóm tắt nhanh

| Khái niệm | Ý nghĩa |
|---|---|
| **AF** | Nhĩ rung, nhịp không đều, rủi ro stroke cao |
| **AF Window** | 1 cửa sổ 30 giây có P(AFib) ≥ 0.05 |
| **AF Episode** | Chuỗi ≥2 windows AF liên tiếp (kéo dài ≥1 phút) |
| **Episode Duration** | Khoảng thời gian từ start → end của 1 cơn |
| **AF Burden** | (Total AF time / Total time) × 100% |
| **episode_threshold** | 0.05 (định nghĩa AF window) |
| **alert_threshold** | 0.3 (trigger immediate alert) |
| **min_consecutive_windows** | 2 (yêu cầu tối thiểu để form episode) |

---

## Tham khảo

- `src/inference/af_episode_tracker.py` - Implementation
- `src/training/evaluate_long_term_afdb.py` - AFDB evaluation & threshold selection
- `src/api/pipeline.py` - Integration với API
- `models/rhythm/rhythm_decision_config.json` - Decision thresholds
- CDC Atrial Fibrillation: https://www.cdc.gov/heart-disease/about/atrial-fibrillation.html
