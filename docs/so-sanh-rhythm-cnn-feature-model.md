# Báo cáo so sánh Rhythm Feature Model và CNN Rhythm Model

## 1. Mục tiêu so sánh

Mục tiêu của phần này là đánh giá hai phương pháp phân loại nhịp ECG cho hệ thống theo dõi realtime:

- **Rhythm Feature Model**: mô hình học máy truyền thống, sử dụng các đặc trưng được trích xuất thủ công từ ECG/HRV/morphology.
- **CNN Rhythm Model**: mô hình 1D-CNN học trực tiếp từ chuỗi ECG raw đã chuẩn hóa.

Bài toán phân loại gồm 4 lớp:

| Class ID | Nhãn | Ý nghĩa |
|---:|---|---|
| 0 | `normal` | Nhịp bình thường |
| 1 | `possible_afib` | Có khả năng rung nhĩ |
| 2 | `other_rhythm` | Nhịp bất thường khác |
| 3 | `noise` | Tín hiệu nhiễu/không đáng tin cậy |

Trong hệ thống realtime, mục tiêu quan trọng không chỉ là accuracy cao, mà còn phải phát hiện tốt các lớp có ý nghĩa cảnh báo như `possible_afib` và `noise`.

## 2. Phương pháp 1: Rhythm Feature Model

Feature model hiện tại sử dụng `HistGradientBoostingClassifier` và 41 đặc trưng ECG, gồm:

- Đặc trưng R-peak/RR interval.
- Đặc trưng nhịp tim: mean HR, min HR, max HR, HR range.
- Đặc trưng HRV: SDNN, RMSSD, pNN50, RR irregularity.
- Đặc trưng morphology: QRS width, R amplitude.
- Đặc trưng thống kê tín hiệu: mean, std, IQR, skewness, kurtosis, energy.
- Đặc trưng miền tần số và signal quality.

Kết quả train/evaluate:

| Chỉ số | Giá trị |
|---|---:|
| Dataset shape | 11751 windows x 3900 samples |
| Feature shape | 11751 windows x 41 features |
| Split strategy | Group shuffle split |
| Record overlap | 0 |
| Accuracy | 74.07% |
| Macro F1 | 71.44% |
| AFib recall | 66.05% |
| Noise recall | 85.54% |

Classification report chính:

| Lớp | Precision | Recall | F1-score | Support |
|---|---:|---:|---:|---:|
| normal | 76.07% | 84.46% | 80.05% | 1197 |
| possible_afib | 75.35% | 66.05% | 70.39% | 162 |
| other_rhythm | 62.26% | 46.40% | 53.17% | 569 |
| noise | 79.03% | 85.54% | 82.16% | 401 |

Confusion matrix:

| Actual \ Predicted | normal | possible_afib | other_rhythm | noise |
|---|---:|---:|---:|---:|
| normal | 1011 | 6 | 122 | 58 |
| possible_afib | 19 | 107 | 27 | 9 |
| other_rhythm | 254 | 27 | 264 | 24 |
| noise | 45 | 2 | 11 | 343 |

Nhận xét:

- Mô hình phát hiện `possible_afib` tốt hơn CNN, với recall 66.05%.
- Mô hình nhận biết `noise` rất tốt, recall 85.54%, giúp giảm nguy cơ đưa ra cảnh báo sai trên tín hiệu kém.
- Macro F1 cao hơn đáng kể, cho thấy mô hình cân bằng giữa các lớp tốt hơn.
- Điểm yếu chính là lớp `other_rhythm` vẫn còn bị nhầm sang `normal`, nhưng vẫn tốt hơn CNN về recall.

## 3. Phương pháp 2: CNN Rhythm Model

CNN model sử dụng kiến trúc 1D-CNN để học trực tiếp từ ECG raw window dài 30 giây, tương ứng 3900 mẫu ở 130 Hz.

Đặc điểm:

- Input: chuỗi ECG raw đã resample và normalize.
- Không cần feature engineering thủ công.
- Có khả năng học morphology/pattern trực tiếp từ waveform.
- Train trên CPU trong 12 epoch, best epoch là epoch 6.

Kết quả train/evaluate:

| Chỉ số | Giá trị |
|---|---:|
| Dataset shape | 10151 windows x 3900 samples |
| Split strategy | Group shuffle split |
| Record overlap | 0 |
| Epochs ran | 12 |
| Best epoch | 6 |
| Accuracy | 71.66% |
| Macro F1 | 55.15% |
| AFib recall | 38.65% |
| Noise recall | 48.00% |
| Mean prediction confidence | 73.16% |

Classification report chính:

| Lớp | Precision | Recall | F1-score | Support |
|---|---:|---:|---:|---:|
| normal | 72.99% | 96.75% | 83.21% | 1232 |
| possible_afib | 63.64% | 38.65% | 48.09% | 163 |
| other_rhythm | 70.76% | 29.14% | 41.29% | 573 |
| noise | 48.00% | 48.00% | 48.00% | 50 |

Confusion matrix:

| Actual \ Predicted | normal | possible_afib | other_rhythm | noise |
|---|---:|---:|---:|---:|
| normal | 1192 | 4 | 23 | 13 |
| possible_afib | 57 | 63 | 41 | 2 |
| other_rhythm | 364 | 31 | 167 | 11 |
| noise | 20 | 1 | 5 | 24 |

Nhận xét:

- CNN có recall rất cao ở lớp `normal` nhưng điều này chưa đủ tốt cho bài toán cảnh báo.
- CNN bỏ sót nhiều ca `possible_afib`: 57 mẫu AFib bị dự đoán thành normal, 41 mẫu bị dự đoán thành other rhythm.
- CNN bỏ sót nhiều `other_rhythm`: 364 mẫu other rhythm bị dự đoán thành normal.
- Noise recall chỉ đạt 48%, thấp hơn nhiều so với feature model. Điều này không phù hợp cho realtime vì tín hiệu Polar có thể bị nhiễu do tiếp xúc điện cực hoặc vận động.

## 4. So sánh trực tiếp

| Chỉ số | Feature Model | CNN Model | Chênh lệch CNN - Feature | Model tốt hơn |
|---|---:|---:|---:|---|
| Accuracy | 74.07% | 71.66% | -2.41 điểm % | Feature |
| Macro F1 | 71.44% | 55.15% | -16.30 điểm % | Feature |
| AFib recall | 66.05% | 38.65% | -27.40 điểm % | Feature |
| Noise recall | 85.54% | 48.00% | -37.54 điểm % | Feature |

Điểm quan trọng:

- Accuracy của hai mô hình nhìn khá gần nhau, nhưng accuracy không phản ánh đủ chất lượng trong bài toán mất cân bằng lớp.
- `normal` là lớp chiếm tỷ trọng lớn, nên mô hình có thể đạt accuracy tương đối cao dù bỏ sót AFib hoặc noise.
- Với hệ thống chăm sóc sức khỏe, `AFib recall` và `noise recall` quan trọng hơn accuracy thuần.
- Feature model tốt hơn ở cả macro F1, AFib recall và noise recall.

## 5. Lý do chọn Feature Model làm model chính

Feature model được chọn làm model chính cho realtime vì:

1. **Khả năng phát hiện AFib tốt hơn**

   Feature model đạt AFib recall 66.05%, trong khi CNN chỉ đạt 38.65%. Với bài toán cảnh báo rung nhĩ, bỏ sót AFib là rủi ro lớn hơn so với việc cần theo dõi thêm.

2. **Khả năng nhận biết tín hiệu nhiễu tốt hơn**

   Feature model đạt noise recall 85.54%, CNN chỉ đạt 48.00%. Trong dữ liệu thực tế từ Polar H10, tín hiệu có thể bị nhiễu do vận động, tiếp xúc kém hoặc dây đeo chưa ổn định. Nếu model không nhận ra noise, hệ thống có thể đưa ra cảnh báo sai.

3. **Cân bằng giữa các lớp tốt hơn**

   Macro F1 của feature model là 71.44%, cao hơn CNN 55.15%. Điều này cho thấy feature model ổn định hơn trên nhiều class, không chỉ học tốt lớp normal.

4. **Phù hợp với triển khai realtime trên Raspberry Pi**

   Feature model nhẹ hơn CNN, inference nhanh hơn, ít phụ thuộc phần cứng hơn và phù hợp hơn với thiết bị biên như Raspberry Pi.

5. **Dễ giải thích hơn**

   Các feature như HRV, RR irregularity, QRS width, signal quality có ý nghĩa sinh lý rõ ràng. Điều này giúp báo cáo, debug và giải thích kết quả dễ hơn so với CNN black-box.

## 6. Vai trò của CNN sau khi so sánh

CNN chưa nên dùng làm model chính ở thời điểm hiện tại, nhưng vẫn có giá trị nghiên cứu:

- Dùng làm baseline deep learning.
- Dùng để so sánh với feature model trong báo cáo.
- Có thể cải thiện sau bằng augmentation, class balancing, kiến trúc sâu hơn hoặc train thêm dữ liệu.
- Có thể dùng lại khi có GPU hoặc dataset lớn hơn.

Trong code hiện tại, quyết định triển khai production là:

```text
src.api.pipeline chỉ import và chạy rhythm_feature_model
```

CNN không còn nằm trong runtime production. Nếu muốn thử nghiệm lại CNN, chạy tooling nghiên cứu:

```text
pip install -r requirements-research.txt
python -m src.training.train_rhythm_cnn --dataset-dir data_processed/rhythm --model-dir models/research/rhythm_cnn --metrics-dir models/metrics
```

## 7. Kết luận thuyết trình

Kết luận ngắn gọn:

> Sau khi so sánh mô hình học máy dựa trên feature và mô hình CNN học trực tiếp từ ECG raw, hệ thống chọn feature model làm mô hình chính cho phân loại nhịp realtime. Lý do là feature model có macro F1 cao hơn, phát hiện AFib tốt hơn và nhận biết tín hiệu nhiễu tốt hơn. CNN tuy có accuracy gần tương đương nhưng bỏ sót nhiều AFib và noise, chưa phù hợp để dùng làm mô hình cảnh báo chính trong hệ thống chăm sóc sức khỏe realtime.

Kết luận kỹ thuật:

- Feature model là lựa chọn production hiện tại.
- CNN là hướng phát triển tiếp theo, chưa thay thế feature model.
- Với hệ thống y tế, không chọn model chỉ dựa trên accuracy; cần ưu tiên recall của các lớp cảnh báo và khả năng xử lý tín hiệu nhiễu.

## 8. Gợi ý slide thuyết trình

### Slide 1: Mục tiêu

- Phân loại nhịp ECG realtime thành normal, possible AFib, other rhythm, noise.
- So sánh feature-based ML và 1D-CNN.
- Chọn model phù hợp cho hệ thống chạy trên thiết bị thật.

### Slide 2: Feature Model

- Trích xuất 41 đặc trưng ECG/HRV/morphology/signal quality.
- Model: HistGradientBoostingClassifier.
- Ưu điểm: nhẹ, dễ giải thích, phù hợp Raspberry Pi.

### Slide 3: CNN Model

- Input trực tiếp ECG raw 30 giây, 3900 samples.
- Model: 1D-CNN.
- Ưu điểm: tự học pattern từ waveform.
- Nhược điểm hiện tại: cần nhiều dữ liệu và tuning hơn.

### Slide 4: Bảng so sánh

| Metric | Feature | CNN |
|---|---:|---:|
| Accuracy | 74.07% | 71.66% |
| Macro F1 | 71.44% | 55.15% |
| AFib recall | 66.05% | 38.65% |
| Noise recall | 85.54% | 48.00% |

### Slide 5: Vì sao không chọn CNN lúc này

- Accuracy gần nhau nhưng CNN bỏ sót nhiều AFib.
- CNN nhận diện noise yếu hơn.
- Macro F1 thấp hơn, nghĩa là xử lý các lớp thiểu số kém hơn.
- Với bài toán cảnh báo sức khỏe, bỏ sót AFib/noise là không phù hợp.

### Slide 6: Quyết định cuối cùng

- Dùng feature model làm model chính.
- Giữ CNN làm hướng nghiên cứu tiếp theo.
- Pipeline production: `rhythm_feature_model`.
