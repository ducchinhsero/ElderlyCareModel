1. Mục tiêu rebuild model

Hiện tại script_anomaly.py đang train IsolationForest từ MIT-BIH/PTBDB để phát hiện bất thường ECG chung chung. Output chính là normal / abnormal, chưa phân loại rõ AFib, tachycardia, bradycardia, noise hoặc irregular rhythm.

Trong khi pipeline.py đã có phần realtime khá tốt: thu ECG/ACC từ Polar H10, kiểm tra chất lượng tín hiệu, trích feature, load model, dự đoán, lưu kết quả, hiển thị dashboard và cảnh báo.

Vì vậy không nên bỏ toàn bộ hệ thống. Nên giữ pipeline.py làm khung vận hành, nhưng thay lõi model anomaly.

Mục tiêu mới:

Polar H10 ECG/RR/ACC
→ signal quality
→ rhythm classification
→ AF episode detection
→ AF burden
→ alert theo ngữ cảnh
2. Kiến trúc model mới nên dùng

Nên chia thành 4 model/module, không dùng một model duy nhất cho tất cả.

Module A — Signal Quality / Noise Model

Dùng để trả lời:

Tín hiệu ECG có đủ sạch để dự đoán không?

Output:

good
fair
noise
poor_contact
motion_artifact

Dataset dùng:

MIT-BIH Noise Stress Test Database
PhysioNet/CinC 2017 class Noise
Dữ liệu Polar H10 tự thu có nhiễu

Vai trò:

Chặn false alarm.
Không cho model báo AFib/abnormal khi tín hiệu thật ra là nhiễu.
Module B — Rhythm Classifier chính

Dùng để phân loại nhịp theo cửa sổ 30 giây.

Output khuyến nghị:

normal
possible_afib
other_rhythm
noise

Dataset chính:

PhysioNet/CinC Challenge 2017

Đây là model quan trọng nhất.

Sau đó map lại cho dashboard:

Normal              → normal
Atrial Fibrillation → possible_afib
Other rhythm        → irregular_rhythm / unclassified_abnormal
Noisy               → noise
Module C — Tachycardia / Bradycardia Rule Engine

Không nhất thiết cần model AI phức tạp. Dùng rule + context là đủ.

Input:

heart_rate_bpm
RR interval
activity_state
duration
signal_quality

Output:

tachycardia_at_rest
bradycardia
normal_hr

Ví dụ:

if hr_bpm > 100 and activity_state == "rest" and duration_sec >= 30:
    label = "tachycardia"

elif hr_bpm < 50 and activity_state not in ["sleep", "unknown"] and duration_sec >= 30:
    label = "bradycardia"

Lưu ý: với người già, nhịp nhanh/chậm nên xét theo ngữ cảnh. Nếu đang đi/chạy thì HR cao chưa chắc bất thường.

Module D — AF Episode / AF Burden

Dùng để trả lời:

AFib kéo dài bao lâu?
Trong phiên đo, tổng thời gian nghi AFib là bao nhiêu?

Dataset dùng:

MIT-BIH Atrial Fibrillation Database

Output:

{
  "af_episode_count": 4,
  "longest_af_episode_sec": 420,
  "total_af_duration_sec": 1200,
  "af_burden_percent": 3.4
}

Đây là module giúp dự án mạnh hơn rất nhiều so với chỉ phân loại từng cửa sổ.

3. Dataset nào dùng cho việc gì?
Dataset	Vai trò chính	Cách dùng
PhysioNet/CinC 2017	Rhythm classifier	Train normal / AFib / other / noise
MIT-BIH AFDB	AF episode, AF burden	Validate AFib theo chuỗi dài
MIT-BIH Noise Stress Test	Noise robustness	Train/test signal quality, augmentation
MIT-BIH Arrhythmia	Beat abnormality, PVC/PAC, irregular	Giai đoạn 2, chưa cần làm lõi đầu tiên
4. Roadmap rebuild theo giai đoạn
Giai đoạn 1 — Chuẩn hóa dữ liệu

Mục tiêu: đưa tất cả dataset về cùng chuẩn giống Polar H10.

Polar H10 realtime đang dùng:

REALTIME_SAMPLE_RATE_HZ = 130

trong pipeline.py.

Vì vậy toàn bộ dataset nên resample về:

130 Hz

Chuẩn chung:

sample_rate = 130 Hz
window_size = 30 giây
samples_per_window = 3900

Cấu trúc dữ liệu sau xử lý:

dataset_processed/
    cinc2017/
        X.npy
        y.npy
        metadata.csv

    afdb/
        X_windows.npy
        y_windows.npy
        episode_metadata.csv

    noise/
        X_noise.npy
        y_noise.npy

    mitdb/
        beat_windows.npy
        beat_labels.npy

Việc cần làm:

1. Đọc file ECG gốc
2. Resample về 130 Hz
3. Normalize biên độ
4. Cắt thành cửa sổ 30 giây
5. Gán nhãn
6. Lưu thành .npy/.csv

Nhãn chuẩn:

LABEL_MAP = {
    "normal": 0,
    "possible_afib": 1,
    "other_rhythm": 2,
    "noise": 3
}
Giai đoạn 2 — Train model baseline nhanh

Trước khi dùng deep learning, nên làm baseline bằng feature-based model.

Feature cần trích:

mean_hr
median_hr
min_hr
max_hr
mean_rr
std_rr
rmssd
sdnn
pnn50
rr_irregularity_index
sample_entropy
turning_point_ratio
qrs_width_mean
r_amplitude_mean
signal_quality_score

Model baseline:

Random Forest
XGBoost hoặc LightGBM
SVM
Logistic Regression

Output:

normal / possible_afib / other_rhythm / noise

Lý do nên làm baseline trước:

- dễ debug
- dễ giải thích trong báo cáo
- ít tốn tài nguyên
- biết dataset/preprocessing đã đúng chưa

File nên tạo:

train_rhythm_features.py

Output sau train:

rhythm_feature_model.pkl
rhythm_scaler.pkl
rhythm_feature_schema.json
rhythm_metrics.json
confusion_matrix.png
Giai đoạn 3 — Train model deep learning trên ECG raw

Sau khi baseline ổn, train 1D-CNN.

Input:

30 giây ECG
130 Hz
3900 samples

Output:

4 class:
normal
possible_afib
other_rhythm
noise

Model đề xuất:

1D-CNN nhẹ
CNN + BiLSTM nếu muốn nâng cao
TCN nếu muốn tốt hơn cho chuỗi thời gian

Kiến trúc 1D-CNN đơn giản:

Input: 3900 x 1
Conv1D + BatchNorm + ReLU + MaxPool
Conv1D + BatchNorm + ReLU + MaxPool
Conv1D + BatchNorm + ReLU + GlobalAveragePooling
Dense
Softmax 4 classes

File nên tạo:

train_rhythm_cnn.py

Output:

rhythm_cnn_model.pt hoặc rhythm_cnn_model.keras
preprocess_config.json
label_map.json
metrics.json

Nếu dùng PyTorch:

.pt

Nếu dùng TensorFlow/Keras:

.keras
Giai đoạn 4 — Thêm AF episode detection

Sau khi model phân loại từng cửa sổ 30s, cần post-processing theo thời gian.

Không nên báo AFib chỉ vì 1 cửa sổ duy nhất. Nên dùng logic:

possible_afib nếu:
- ≥2 cửa sổ liên tiếp là AFib
hoặc
- tổng xác suất AFib trung bình trong 60–90s vượt ngưỡng

Ví dụ:

if afib_prob_window_1 > 0.7 and afib_prob_window_2 > 0.7:
    start_af_episode()

Từ đó tính:

episode_start
episode_end
episode_duration
total_af_duration
af_burden_percent

File nên tạo:

af_episode_tracker.py

Output realtime:

{
  "current_af_episode": true,
  "current_episode_duration_sec": 120,
  "af_episode_count": 3,
  "af_burden_percent": 2.8
}
Giai đoạn 5 — Tích hợp vào pipeline.py

Hiện pipeline.py đang load:

ANOMALY_MODEL_PATH = "isolation_forest_model.pkl"
ANOMALY_SCALER_PATH = "anomaly_scaler.pkl"

và dùng _summarize_anomaly() để trả về normal / abnormal / unknown.

Sau rebuild, nên chuyển sang:

RHYTHM_MODEL_PATH = "rhythm_model.pkl" 
# hoặc rhythm_cnn_model.pt

RHYTHM_SCHEMA_PATH = "rhythm_feature_schema.json"
RHYTHM_LABEL_MAP_PATH = "rhythm_label_map.json"

Thêm hàm mới:

def _summarize_rhythm(ecg, sample_rate_hz, signal_quality):
    ...

Output mới:

{
  "label": "possible_afib",
  "class_id": 1,
  "confidence": 0.86,
  "probabilities": {
    "normal": 0.05,
    "possible_afib": 0.86,
    "other_rhythm": 0.07,
    "noise": 0.02
  }
}

Trong predict_ecg(), thay vì chỉ:

anomaly = _summarize_anomaly(...)

nên có:

rhythm = _summarize_rhythm(...)
hr_event = detect_hr_event(...)
af_episode = update_af_episode_tracker(...)

Output cuối nên thành:

{
  "heart_rate_bpm": 82,
  "signal_quality": {...},
  "rhythm": {
    "label": "possible_afib",
    "confidence": 0.86
  },
  "hr_event": {
    "tachycardia": false,
    "bradycardia": false
  },
  "af_episode": {
    "active": true,
    "duration_sec": 90,
    "af_burden_percent": 1.7
  },
  "alert_level": "high",
  "message": "Possible AFib episode detected."
}
5. Cấu trúc folder mới nên dùng

Nên tổ chức lại project như sau:

project/
│
├── data_raw/
│   ├── cinc2017/
│   ├── afdb/
│   ├── nstdb/
│   └── mitdb/
│
├── data_processed/
│   ├── rhythm_windows/
│   ├── afdb_windows/
│   ├── noise_windows/
│   └── mitdb_beats/
│
├── models/
│   ├── rhythm_model.pkl
│   ├── rhythm_cnn_model.pt
│   ├── rhythm_scaler.pkl
│   ├── rhythm_feature_schema.json
│   ├── label_map.json
│   └── metrics/
│
├── src/
│   ├── preprocessing.py
│   ├── dataset_builders/
│   │   ├── build_cinc2017.py
│   │   ├── build_afdb.py
│   │   ├── build_nstdb.py
│   │   └── build_mitdb.py
│   │
│   ├── features/
│   │   ├── rhythm_features.py
│   │   ├── hrv_features.py
│   │   └── signal_quality.py
│   │
│   ├── training/
│   │   ├── train_rhythm_features.py
│   │   ├── train_rhythm_cnn.py
│   │   └── evaluate_model.py
│   │
│   ├── inference/
│   │   ├── rhythm_inference.py
│   │   ├── af_episode_tracker.py
│   │   └── alert_engine.py
│   │
│   └── pipeline.py

Hiện bạn đang có pipeline.py và script_anomaly.py ở dạng khá tập trung nhiều chức năng. Sau rebuild, nên tách nhỏ để dễ bảo trì.

6. Class nào nên làm trước?

Không nên làm 7 class ngay từ đầu. Nên đi theo thứ tự:

Phase 1 — bắt buộc
normal
possible_afib
other_rhythm
noise

Dùng CinC 2017.

Đây là nhóm quan trọng nhất.

Phase 2 — thêm rule nhịp nhanh/chậm
tachycardia
bradycardia

Không cần dataset riêng lớn, vì có thể tính từ HR/RR.

Phase 3 — mở rộng irregular rhythm
irregular_rhythm

Có thể map từ:

other_rhythm
+ RR irregularity cao
+ không đủ tiêu chí AFib
Phase 4 — PVC/PAC
PVC/PAC

Dùng MIT-BIH Arrhythmia. Để sau vì phức tạp hơn và dễ báo sai nếu chưa có post-processing.

7. Chiến lược label thống nhất

Bạn nên dùng label chính cho model:

RHYTHM_LABELS = {
    0: "normal",
    1: "possible_afib",
    2: "other_rhythm",
    3: "noise"
}

Sau đó alert layer map thành trạng thái người dùng:

def map_rhythm_to_alert(rhythm_label, confidence, hr_event, signal_quality):
    if signal_quality == "noise":
        return "unknown", "Poor ECG signal quality. Please adjust the strap."

    if rhythm_label == "possible_afib" and confidence >= 0.8:
        return "high", "Possible AFib detected."

    if rhythm_label == "other_rhythm":
        return "medium", "Irregular rhythm detected. Continue monitoring."

    if hr_event == "tachycardia_at_rest":
        return "medium", "High heart rate at rest detected."

    if hr_event == "bradycardia":
        return "medium", "Low heart rate detected."

    return "normal", "No significant rhythm abnormality detected."
8. Các chỉ số đánh giá cần có

Không chỉ báo accuracy. Cần có:

Accuracy
Precision từng class
Recall từng class
F1 từng class
Macro F1
Confusion matrix
False alarm rate
Noise rejection accuracy
AFib sensitivity
AFib specificity

Với người già/cảnh báo sức khỏe, quan trọng nhất:

AFib recall cao
Noise false alarm thấp
False alarm/hour thấp

Ví dụ báo cáo nên có:

AFib Recall: 0.91
AFib Precision: 0.84
Noise Recall: 0.88
Macro F1: 0.86
False alarm/hour trên AFDB: 0.3
9. Cách tận dụng MIT-BIH Arrhythmia

MIT-BIH Arrhythmia không nên là dataset chính cho model đầu tiên. Dùng nó ở Phase 4.

Nhiệm vụ:

beat-level classification

Mapping đơn giản:

N → normal_beat
S → supraventricular ectopic
V → ventricular ectopic
F → fusion
Q → unknown

Sau đó tính trong 30 giây:

PVC_count
PAC_count
ectopic_ratio
abnormal_beat_ratio

Nếu nhiều PVC/PAC:

other_rhythm hoặc ectopic_activity

Không nên cảnh báo mạnh vì một PVC đơn lẻ.

10. Cách tận dụng MIT-BIH Noise Stress Test

Dùng cho 2 việc:

Cách 1 — train signal quality model

Class:

clean
baseline_wander
muscle_artifact
electrode_motion
Cách 2 — data augmentation

Thêm noise vào ECG sạch:

clean ECG + baseline wander
clean ECG + muscle artifact
clean ECG + electrode motion

Mục tiêu:

model không nhầm noise thành AFib

Đây là cực kỳ quan trọng với Polar H10.

11. Cách tận dụng MIT-BIH AFDB

Dùng để kiểm tra logic dài hạn.

Pipeline:

AFDB record dài
→ resample 130 Hz
→ cắt 30s window
→ label mỗi window là AFIB hoặc non-AFIB
→ chạy rhythm model
→ dùng episode tracker
→ so sánh với annotation thật

Metric quan trọng:

episode sensitivity
episode precision
AF burden error
false episode/hour

Ví dụ:

AF burden thật: 12.5%
AF burden model: 13.8%
Sai số: 1.3%
12. Kế hoạch thay thế script_anomaly.py

Hiện script_anomaly.py nên được giữ làm tham khảo, nhưng không nên là model chính nữa.

Thay bằng 4 file:

01_build_rhythm_dataset.py
02_train_rhythm_feature_model.py
03_train_rhythm_cnn.py
04_evaluate_long_term_afdb.py
File 1: 01_build_rhythm_dataset.py

Input:

PhysioNet/CinC 2017

Output:

data_processed/rhythm/X.npy
data_processed/rhythm/y.npy
data_processed/rhythm/metadata.csv
File 2: 02_train_rhythm_feature_model.py

Input:

X.npy, y.npy

Output:

models/rhythm_feature_model.pkl
models/rhythm_scaler.pkl
models/rhythm_feature_schema.json
models/metrics/rhythm_feature_metrics.json
File 3: 03_train_rhythm_cnn.py

Input:

ECG windows 3900 samples

Output:

models/rhythm_cnn_model.pt
models/metrics/rhythm_cnn_metrics.json
File 4: 04_evaluate_long_term_afdb.py

Input:

MIT-BIH AFDB
trained rhythm model

Output:

AF episode metrics
AF burden metrics
false alarm/hour
13. Tích hợp dashboard mới

Dashboard hiện tại có card:

Emotion
ECG anomaly
Risk trend
Activity
Fall status

Nên đổi/ thêm:

Rhythm status
AFib probability
Current AF episode
AF burden
Signal quality
Heart-rate event
Activity context
Alert

Card gợi ý:

Rhythm: possible AFib
Confidence: 86%
AF episode: active, 2m 10s
AF burden today: 1.8%
HR: 112 bpm
Signal: good
Activity: rest
Alert: high
14. Thứ tự triển khai cụ thể
Tuần/Giai đoạn 1: Dataset preprocessing

Việc cần làm:

- Viết loader cho CinC 2017
- Resample ECG 300 Hz → 130 Hz
- Cắt/pad thành 30 giây = 3900 samples
- Encode label N/AF/O/~ thành 0/1/2/3
- Lưu X.npy, y.npy

Kết quả cần có:

X shape: [num_records, 3900]
y shape: [num_records]
label distribution
sample plot từng class
Giai đoạn 2: Baseline feature model

Việc cần làm:

- Trích HRV/RR/morphology features
- Train Random Forest/XGBoost
- Evaluate confusion matrix
- Lưu model/scaler/schema

Mục tiêu:

Macro F1 baseline đủ tốt
Biết class nào model hay nhầm
Giai đoạn 3: CNN model

Việc cần làm:

- Train 1D-CNN
- Dùng class weight vì dataset mất cân bằng
- Early stopping
- Confusion matrix
- So sánh với feature model

Chọn model tốt hơn để deploy.

Giai đoạn 4: Noise robustness

Việc cần làm:

- Dùng NSTDB để tạo noisy ECG
- Test xem model có nhầm noise thành AFib không
- Nếu có, thêm noise augmentation vào training

Mục tiêu:

Giảm false AFib khi tín hiệu xấu
Giai đoạn 5: AFDB long-term evaluation

Việc cần làm:

- Cắt AFDB thành window 30s
- Dự đoán từng window
- Gộp thành episode
- Tính AF burden

Mục tiêu:

Không chỉ đúng từng cửa sổ, mà đúng theo episode dài hạn
Giai đoạn 6: Tích hợp Polar H10

Việc cần làm:

- Load model mới trong pipeline.py
- Thay anomaly output bằng rhythm output
- Giữ signal quality hiện có
- Giữ ACC context hiện có
- Thêm AF episode tracker
- Update dashboard

Kết quả:

Polar H10 realtime → normal / possible_afib / other_rhythm / noise
15. Mức hoàn thiện sau rebuild

Nếu làm theo kế hoạch trên, dự án sẽ nâng từ khoảng:

60–65%

lên khoảng:

80–85%

cho mục tiêu:

“Hệ thống phát hiện bất thường nhịp tim từ ECG Polar H10”

Nếu thêm được AF burden + noise robustness + dữ liệu Polar H10 tự thu:

85–90% cho đồ án/demo nghiên cứu

Nhưng vẫn không nên gọi là thiết bị chẩn đoán y tế.

16. Kết luận chiến lược

Hướng rebuild tốt nhất là:

Bỏ tư duy “anomaly normal/abnormal chung chung”.
Chuyển sang “rhythm classification + AF episode + signal quality + context alert”.

Thứ tự ưu tiên:

1. Train model 4 class bằng PhysioNet/CinC 2017:
   normal / possible_afib / other_rhythm / noise

2. Dùng NSTDB để chống nhiễu.

3. Dùng AFDB để đánh giá AF episode và AF burden.

4. Dùng MIT-BIH Arrhythmia sau cùng để mở rộng PVC/PAC.

5. Tích hợp lại vào pipeline.py và dashboard.

Bản rebuild nên hướng đến output cuối:

{
  "rhythm_status": "possible_afib",
  "confidence": 0.86,
  "heart_rate_bpm": 112,
  "signal_quality": "good",
  "activity_context": "rest",
  "af_episode_active": true,
  "af_episode_duration_sec": 120,
  "af_burden_percent": 1.8,
  "alert_level": "high",
  "message": "Possible AFib episode detected. Continue monitoring and consider medical review."
}

Đây là hướng thực tế, đúng dữ liệu, đúng khả năng của Polar H10 và dễ bảo vệ nhất về mặt kỹ thuật.