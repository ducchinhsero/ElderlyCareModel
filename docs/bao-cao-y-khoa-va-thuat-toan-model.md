# Báo cáo kiến thức y khoa và thuật toán model

## 1. Mục tiêu của phần model

Dự án xây dựng hệ thống Edge AI theo dõi sức khỏe người cao tuổi, trong đó Raspberry/thiết bị biên xử lý dữ liệu tại chỗ để phát hiện sớm các dấu hiệu rủi ro. Trọng tâm model hiện tại là phân tích tín hiệu ECG một chuyển đạo và ngữ cảnh vận động ACC nhằm:

- Ước lượng nhịp tim hiện tại.
- Đánh giá chất lượng tín hiệu ECG trước khi đưa ra kết luận.
- Phân loại nhịp tim theo các nhóm: bình thường, nghi rung nhĩ, nhịp khác, nhiễu.
- Theo dõi episode nghi rung nhĩ theo thời gian thay vì chỉ dựa trên một cửa sổ đơn lẻ.
- Phát hiện ngoại tâm thu PVC/PAC ở mức hỗ trợ.
- Phát hiện té ngã hoặc va đập mạnh bằng gia tốc kế.
- Kết hợp kết quả model với luật y khoa/ngữ cảnh vận động để tạo cảnh báo tại biên.

Về mặt nghiên cứu, điểm cốt lõi không phải là một model duy nhất, mà là pipeline nhiều tầng:

```text
ECG/ACC từ thiết bị đeo
→ tiền xử lý tín hiệu
→ kiểm tra chất lượng tín hiệu
→ trích xuất đặc trưng sinh lý
→ suy luận model nhịp tim / ngoại tâm thu / anomaly
→ hậu xử lý theo thời gian
→ luật cảnh báo y khoa có xét ngữ cảnh vận động
→ cảnh báo tại biên + đồng bộ dữ liệu lên cloud/app
```

## 2. Kiến thức y khoa được sử dụng

### 2.1 ECG và các thành phần cơ bản

ECG, hay điện tâm đồ, ghi lại hoạt động điện của tim. Trong dự án này hệ thống dùng ECG một chuyển đạo từ thiết bị đeo, phù hợp cho theo dõi liên tục nhưng không tương đương ECG 12 chuyển đạo trong chẩn đoán lâm sàng.

Các khái niệm chính:

- **R-peak:** đỉnh R trong phức bộ QRS, thường là điểm cao nhất mỗi nhịp tim. Đây là điểm neo quan trọng để tính khoảng cách giữa các nhịp.
- **QRS complex:** pha khử cực thất. QRS rộng/bất thường có thể gợi ý nhịp thất hoặc dẫn truyền bất thường, nhưng với ECG một chuyển đạo chỉ nên xem là dấu hiệu hỗ trợ.
- **RR interval:** khoảng thời gian giữa hai R-peak liên tiếp, tính bằng mili giây. RR là nền tảng để tính nhịp tim và độ biến thiên nhịp tim.
- **Heart rate, HR:** nhịp tim, tính bằng nhịp/phút.

Công thức cơ bản:

```text
RR_i = (R_i - R_{i-1}) / fs * 1000  (ms)
HR_i = 60000 / RR_i                 (BPM)
```

Trong đó:

- `R_i`: vị trí mẫu của R-peak thứ i.
- `fs`: tần số lấy mẫu, đơn vị Hz.
- `BPM`: beats per minute, số nhịp mỗi phút.

Trong code, phần này nằm ở:

- `src/features/ecg_features.py`
- `src/features/rhythm_features.py`

### 2.2 Nhịp tim nhanh và nhịp tim chậm

Hệ thống dùng ngưỡng nhịp tim để phát hiện tình huống cần chú ý:

- **Tachycardia:** nhịp tim nhanh. Theo AHA, nhịp tim nghỉ trên 100 BPM được gọi là tachycardia.
- **Bradycardia:** nhịp tim chậm. Theo AHA, nhịp tim nghỉ dưới 60 BPM thường được xem là bradycardia, nhưng người khỏe mạnh/vận động viên có thể thấp hơn mà không nguy hiểm.

Trong dự án, ngưỡng được điều chỉnh theo ngữ cảnh để giảm báo sai:

- `tachycardia_at_rest`: HR > 100 BPM khi trạng thái vận động là nghỉ ngơi và cửa sổ đủ dài.
- `bradycardia`: HR < 50 BPM khi không phải ngủ/không rõ trạng thái và cửa sổ đủ dài.
- Với ACC, ngưỡng nhịp tim cao được nới rộng khi người dùng đi bộ/vận động.

Lý do: người cao tuổi có thể tăng nhịp khi hoạt động nhẹ; nếu chỉ dùng một ngưỡng cố định sẽ tạo nhiều cảnh báo giả. Do đó, hệ thống kết hợp HR với `activity_state`.

File liên quan:

- `src/inference/hr_event.py`
- `src/features/acc_features.py`

### 2.3 Rung nhĩ, AFib

**AFib**, hay atrial fibrillation/rung nhĩ, là một dạng rối loạn nhịp trong đó nhịp tim trở nên không đều. AHA mô tả AFib là nhịp tim bất thường có thể dẫn tới huyết khối, đột quỵ, suy tim và các biến chứng tim mạch khác. CDC cũng ghi nhận AFib liên quan tới nguy cơ đột quỵ thiếu máu cục bộ tăng khoảng 5 lần.

Dấu hiệu ECG thường được dùng để nghi ngờ AFib:

- RR interval thay đổi thất thường, thường gọi là irregularly irregular.
- Sóng P không rõ hoặc không ổn định.
- Nhịp có thể nhanh hoặc không nhanh tùy đáp ứng thất.

Giới hạn quan trọng của dự án:

- Thiết bị dùng ECG một chuyển đạo, do đó không khẳng định chẩn đoán AFib như ECG 12 chuyển đạo.
- Model trả nhãn **possible_afib** thay vì “AFib chắc chắn”.
- Cảnh báo phải hiểu là “nghi ngờ/rủi ro cần theo dõi hoặc xác nhận y tế”, không phải kết luận điều trị.

Trong code:

- Nhãn `possible_afib` nằm trong `src/preprocessing.py`.
- Model nhịp nằm trong `src/inference/rhythm_inference.py`.
- Theo dõi episode nằm trong `src/inference/af_episode_tracker.py`.
- Cấu hình ngưỡng nằm trong `models/rhythm/rhythm_decision_config.json`.

### 2.4 AF episode và AF burden

Không nên báo AFib chỉ vì một cửa sổ ECG đơn lẻ. Dự án dùng hậu xử lý theo thời gian để theo dõi AF episode:

- **AF window:** một cửa sổ ECG có xác suất AFib vượt ngưỡng.
- **AF episode:** chuỗi các AF window liên tiếp đủ điều kiện.
- **AF burden:** tỷ lệ thời gian nghi AFib trên tổng thời gian theo dõi.

Công thức:

```text
AF burden (%) = tổng thời gian nghi AF / tổng thời gian theo dõi * 100
```

Trong hệ thống hiện tại:

- Mỗi cửa sổ episode mặc định tương ứng 30 giây.
- Cần tối thiểu 2 cửa sổ liên tiếp để episode ổn định hơn.
- `episode_threshold` hiện chọn theo đánh giá AFDB là 0.05.
- `alert_threshold` dùng để cảnh báo tức thời là 0.3.

Ý nghĩa nghiên cứu: phần này biến kết quả model từng cửa sổ thành chỉ số theo thời gian, gần hơn với cách bác sĩ quan tâm tới tải lượng AFib thay vì chỉ một dự đoán rời rạc.

### 2.5 HRV, SDNN, RMSSD, pNN50, LF/HF

**HRV**, heart rate variability, là độ biến thiên giữa các nhịp tim liên tiếp. HRV phản ánh phần nào hoạt động hệ thần kinh tự chủ, trạng thái hồi phục, stress và sức khỏe tim mạch. Các chỉ số HRV phải được diễn giải thận trọng vì bị ảnh hưởng bởi tuổi, thuốc, bệnh nền, vận động, chất lượng tín hiệu và thời điểm đo.

Các chỉ số dự án dùng:

- **SDNN:** độ lệch chuẩn của chuỗi RR.
- **RMSSD:** căn bậc hai trung bình bình phương sai khác giữa các RR liên tiếp.
- **pNN50:** tỷ lệ phần trăm cặp RR liên tiếp chênh nhau hơn 50 ms.
- **LF/HF:** tỷ lệ công suất vùng tần số thấp và cao của HRV.

Công thức:

```text
SDNN = std(RR)
RMSSD = sqrt(mean((RR_i - RR_{i-1})^2))
pNN50 = count(|RR_i - RR_{i-1}| > 50 ms) / số cặp RR * 100
LF/HF = LF_power / HF_power
```

Trong dự án, HRV vừa là đặc trưng đầu vào cho model, vừa là thông tin hiển thị nếu backend cung cấp đủ dữ liệu. Không nên dùng riêng RMSSD để kết luận bệnh; RMSSD thấp chỉ là dấu hiệu cần xem cùng HR, nhịp, vận động và bệnh nền.

File liên quan:

- `src/features/ecg_features.py`
- `src/features/rhythm_features.py`

### 2.6 Ngoại tâm thu PVC/PAC

**PVC**, premature ventricular contraction, là nhịp sớm xuất phát từ thất. **PAC**, premature atrial contraction, là nhịp sớm xuất phát từ nhĩ. Trong hệ thống, PVC/PAC được xem là tín hiệu phụ để nhận biết hoạt động ngoại tâm thu, không phải chẩn đoán độc lập.

Dấu hiệu đặc trưng hóa trong dự án:

- Nhịp đến sớm: RR ngắn hơn median RR.
- Khoảng nghỉ bù: RR sau nhịp sớm dài hơn bình thường.
- QRS rộng hoặc biên độ R khác biệt.
- Tỷ lệ cặp ngắn-dài liên tiếp.

Các đặc trưng:

- `premature_rr_ratio`
- `compensatory_pause_ratio`
- `short_long_rr_pair_ratio`
- `qrs_width_outlier_ratio`
- `r_amplitude_outlier_ratio`
- `pvc_like_ratio`
- `pac_like_ratio`

File liên quan:

- `src/features/ectopy_features.py`
- `src/inference/ectopy_inference.py`

### 2.7 Chất lượng tín hiệu ECG

Một trong các nguyên tắc quan trọng của hệ thống là không đưa ra cảnh báo nhịp nghiêm trọng khi tín hiệu quá xấu. Dữ liệu ECG từ thiết bị đeo dễ bị:

- Lỏng dây/tiếp xúc điện cực kém.
- Nhiễu do chuyển động.
- Baseline wander.
- Mất mẫu hoặc tín hiệu gần phẳng.

Hệ thống kiểm tra:

- Tỷ lệ NaN/mẫu không hợp lệ.
- Tỷ lệ mẫu bằng 0.
- Độ lệch chuẩn và biên độ ECG.
- Số lượng R-peak phát hiện được.
- Tỷ lệ RR hợp lệ trong khoảng sinh lý 300-2000 ms.
- Tỷ lệ RR outlier.

Nếu tín hiệu `poor`, pipeline trả nhãn `unknown` hoặc hạ mức tin cậy, thay vì cố dự đoán.

### 2.8 Té ngã ở người cao tuổi

Té ngã là vấn đề y tế công cộng nghiêm trọng ở người cao tuổi. CDC ghi nhận té ngã ở người từ 65 tuổi trở lên là nguyên nhân hàng đầu gây tử vong do chấn thương trong nhóm tuổi này; hơn 1/4 người cao tuổi bị ngã mỗi năm.

Dự án dùng ACC để phát hiện mẫu té ngã:

- **Impact spike:** gia tốc tổng hợp tăng mạnh.
- **Free-fall:** khoảng trước va chạm có gia tốc thấp.
- **Post-still:** sau va chạm có giai đoạn ít chuyển động.
- **Strong fall:** va chạm mạnh kèm free-fall và post-still.

Công thức gia tốc tổng hợp:

```text
VM = sqrt(x^2 + y^2 + z^2)
```

Trong đó `x`, `y`, `z` là gia tốc theo ba trục. Hệ thống phân biệt “va chạm khi vận động” với “té ngã thật” bằng cách xét trạng thái hoạt động và ngưỡng impact cao hơn khi người dùng đang vận động mạnh.

File liên quan:

- `src/features/acc_features.py`

## 3. Thuật toán và phương thức xử lý tín hiệu

### 3.1 Tiền xử lý ECG

Pipeline xử lý ECG theo các bước:

1. Nhận ECG từ Polar H10 hoặc payload `/ingest-ecg`.
2. Ép dữ liệu thành mảng số một chiều.
3. Resample về 130 Hz cho đồng nhất.
4. Chuẩn hóa biên độ.
5. Lọc thông dải bằng Butterworth bậc 2, vùng 5-40 Hz.
6. Tìm R-peak bằng `scipy.signal.find_peaks`.
7. Tính RR interval và đặc trưng.

Lọc thông dải giúp giảm nhiễu tần số thấp và nhiễu cao. R-peak detection là bước then chốt; nếu R-peak sai thì HRV, AFib và PVC/PAC đều có nguy cơ sai.

### 3.2 Cửa sổ dữ liệu

Model không phân tích từng mẫu ECG riêng lẻ, mà phân tích theo cửa sổ:

- Cửa sổ rhythm/CNN: 30 giây, tương ứng 3900 mẫu ở 130 Hz.
- Pipeline realtime có bước nhận chunk và sinh kết quả theo từng đoạn.
- Với HRV/anomaly legacy có cửa sổ theo số RR/beat, thường `window_size = 10`.

Lý do dùng cửa sổ:

- Nhịp tim là hiện tượng theo thời gian, không thể đánh giá ổn định từ một nhịp đơn lẻ.
- AFib cần nhìn sự không đều của nhiều RR liên tiếp.
- Té ngã cần chuỗi trước-va chạm-sau va chạm.

### 3.3 Feature engineering cho rhythm model

Model rhythm chính dùng 41 đặc trưng, chia thành các nhóm:

Nhóm nhịp tim/RR:

- `mean_hr`, `median_hr`, `min_hr`, `max_hr`
- `mean_rr`, `median_rr`, `std_rr`, `rr_iqr`, `rr_range`
- `rmssd`, `sdnn`, `pnn50`
- `rr_irregularity_index`
- `rr_outlier_ratio`
- `sample_entropy`
- `turning_point_ratio`

Nhóm hình thái ECG:

- `qrs_width_mean`, `qrs_width_std`
- `r_amplitude_mean`, `r_amplitude_std`

Nhóm thống kê tín hiệu:

- `ecg_mean`, `ecg_std`, `ecg_iqr`, `ecg_range`
- `ecg_skewness`, `ecg_kurtosis`
- `ecg_energy`, `line_length`
- `zero_crossing_rate`
- `spectral_entropy`
- `high_freq_power_ratio`

Nhóm chất lượng:

- `signal_quality_score`
- `r_peak_count`
- `valid_rr_ratio`

Ý nghĩa: thay vì đưa ECG raw trực tiếp vào model, hệ thống chuyển ECG thành các đặc trưng có ý nghĩa sinh lý. Cách này phù hợp edge AI vì nhẹ, dễ giải thích, dễ chạy trên Raspberry hơn deep learning lớn.

## 4. Các model được sử dụng

### 4.1 Rhythm feature model, model chính

Nhiệm vụ:

```text
ECG 30 giây → normal / possible_afib / other_rhythm / noise
```

Dữ liệu:

- PhysioNet/CinC Challenge 2017 cho ECG một chuyển đạo ngắn.
- Dataset đã xử lý: `data_processed/rhythm`.

Mô hình được thử:

- `RandomForestClassifier`
- `ExtraTreesClassifier`
- `HistGradientBoostingClassifier`

Mô hình được chọn:

```text
HistGradientBoostingClassifier
```

Lý do chọn: có điểm selection_score cao nhất, macro F1 cao hơn, noise recall tốt hơn và false AFib từ noise thấp.

Kỹ thuật huấn luyện:

- Trích 41 đặc trưng từ ECG.
- Chuẩn hóa bằng `StandardScaler`.
- Chia train/test theo `GroupShuffleSplit` để tránh cùng record xuất hiện ở cả train và test.
- Dùng sample weight để tăng trọng số cho AFib và noise vì đây là hai lớp quan trọng về mặt lâm sàng.

Kết quả hiện tại:

| Chỉ số | Giá trị |
|---|---:|
| Accuracy | 0.732 |
| Macro F1 | 0.706 |
| AFib recall | 0.636 |
| Noise recall | 0.853 |
| False AFib from noise | 0.0075 |

Diễn giải:

- Model nhận biết noise khá tốt, giúp giảm cảnh báo giả do tín hiệu xấu.
- AFib recall khoảng 63.6% trên test split hiện tại, nghĩa là vẫn còn bỏ sót một phần cửa sổ nghi AFib.
- Precision AFib khoảng 75.7%, tức là khi model báo `possible_afib`, tỷ lệ đúng trên tập test khá tốt nhưng chưa đủ để gọi là chẩn đoán y khoa.
- Đây là model có thể dùng cho cảnh báo theo dõi, chưa đủ để tự động kết luận bệnh.

File:

- `src/training/train_rhythm_features.py`
- `src/inference/rhythm_inference.py`
- `models/metrics/rhythm_feature_metrics.json`

### 4.2 Rhythm CNN 1D, model thử nghiệm

Nhiệm vụ giống rhythm feature model nhưng dùng ECG raw 30 giây.

Kiến trúc:

```text
Input: 1 x 3900
→ Conv1D(32, kernel=15, stride=2)
→ BatchNorm + ReLU + MaxPool
→ Conv1D(64, kernel=9, stride=2)
→ BatchNorm + ReLU + MaxPool
→ Conv1D(128, kernel=7, stride=2)
→ BatchNorm + ReLU
→ Conv1D(128, kernel=5)
→ BatchNorm + ReLU
→ AdaptiveAvgPool1D
→ Dropout
→ Linear classifier
```

Kết quả hiện tại:

| Chỉ số | CNN | Feature model |
|---|---:|---:|
| Accuracy | 0.717 | 0.732 |
| Macro F1 | 0.551 | 0.706 |
| AFib recall | 0.387 | 0.636 |
| Noise recall | 0.480 | 0.853 |

Kết luận: CNN chưa được chọn làm mặc định vì kém hơn feature model ở macro F1, AFib recall và noise recall. Trong nghiên cứu, CNN được trình bày như hướng phát triển tiếp theo, không phải model production hiện tại.

File:

- `src/training/train_rhythm_cnn.py`
- `src/inference/rhythm_cnn_inference.py`
- `models/metrics/rhythm_cnn_metrics.json`

### 4.3 AF episode tracker

Đây không phải model học máy, mà là thuật toán hậu xử lý theo thời gian.

Đầu vào:

- `rhythm_label`
- `possible_afib_probability`

Logic:

```text
Nếu P(AFib) >= threshold:
    đánh dấu cửa sổ là AF window
Nếu có ít nhất 2 AF window liên tiếp:
    mở hoặc kéo dài AF episode
Nếu cửa sổ hiện tại không đạt:
    đóng episode hiện tại
```

Kết quả trên MIT-BIH AFDB:

| Chỉ số | Giá trị |
|---|---:|
| Window accuracy | 0.838 |
| AFib precision | 0.913 |
| AFib recall | 0.655 |
| AFib F1 | 0.763 |
| Episode sensitivity | 0.758 |
| Episode precision | 0.854 |
| False episode/hour | 0.564 |

Diễn giải:

- Precision cao, tức là khi báo AFib thì khả năng đúng tương đối tốt.
- Recall trung bình, tức là còn bỏ sót một phần AFib.
- AF burden dự đoán thấp hơn thực tế trong đánh giá hiện tại; cần cải thiện nếu dùng cho thống kê y khoa dài hạn.

File:

- `src/inference/af_episode_tracker.py`
- `src/training/evaluate_long_term_afdb.py`
- `models/metrics/afdb_long_term_metrics.json`

### 4.4 PVC/PAC ectopy model

Nhiệm vụ:

```text
ECG window → normal / pvc / pac / mixed_ectopic / other
```

Dữ liệu:

- MIT-BIH Arrhythmia Database.
- Dataset xử lý: `data_processed/mitdb_ectopy`.

Đặc trưng:

- 41 rhythm features.
- 7 đặc trưng ngoại tâm thu bổ sung.

Model được chọn:

```text
HistGradientBoostingClassifier
```

Kết quả hiện tại:

| Chỉ số | Giá trị |
|---|---:|
| Accuracy | 0.550 |
| Macro F1 | 0.293 |
| PVC recall | 0.846 |
| PAC recall | 0.177 |
| Mixed ectopic recall | 0.000 |

Diễn giải:

- Model phát hiện PVC tương đối nhạy.
- PAC và mixed ectopic còn yếu.
- Không nên trình bày model này như module chẩn đoán hoàn chỉnh; nên ghi là module hỗ trợ phát hiện ngoại tâm thu, đang cần mở rộng dữ liệu và cải thiện thuật toán.

### 4.5 Stress model

Nhiệm vụ:

```text
Rolling RR/HRV features → non_stress / stress / unknown
```

Dữ liệu:

- WESAD, dataset wearable stress and affect detection.

Model:

- Soft voting gồm RandomForest và SVM pipeline.
- LOSO/GroupKFold theo subject.
- Realtime cần rolling RR buffer khoảng 300 giây; nếu chưa đủ dữ liệu thì trả `unknown`.

Đặc trưng:

- `RR_mean`, `mean_HR`, `RR_min`, `RR_max`, `CVRR`, `SDNN`, `RMSSD`, `pNN50`, `LF/HF`.

Vai trò trong dự án:

- Đây là module phụ, dùng để tham khảo trạng thái sinh lý/stress.
- Không phải module y khoa cốt lõi bằng rhythm/AFib/fall.
- Stress không tự nâng cảnh báo quá `medium` và bị suppress khi người dùng đang `WALK` hoặc `ACTIVE`.

### 4.6 Anomaly legacy model

Model anomaly legacy dùng `IsolationForest` huấn luyện trên dữ liệu normal để phát hiện bất thường chung.

Đặc trưng:

- HRV: RR_mean, SDNN, RMSSD, pNN50, LF/HF.
- Hình thái: amplitude, energy, QRS slope.

Vai trò hiện tại:

- Module screening phụ, không phải lõi chẩn đoán.
- Global anomaly legacy đang bật mặc định với signal-quality gate: nếu tín hiệu kém, nhiễu hoặc nghi ngờ đeo lỏng thì trả `unknown`.
- Patient-specific anomaly calibration tắt mặc định; chỉ bật khi `ANOMALY_CALIBRATION_ENABLED=1` và đã có baseline đủ chất lượng.
- Hệ thống vẫn ưu tiên rhythm classification + AF episode + signal quality + context alert vì có ý nghĩa y khoa rõ hơn.

## 5. Luật cảnh báo và kết hợp model

Hệ thống không lấy trực tiếp output model để cảnh báo. Thay vào đó, cảnh báo được tạo từ nhiều điều kiện:

- Chất lượng tín hiệu ECG.
- Nhãn rhythm và xác suất AFib.
- HR event: tachycardia/bradycardia.
- ACC context: nghỉ, đi bộ, hoạt động.
- Fall detection.
- AF episode theo thời gian.

Ví dụ logic:

```text
Nếu signal_quality = poor:
    không cảnh báo AFib mạnh, yêu cầu chỉnh thiết bị

Nếu rhythm = possible_afib và P(AFib) cao:
    cảnh báo rhythm

Nếu HR > 100 khi REST:
    tachycardia_at_rest

Nếu có free-fall + impact + post-still:
    fall_candidate hoặc strong_fall

Nếu người dùng ACTIVE và nhịp tăng vừa phải:
    giảm mức cảnh báo để tránh false alarm
```

Điểm quan trọng: đây là thiết kế phù hợp người cao tuổi, vì cảnh báo giả quá nhiều sẽ làm người chăm sóc bỏ qua cảnh báo thật. Ngược lại, té ngã và nhịp tim nguy hiểm phải được ưu tiên tức thì.

## 6. Khả năng hiện tại của model

### 6.1 Những gì model làm tốt

- Chạy được realtime/near-realtime trên pipeline edge.
- Có kiểm soát chất lượng tín hiệu trước khi suy luận.
- Phân loại rhythm 4 lớp ở mức chấp nhận được cho nghiên cứu prototype.
- Nhận biết noise tốt, giúp tránh nhầm nhiễu thành AFib.
- Có hậu xử lý AF episode và AF burden thay vì chỉ cảnh báo từng cửa sổ.
- Có kết hợp ACC để phát hiện té ngã và giảm báo sai khi vận động.
- Kiến trúc module hóa, dễ thay model lõi mà không phá pipeline.

### 6.2 Những gì chưa đủ mạnh

- AFib recall của rhythm feature model còn khoảng 0.636 trên test split; vẫn còn bỏ sót.
- CNN chưa tốt hơn feature model.
- PVC/PAC model chưa ổn định, đặc biệt PAC và mixed ectopic còn yếu.
- Chưa có đánh giá lâm sàng trên người cao tuổi thực tế trong môi trường sống thật.
- ECG một chuyển đạo không đủ để kết luận chẩn đoán như ECG y tế chuẩn.
- Các ngưỡng HR/ACC cần cá nhân hóa thêm theo bệnh nền, thuốc, độ tuổi và mức vận động.

### 6.3 Mức độ có thể tuyên bố trong báo cáo

Nên tuyên bố:

> Hệ thống hỗ trợ phát hiện sớm dấu hiệu bất thường nhịp tim và té ngã trên thiết bị biên, cung cấp cảnh báo và dữ liệu tham khảo cho người chăm sóc.

Không nên tuyên bố:

> Hệ thống chẩn đoán AFib/PVC/PAC chính xác như thiết bị y tế.

Nên dùng các cụm từ:

- “nghi ngờ rung nhĩ”
- “cảnh báo nguy cơ”
- “hỗ trợ theo dõi”
- “dữ liệu tham khảo”
- “cần xác nhận bởi nhân viên y tế/ECG chuẩn”

## 7. Đóng góp nghiên cứu của dự án

Đóng góp chính có thể trình bày:

1. Xây dựng pipeline edge AI xử lý ECG/ACC tại chỗ.
2. Kết hợp model học máy với tri thức y khoa và ngữ cảnh vận động.
3. Thiết kế tầng signal quality để giảm cảnh báo sai.
4. Dùng AF episode/AF burden thay vì chỉ dự đoán từng cửa sổ.
5. Ưu tiên cảnh báo tức thời cho té ngã và rối loạn nhịp nguy hiểm.
6. Đồng bộ dữ liệu đã xử lý lên cloud/app thay vì đẩy toàn bộ dữ liệu thô.

## 8. Ký hiệu và viết tắt

| Ký hiệu | Ý nghĩa |
|---|---|
| ECG | Electrocardiogram, điện tâm đồ |
| ACC | Accelerometer, gia tốc kế |
| HR | Heart rate, nhịp tim |
| BPM | Beats per minute, nhịp/phút |
| RR | Khoảng giữa hai R-peak liên tiếp |
| HRV | Heart rate variability, biến thiên nhịp tim |
| SDNN | Standard deviation of NN/RR intervals |
| RMSSD | Root mean square of successive RR differences |
| pNN50 | Tỷ lệ cặp RR liên tiếp lệch hơn 50 ms |
| LF/HF | Tỷ lệ công suất tần số thấp/tần số cao của HRV |
| AFib/AF | Atrial fibrillation, rung nhĩ |
| PVC | Premature ventricular contraction |
| PAC | Premature atrial contraction |
| QRS | Phức bộ khử cực thất trên ECG |
| VM | Vector magnitude của gia tốc |
| Precision | Tỷ lệ dự đoán dương tính là đúng |
| Recall/Sensitivity | Tỷ lệ trường hợp thật được phát hiện |
| F1-score | Trung bình điều hòa giữa precision và recall |
| Macro F1 | F1 trung bình đều giữa các lớp |

## 9. Nguồn tham khảo

Nguồn y khoa:

- American Heart Association, What is Atrial Fibrillation: https://www.heart.org/en/health-topics/atrial-fibrillation/what-is-atrial-fibrillation-afib-or-af
- CDC, About Atrial Fibrillation: https://www.cdc.gov/heart-disease/about/atrial-fibrillation.html
- American Heart Association, Tachycardia: https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/tachycardia--fast-heart-rate
- American Heart Association, Bradycardia: https://www.heart.org/en/health-topics/arrhythmia/about-arrhythmia/bradycardia--slow-heart-rate
- CDC, Older Adult Fall Prevention: https://www.cdc.gov/falls
- ESC/NASPE Task Force, Heart Rate Variability Standards, 1996: https://www.escardio.org/static-file/Escardio/Guidelines/Scientific-Statements/guidelines-Heart-Rate-Variability-FT-1996.pdf

Nguồn dữ liệu/model:

- PhysioNet/CinC Challenge 2017: https://physionet.org/challenge/2017/
- MIT-BIH Atrial Fibrillation Database: https://physionet.org/content/afdb/
- MIT-BIH Arrhythmia Database: https://www.physionet.org/physiobank/database/html/mitdbdir/mitdbdir.htm
- WESAD dataset: https://complexity.cecs.ucf.edu/wesad-wearable-stress-and-affect-detection/

Nguồn trong repo:

- `src/api/pipeline.py`
- `src/features/ecg_features.py`
- `src/features/rhythm_features.py`
- `src/features/acc_features.py`
- `src/features/ectopy_features.py`
- `src/inference/rhythm_inference.py`
- `src/inference/af_episode_tracker.py`
- `src/inference/alert_engine.py`
- `models/metrics/rhythm_feature_metrics.json`
- `models/metrics/rhythm_cnn_metrics.json`
- `models/metrics/ectopy_feature_metrics.json`
- `models/metrics/afdb_long_term_metrics.json`
