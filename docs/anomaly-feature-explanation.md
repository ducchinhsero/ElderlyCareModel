# Giải thích 10 feature của anomaly model

Ngày cập nhật: 2026-06-10

Tài liệu này giải thích bộ feature đang dùng cho **global anomaly legacy model**. Schema chính thức nằm tại:

```text
models/anomaly_legacy/anomaly_feature_schema.json
```

Code trích xuất feature nằm tại:

```text
src/features/ecg_features.py
```

Anomaly model hiện dùng 10 feature:

```text
RR_mean, SDNN, RMSSD, pNN50, LF/HF,
mean_amplitude, std_amplitude, mean_energy, std_energy, mean_qrs_slope
```

Các feature được chia thành 2 nhóm:

- **HRV/RR features**: mô tả nhịp tim và độ biến thiên giữa các nhịp.
- **Morphology features**: mô tả hình dạng/biên độ/năng lượng của từng nhịp ECG.

> Lưu ý: anomaly model chỉ là lớp **screening** để phát hiện cửa sổ ECG khác mẫu bình thường. Nó không chẩn đoán bệnh cụ thể.

## 1. Quy trình tạo feature

Pipeline tổng quát:

```text
raw ECG
-> bandpass filter 5-40 Hz
-> detect R-peaks
-> tính RR intervals theo milliseconds
-> cắt window theo số nhịp, mặc định 10 nhịp/window
-> tính HRV features từ RR window
-> cắt beat quanh từng R-peak
-> tính morphology features từng beat
-> aggregate morphology theo window
-> tạo 10 feature theo đúng schema
```

Trong code hiện tại:

- ECG được lọc bằng `bandpass_filter()`.
- R-peak được phát hiện bằng `detect_r_peaks()`.
- RR intervals được tính bằng `rr_intervals_ms_from_peaks()`.
- HRV được tính bằng `extract_hrv_features()`.
- Morphology từng beat được tính bằng `extract_beat_features()`.
- Morphology theo window được tính bằng `aggregate_morphological_features()`.
- Dòng feature hoàn chỉnh được tạo bằng `extract_anomaly_feature_rows()`.

## 2. Nhóm HRV/RR features

### 2.1 `RR_mean`

Ý nghĩa:

- Trung bình khoảng thời gian giữa hai R-peak liên tiếp.
- Đơn vị: milliseconds.
- RR càng thấp thì nhịp tim càng nhanh; RR càng cao thì nhịp tim càng chậm.

Công thức:

```text
RR_mean = mean(RR intervals)
```

Liên hệ với heart rate:

```text
HR_bpm = 60000 / RR_mean
```

Ví dụ:

- `RR_mean = 1000 ms` tương đương khoảng `60 bpm`.
- `RR_mean = 750 ms` tương đương khoảng `80 bpm`.

Vai trò trong anomaly:

- Giúp model biết nhịp tim trong window đang nhanh, chậm hay bình thường so với mẫu học được.

## 2.2 `SDNN`

Ý nghĩa:

- Độ lệch chuẩn của các RR intervals trong window.
- Đơn vị: milliseconds.
- Phản ánh độ biến thiên tổng thể của nhịp tim trong window.

Công thức:

```text
SDNN = std(RR intervals)
```

Diễn giải:

- SDNN quá thấp có thể cho thấy nhịp quá đều hoặc dữ liệu quá ngắn.
- SDNN quá cao có thể xuất hiện khi nhịp không đều, ngoại tâm thu, AFib-like pattern hoặc nhiễu R-peak.

Vai trò trong anomaly:

- Giúp phát hiện sự thay đổi bất thường trong độ đều/không đều của nhịp.

## 2.3 `RMSSD`

Ý nghĩa:

- Căn bậc hai trung bình bình phương sai khác giữa các RR liên tiếp.
- Đơn vị: milliseconds.
- Nhạy với biến thiên ngắn hạn giữa các nhịp liên tiếp.

Công thức:

```text
diff_RR_i = RR_i - RR_(i-1)
RMSSD = sqrt(mean(diff_RR_i^2))
```

Diễn giải:

- RMSSD tăng khi RR thay đổi mạnh giữa các nhịp liên tiếp.
- RMSSD có thể tăng trong các đoạn nhịp không đều hoặc khi R-peak detection bị nhiễu.

Vai trò trong anomaly:

- Giúp model nhận ra biến động nhịp ngắn hạn bất thường.

## 2.4 `pNN50`

Ý nghĩa:

- Tỷ lệ phần trăm cặp RR liên tiếp có độ chênh lớn hơn 50 ms.
- Đơn vị: phần trăm.

Công thức:

```text
pNN50 = 100 * count(|RR_i - RR_(i-1)| > 50 ms) / count(diff_RR)
```

Diễn giải:

- pNN50 cao nghĩa là nhiều cặp RR thay đổi đáng kể.
- pNN50 thấp nghĩa là nhịp tương đối đều trong window.

Vai trò trong anomaly:

- Bổ sung thông tin về mức độ biến thiên nhanh của RR.

## 2.5 `LF/HF`

Ý nghĩa:

- Tỷ lệ công suất phổ HRV vùng tần số thấp và cao.
- LF thường nằm trong khoảng `0.04-0.15 Hz`.
- HF thường nằm trong khoảng `0.15-0.40 Hz`.

Công thức trong code hiện tại:

```text
LF_power = sum(power spectrum trong vùng 0.04-0.15 Hz)
HF_power = sum(power spectrum trong vùng 0.15-0.40 Hz)
LF/HF = LF_power / HF_power
```

Diễn giải:

- Đây là feature HRV phổ tần.
- Với window ngắn hoặc số RR ít, LF/HF có độ tin cậy thấp hơn.

Vai trò trong anomaly:

- Giúp model có thêm thông tin tần số của biến thiên nhịp.

## 3. Nhóm morphology features

Morphology features được tính từ từng beat quanh R-peak. Với mỗi R-peak, code lấy đoạn ECG:

```text
before = 0.2 giây trước R-peak
after  = 0.4 giây sau R-peak
```

Từ đoạn beat này, code tính:

```text
beat_amplitude = max(beat) - min(beat)
beat_energy = sum(beat^2)
qrs_slope = max(diff(beat))
```

Sau đó aggregate theo window 10 nhịp để tạo 5 morphology features.

## 3.1 `mean_amplitude`

Ý nghĩa:

- Trung bình biên độ của các beat trong window.
- Biên độ beat được tính bằng:

```text
beat_amplitude = max(beat) - min(beat)
mean_amplitude = mean(beat_amplitude)
```

Diễn giải:

- Biên độ quá thấp có thể do tiếp xúc điện cực kém, dây đeo lỏng hoặc tín hiệu yếu.
- Biên độ quá cao có thể do nhiễu chuyển động, spike hoặc morphology bất thường.

Vai trò trong anomaly:

- Giúp model nhận diện cửa sổ có mức biên độ khác bình thường.

## 3.2 `std_amplitude`

Ý nghĩa:

- Độ lệch chuẩn biên độ beat trong window.

Công thức:

```text
std_amplitude = std(beat_amplitude)
```

Diễn giải:

- Thấp: các beat có biên độ khá giống nhau.
- Cao: biên độ các beat thay đổi mạnh, có thể do nhiễu, đeo lỏng, ngoại tâm thu hoặc morphology không ổn định.

Vai trò trong anomaly:

- Giúp phát hiện sự không ổn định về biên độ beat.

## 3.3 `mean_energy`

Ý nghĩa:

- Trung bình năng lượng của các beat trong window.
- Năng lượng beat là tổng bình phương giá trị ECG trong beat.

Công thức:

```text
beat_energy = sum(beat^2)
mean_energy = mean(beat_energy)
```

Diễn giải:

- Energy tăng khi tín hiệu có biên độ lớn hoặc nhiều dao động.
- Energy quá cao có thể do nhiễu/chuyển động/spike.
- Energy quá thấp có thể do tín hiệu yếu hoặc gần flatline.

Vai trò trong anomaly:

- Bổ sung thông tin về “mức mạnh” tổng thể của morphology ECG.

## 3.4 `std_energy`

Ý nghĩa:

- Độ lệch chuẩn năng lượng beat trong window.

Công thức:

```text
std_energy = std(beat_energy)
```

Diễn giải:

- Cao nghĩa là năng lượng các beat thay đổi mạnh.
- Có thể xuất hiện khi tín hiệu không ổn định, có noise hoặc beat bất thường xen kẽ.

Vai trò trong anomaly:

- Giúp model phát hiện cửa sổ có morphology không đều.

## 3.5 `mean_qrs_slope`

Ý nghĩa:

- Trung bình độ dốc QRS ước lượng của các beat.
- Trong code hiện tại:

```text
diff_beat = diff(beat)
qrs_slope = max(diff_beat)
mean_qrs_slope = mean(qrs_slope)
```

Diễn giải:

- Slope phản ánh mức tăng nhanh nhất trong beat.
- QRS bình thường thường có đoạn tăng/giảm nhanh quanh R-peak.
- Slope quá nhỏ có thể do tín hiệu bị bẹt/lọc yếu/tiếp xúc kém.
- Slope quá lớn có thể do spike hoặc nhiễu.

Vai trò trong anomaly:

- Giúp model nhận diện thay đổi hình dạng/sườn dốc beat.

## 4. Bảng tóm tắt

| Feature | Nhóm | Đơn vị | Ý nghĩa chính |
|---|---|---:|---|
| `RR_mean` | HRV/RR | ms | RR trung bình, liên quan trực tiếp đến heart rate |
| `SDNN` | HRV/RR | ms | Độ biến thiên tổng thể của RR |
| `RMSSD` | HRV/RR | ms | Biến thiên ngắn hạn giữa RR liên tiếp |
| `pNN50` | HRV/RR | % | Tỷ lệ cặp RR thay đổi hơn 50 ms |
| `LF/HF` | HRV/RR | ratio | Tỷ lệ phổ LF/HF của HRV |
| `mean_amplitude` | Morphology | raw ECG unit | Biên độ beat trung bình |
| `std_amplitude` | Morphology | raw ECG unit | Độ không ổn định biên độ beat |
| `mean_energy` | Morphology | raw ECG unit^2 | Năng lượng beat trung bình |
| `std_energy` | Morphology | raw ECG unit^2 | Độ không ổn định năng lượng beat |
| `mean_qrs_slope` | Morphology | raw ECG unit/sample | Độ dốc QRS trung bình |

## 5. Cách diễn giải trong báo cáo

Nên viết:

```text
Anomaly model sử dụng 5 đặc trưng HRV/RR để mô tả nhịp tim và 5 đặc trưng morphology để mô tả hình dạng beat ECG. Mục tiêu là phát hiện cửa sổ ECG lệch khỏi mẫu bình thường đã học, không phải chẩn đoán bệnh cụ thể.
```

Không nên viết:

```text
Anomaly model chẩn đoán bệnh tim.
```

Vì anomaly chỉ trả lời câu hỏi:

```text
Cửa sổ ECG này có khác mẫu normal hay không?
```

Nó không trả lời trực tiếp:

```text
Người dùng mắc bệnh gì?
```

## 6. Hạn chế

- Feature phụ thuộc vào chất lượng R-peak detection.
- Nếu ECG nhiễu hoặc dây đeo lỏng, RR và morphology có thể sai.
- LF/HF trên window ngắn không ổn định bằng phân tích HRV dài hạn.
- Morphology features đang là đặc trưng đơn giản, chưa thay thế được phân tích ECG lâm sàng.
- Model anomaly legacy chưa có evaluation accuracy/precision/recall đủ tin cậy.

## 7. Liên hệ với runtime hiện tại

Trong runtime production:

- `ANOMALY_ENABLED=1`: global anomaly legacy đang bật.
- `ANOMALY_CALIBRATION_ENABLED=0`: anomaly calibration cá nhân tắt mặc định.
- Nếu signal quality kém, anomaly trả `unknown` thay vì ép `normal` hoặc `abnormal`.
- Nếu anomaly trả `abnormal`, đây chỉ là screening signal và không được ưu tiên hơn rhythm/AFib/fall alert.

