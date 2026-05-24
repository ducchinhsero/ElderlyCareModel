# PVC và PAC - Ectopy trong Elderly Care ECG

**Ngày tạo:** 2026-05-22  
**Bối cảnh:** PVC/PAC là loại ectopy được phát hiện trong hệ thống (models/ectopy/)

---

## 1. PVC là gì?

### 1.1 Định nghĩa

**PVC = Premature Ventricular Contraction (Co thắt thất sớm)**

- **Bình thường:** Tín hiệu điện từ sinus node → nhĩ → thất → co nhịp đều
- **PVC:** Thất phát sinh tín hiệu **sớm hơn** → co thất trước khi nhận tín hiệu bình thường
- **Kết quả:** 1 nhịp "thừa" không theo thứ tự, có cảm giác "tim nhảy"

### 1.2 ECG Pattern của PVC

```
Bình thường (Normal sinus):
PR──QRS──ST
│   │    │
P   │    T
    └─ Hẹp, nhọn

PVC (Premature Ventricular):
         ╱╲╱╲
    ╱───╱  ╲ ╲ (Wide QRS, >120ms)
   ╱      ST segment elevated/depressed
  ╱
 └─ Không có P wave (từ ventricle, không từ sinus)
 └─ QRS rộng (wide, > 0.12 giây)
 └─ T wave ngược chiều với QRS (discordant)

Timeline:
Normal:    │← Normal RR interval →│
           
PVC:       │← Shortened ←│ PVC │← Long pause →│ (compensatory pause)
           
Cảm giác:  Đều → "bỏ nhịp" → lại đều
```

### 1.3 Các loại PVC

| Loại | Mô tả | Ví dụ |
|---|---|---|
| **Isolated** | Hiếm gặp, ≤1% nhịp | Bình thường, không cần lo |
| **Couplets** | 2 PVC liên tiếp | Nên monitor |
| **Triplets/Salvos** | 3+ PVC liên tiếp | Tiền nháy tim (VT) |
| **Bigeminy** | Normal + PVC + Normal + PVC | Bệnh lý, cần treatment |
| **Trigeminy** | Normal + Normal + PVC lặp | Bệnh lý, cần treatment |

---

## 2. PAC là gì?

### 2.1 Định nghĩa

**PAC = Premature Atrial Contraction (Co thắt nhĩ sớm)**

- **Bình thường:** Sinus node phát sinh tín hiệu → nhĩ co → thất co
- **PAC:** **Nhĩ** (không từ sinus node) phát sinh tín hiệu sớm → co nhĩ sớm
- **Kết quả:** 1 nhịp "thừa" từ nhĩ, cảm giác "tim nhảy" nhẹ

### 2.2 ECG Pattern của PAC

```
Bình thường (Normal sinus):
┌─┐
│P├─ P wave rõ ràng
└─┘
  └─ P-R interval ~0.12-0.2s

PAC (Premature Atrial):
  ┌──┐
  │P'├─ P wave sớm, hình dáng khác (abnormal morphology)
  └──┘
     └─ Ngắn hơn normal PR interval
     └─ QRS bình thường (từ ventricle normal pathway)

Timeline:
Normal:    │← Normal RR interval →│
           
PAC:       │← Shortened ←│ PAC │← Reset →│ (often)
           
Cảm giác:  Đều → "bỏ nhịp nhẹ" → lại đều
```

### 2.3 So sánh PAC vs PVC

| Khía cạnh | PAC | PVC |
|---|---|---|
| **Nguồn** | Nhĩ (ectopic atrial focus) | Thất (ectopic ventricular focus) |
| **QRS** | Bình thường (narrow) | Rộng (wide) |
| **P wave** | Có, nhưng sớm + hình dáng khác | Không hoặc ẩn trong T wave |
| **Độ nguy hiểm** | Thường an toàn | Có thể nghiêm trọng nếu nhiều |
| **Cảm giác** | "Nhảy nhẹ" | "Bỏ nhịp" rõ ràng |
| **Nguyên nhân** | Caffeine, stress, hyperthyroidism | Cardiopathy, MI, electrolyte |

---

## 3. Tại sao PVC/PAC quan trọng?

### 3.1 Tần suất bình thường

| Người | PVC/min | PAC/min |
|---|---|---|
| **Sóe khỏe** | <1 (< 1440/ngày) | <1 |
| **Người cao tuổi** | 1-10 | 1-5 |
| **Bệnh nhân** | >10 | >5 |

### 3.2 Ý nghĩa lâm sàng

#### **PAC (Premature Atrial Contraction)**

| Mức độ | Ý nghĩa | Hành động |
|---|---|---|
| **Isolated/Rare** | Bình thường, không cần lo | Monitor |
| **Frequent (>1-2 / min)** | Có thể tiền đầu PAF | Xem xét medication |
| **Couplets** | Tăng rủi ro AFib | Xem xét ablation |
| **Runs** | Possible AFib/SVT | ECG, Holter monitor |

**→ PAC thường tiền đầu AFib!**

#### **PVC (Premature Ventricular Contraction)**

| Mức độ | Ý nghĩa | Hành động |
|---|---|---|
| **Isolated (< 0.1%)** | Bình thường, đặc biệt nếu vận động | Monitor |
| **Frequent (1-10%)** | Có thể cardiopathy | Echocardiogram |
| **Couplets** | Tăng rủi ko VT/VF | Xem xét antiarrhythmic |
| **Salvo/VT** | **Nguy hiểm!** Có thể sudden death | Emergency treatment |

**→ PVC nhiều liên quan đến bệnh tim cơ bản!**

### 3.3 Liên hệ với AFib

```
PVC/PAC frequent → Tissue remodeling → Substrate for AFib
                 → Autonomic imbalance
                 → Structural changes
                 → ↑ AFib risk

Elderly patient:
- PAC frequent → tiền AFib → early detection → prevent AFib
- Frequent PVC → underlying cardiopathy → worse AFib prognosis
```

---

## 4. Ectopy trong dự án

### 4.1 Phát hiện trong codebase

```
models/ectopy/               ← NEW module
├─ ectopy_model.pkl          (trained classifier)
├─ ectopy_scaler.pkl         (StandardScaler)
├─ ectopy_feature_schema.json (beat-level features)
└─ ectopy_metrics.json       (accuracy)

src/dataset_builders/
├─ build_mitdb_ectopy.py     (prepare MITDB data)

data_processed/
└─ mitdb_ectopy/             (processed dataset)
    ├─ X.npy                 (beat-level features)
    ├─ y.npy                 (0=normal, 1=PVC, 2=PAC, ...)
    └─ metadata.csv
```

### 4.2 Ectopy detection approach

**Window-level (30s) vs Beat-level:**

```
Current rhythm model:
├─ Input: 3,900 ECG samples (30 seconds)
├─ Output: rhythm class (normal/AFib/other/noise)
└─ Granularity: 30 seconds

New ectopy module (proposed):
├─ Input: Individual heartbeats (~200-400ms)
├─ Output: beat class (N=normal, V=PVC, A=PAC, ...)
└─ Granularity: Per beat (~0.5 seconds)

Combined:
└─ Rhythm: "normal" (30s window)
   └─ Ectopy: "5 PVCs out of 60 beats in this window" (8%)
```

### 4.3 Beat-level features cho ectopy

```python
# Từ MITDB beat annotation

Features trên mỗi beat:
├─ QRS width (ms)
├─ QRS amplitude (mV)
├─ R-R interval (ms)
├─ QRS shape (morphology)
├─ ST elevation/depression
├─ T-wave inversion
├─ R-peak to T-peak (ms)
├─ Energy of QRS
├─ RR interval variability (local)
└─ ... (~20-30 beat-level features)

Labels (MITDB standard):
├─ 0 (N) = Normal beat
├─ 1 (V) = PVC (Premature Ventricular)
├─ 2 (A) = PAC (Premature Atrial)
├─ 3 (S) = Supraventricular (other SVT beat)
├─ 4 (F) = Fusion
├─ 5 (~) = Unclassifiable
└─ ... (AAMI standard: 15 types)
```

---

## 5. Ectopy detection pipeline

### 5.1 Quy trình giả định (từ code references)

```
ECG 30 seconds (3,900 samples @ 130 Hz)
    ↓
[R-peak detection]
    ↓
Identify individual beats (typically 60-100 beats in 30s)
    ↓
For each beat:
  ├─ Extract ~20-30 beat-level features
  ├─ Normalize with ectopy_scaler.pkl
  └─ Predict: N/V/A/S/F/~ using ectopy_model.pkl
    ↓
Aggregate beat predictions:
├─ PVC count = N_V
├─ PAC count = N_A
├─ PVC rate = N_V / total_beats * 100
├─ PAC rate = N_A / total_beats * 100
└─ Ectopy burden = (N_V + N_A) / total_beats * 100
    ↓
Output:
{
  "total_beats": 75,
  "pvc_count": 3,
  "pac_count": 1,
  "pvc_rate_percent": 4.0,
  "pac_rate_percent": 1.3,
  "ectopy_burden_percent": 5.3,
  "dominant_ectopy": "PVC"
}
```

### 5.2 Integration vào pipeline (proposed)

```python
# src/api/pipeline.py

def predict_ecg(patient_id, ecg_samples, sample_rate_hz, ...):
    # Existing:
    rhythm = rhythm_predictor.predict(ecg_samples, sample_rate_hz)
    af_episode = af_tracker.update(...)
    
    # NEW - Ectopy detection
    if ectopy_model_available:
        # 1. Detect R-peaks
        r_peaks = find_r_peaks(ecg_samples, sample_rate_hz)
        
        # 2. Extract individual beats
        beats = [ecg_samples[peak-offset:peak+offset] for peak in r_peaks]
        
        # 3. Extract beat-level features
        beat_features = []
        for beat in beats:
            feat = extract_beat_features(beat)
            beat_features.append(feat)
        
        # 4. Predict beat types
        beat_predictions = ectopy_model.predict(beat_features)
        # [N, N, V, N, A, N, ...]
        
        # 5. Aggregate
        pvc_count = (beat_predictions == V).sum()
        pac_count = (beat_predictions == A).sum()
        ectopy_output = {
            "total_beats": len(beats),
            "pvc_count": pvc_count,
            "pac_count": pac_count,
            "pvc_rate": pvc_count / len(beats) * 100,
            "pac_rate": pac_count / len(beats) * 100
        }
    else:
        ectopy_output = None
    
    return {
        "rhythm": rhythm,
        "af_episode": af_episode,
        "ectopy": ectopy_output,  # NEW
        ...
    }
```

### 5.3 Expected output từ API

```json
{
  "timestamp": "2026-05-22T10:30:00+07:00",
  "patient_id": "chinh",
  "rhythm": {
    "label": "normal",
    "confidence": 0.85,
    "probabilities": {...}
  },
  "af_episode": {
    "active": false,
    "af_episode_count": 0,
    "af_burden_percent": 0.0
  },
  "ectopy": {
    "total_beats": 78,
    "pvc_count": 3,
    "pac_count": 1,
    "pvc_rate_percent": 3.85,
    "pac_rate_percent": 1.28,
    "ectopy_burden_percent": 5.13,
    "dominant_ectopy_type": "PVC",
    "clinical_significance": "low"
  },
  "heart_rate_bpm": 78,
  "signal_quality": {
    "label": "good",
    "score": 0.92
  },
  "alert_level": "normal"
}
```

---

## 6. Clinical Interpretation

### 6.1 Ectopy burden classification

```
Ectopy Burden =  (N_PVC + N_PAC + N_other) / total_beats * 100 %

Classification:
├─ < 0.5%:      Trivial (bình thường)
├─ 0.5-1%:      Occasional (monitor)
├─ 1-5%:        Frequent (xem xét treatment)
├─ 5-10%:       Very frequent (likely pathology)
└─ > 10%:       Highly frequent (definite pathology)
```

### 6.2 PVC significance score (proposed)

```
Risk = Ectopy_burden × Ectopy_pattern × Hemodynamic_impact

Pattern scoring:
├─ Isolated        = 1.0 (low risk)
├─ Couples         = 2.0 (moderate)
├─ Salvos (3+)     = 4.0 (high)
├─ Bigeminy        = 3.0 (very high)
└─ VT runs         = 10.0 (critical)

Example:
├─ 5% ectopy × 1.0 (isolated) = 5 (low risk)
└─ 5% ectopy × 4.0 (salvos) = 20 (high risk)
```

### 6.3 PAC significance score (proposed)

```
AFib_risk = PAC_burden × PAC_frequency_pattern

PAC patterns:
├─ Isolated        = minimal AFib risk
├─ Frequent        = increasing AFib risk
├─ Runs            = significant AFib risk
└─ Near-miss_PSVT  = high AFib risk

Clinical action:
├─ PAC < 0.5%:    No treatment
├─ PAC 0.5-2%:    Monitor, limit caffeine/stress
├─ PAC 2-5%:      Beta-blocker, electrolyte check
└─ PAC > 5%:      Consider ablation or antiarrhythmic
```

---

## 7. Real-world scenario

### 7.1 Chinh (70 tuổi, multiple comorbidities)

```
Mặc Polar H10, monitoring suốt đêm (22:00 - 06:00):

23:00 - 00:00 (Normal sleep):
├─ Rhythm: normal
├─ HR: 58 bpm
├─ Ectopy: 2 PVCs / 480 beats = 0.42% (trivial)
├─ AF episodes: 0
└─ Alert: normal ✓

02:00 - 02:30 (Sleep disturbance):
├─ Rhythm: normal
├─ HR: 72 bpm (↑ from arousal)
├─ Ectopy: 15 PVCs + 3 PACs / 90 beats = 20% (VERY FREQUENT!)
│  └─ Pattern: "Bigeminy" (alternating normal + PVC)
│  └─ Clinical significance: HIGH
├─ AF episodes: 0 (but PACs increase AFib risk)
└─ Alert: MEDIUM ⚠️
   └─ "Frequent ectopy detected, suggest EKG confirmation"

04:00 - 06:00 (Normal sleep recovery):
├─ Rhythm: normal
├─ HR: 62 bpm
├─ Ectopy: 8 PVCs / 600 beats = 1.3% (occasional)
├─ AF episodes: 0
└─ Alert: normal ✓

Summary:
├─ Total sleep: 8 hours
├─ High ectopy period: 1 episode (30 min)
├─ PVC burden (overall): 0.8% (low)
├─ PAC burden (overall): 0.05% (trivial)
├─ Clinical notes:
│  └─ PVC increase during arousals → likely reactive
│  └─ No sustained runs → low sudden death risk
│  └─ Low PAC burden → low AFib risk at this time
└─ Recommendation: 
   └─ Follow-up EKG if symptoms persist
   └─ Electrolyte panel (K+, Mg2+)
   └─ Consider beta-blocker if frequency increases
```

### 7.2 Dashboard visualization (proposed)

```
ECTOPY STATUS
├─ Ectopy Burden: 0.8% ✓ (Low)
├─ PVC/hour: 2.5 (Occasional)
├─ PAC/hour: 0.2 (Trivial)
├─ Pattern: Isolated
├─ Peak rate: 20% (during 02:30 arousal)
└─ Trend: ↓ Improving

CLINICAL INTERPRETATION
├─ Risk Level: LOW
├─ Likely Cause: Reactive (sleep disturbance)
├─ Recommendation: Monitor, recheck EKG if symptoms
└─ Action: None urgent
```

---

## 8. MITDB Dataset (ectopy training data)

### 8.1 MIT-BIH Arrhythmia Database

```
Database: MIT-BIH Arrhythmia (48 records)
├─ 47 records từ bệnh nhân (age 23-89)
├─ 1 record từ người khỏe (reference)
├─ Duration: 30 phút mỗi record
├─ Sampling: 360 Hz
├─ Annotation: Beat-by-beat labels (15 types)
└─ Total beats: ~110,000

Beat types in MITDB:
├─ 0 (N)  = Normal beat
├─ 1 (L)  = Left bundle branch block
├─ 2 (R)  = Right bundle branch block
├─ 3 (V)  = PVC
├─ 4 (A)  = PAC
├─ 5 (J)  = Junctional
├─ 6 (S)  = Supraventricular
├─ 7 (F)  = Fusion
├─ 8 (/)  = Paced beat
├─ 9 (f)  = Fusion paced
├─ 10 (~) = Unclassifiable
├─ 11 (|) = Isolated QRS complex
├─ 12 (s) = ST change
├─ 13 (t) = T-wave change
└─ 14 (u) = Ventricular flutter wave
```

### 8.2 Distribution (example)

```
Record 100 (237 min ectopy):
├─ N (Normal): 2,093 beats (88.2%)
├─ L (LBBB):   96 beats (4.0%)
├─ R (RBBB):   42 beats (1.8%)
├─ V (PVC):    105 beats (4.4%)
├─ A (PAC):    39 beats (1.6%)
└─ Others:     22 beats (0.9%)

→ Ectopy = 4.4% + 1.6% = 6.0% burden
→ PVC heavy, moderate PAC
```

---

## 9. Training ectopy model (expected approach)

### 9.1 Data preparation

```
build_mitdb_ectopy.py:
├─ Load MITDB annotations
├─ Extract beat windows (typically 200-400ms)
├─ For each beat:
│  ├─ Resample to 130 Hz (align with pipeline)
│  ├─ Normalize
│  └─ Extract beat-level features
├─ Group by record (no contamination)
├─ Split: 80% train, 20% test
└─ Output:
   ├─ X.npy (N_beats × 30 features)
   ├─ y.npy (N_beats labels)
   └─ metadata.csv (record_id, beat_index, label)
```

### 9.2 Model training (MITDB-based)

```
train_ectopy_features.py (proposed):
├─ Load processed MITDB
├─ Simplify to binary/multiclass:
│  └─ Option A: Binary (N vs Ectopy)
│  └─ Option B: Multiclass (N / V / A / Other)
├─ Train candidates:
│  ├─ RandomForestClassifier
│  ├─ ExtraTreesClassifier
│  └─ HistGradientBoostingClassifier
├─ Select best by macro-F1
└─ Output:
   ├─ ectopy_model.pkl
   ├─ ectopy_scaler.pkl
   └─ ectopy_metrics.json
```

### 9.3 Expected metrics

```
Binary classification (Normal vs Ectopy):
├─ Accuracy: ~95-98%
├─ Ectopy F1: ~85-90%
└─ Reason: Beat-level easier than window-level

Multiclass (N / V / A / Other):
├─ Accuracy: ~90-95%
├─ V (PVC) F1: ~80-85%
├─ A (PAC) F1: ~75-80%
└─ Reason: More detailed, harder to distinguish
```

---

## 10. Future integration plan

### 10.1 Phase 1 (Current): Detection only
- ✅ Detect individual beats (N/V/A/S/F/~)
- ✅ Count PVC/PAC per window
- ✅ Calculate ectopy burden
- ✅ Display in dashboard

### 10.2 Phase 2 (Future): Pattern recognition
- ❌ Identify patterns (Bigeminy, Trigeminy, Salvos)
- ❌ Calculate VT risk score
- ❌ Predict AFib risk from PAC pattern

### 10.3 Phase 3 (Partial current): Per-patient baseline
- ✅ Learn personal baseline from SQLite predictions with progressive 7-day calibration.
- ✅ Track baseline ectopy/PVC-PAC ratio per patient.
- ✅ Compare recent PVC/PAC ratio against personal baseline in `/health-report`.
- ❌ Advanced ectopy pattern baseline by activity/exercise context is still future work.

### 10.4 Phase 4 (Future): Fusion models
- ❌ Combine ectopy + rhythm + HR context
- ❌ "PVC during AF" vs "PVC during normal rhythm"
- ❌ Composite risk score

---

## Tóm tắt nhanh

| Ký hiệu | Tên đầy đủ | Nguồn | QRS | Nguy hiểm | Ý nghĩa |
|---|---|---|---|---|---|
| **PVC** | Premature Ventricular | Thất | Rộng | Cao nếu nhiều | Bệnh tim cơ bản |
| **PAC** | Premature Atrial | Nhĩ | Hẹp | Tiền AFib | Tiền đầu AFib |

**Trong dự án:**
- ✅ Models/ectopy/ - Module phát hiện PVC/PAC (beat-level)
- ✅ Chuẩn bị từ MITDB (110,000 heartbeats)
- ⏳ Chưa tích hợp vào main pipeline
- 📊 Expected: PVC/PAC burden % + pattern analysis

---

## Tham khảo

- `src/dataset_builders/build_mitdb_ectopy.py` - Data preparation
- `models/ectopy/` - Model artifacts
- `data_processed/mitdb_ectopy/` - Processed dataset
- MIT-BIH Arrhythmia Database: https://physionet.org/content/mitdb/1.0.0/
- Goldberger et al. PhysioBank, PhysioToolkit: https://physionet.org/
