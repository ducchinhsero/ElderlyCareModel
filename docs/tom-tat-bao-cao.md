# Tóm tắt báo cáo hệ thống Elderly Care ECG

Ngày tổng hợp: 2026-05-22

## Mục tiêu

Dự án xây dựng hệ thống Edge AI theo dõi sức khỏe người cao tuổi bằng ECG từ Polar H10 và ngữ cảnh vận động ACC. Dữ liệu được xử lý tại thiết bị biên hoặc gateway cục bộ: tiền xử lý, trích xuất đặc trưng, chạy model, tính rủi ro và phát cảnh báo ngay tại thời điểm xảy ra bất thường. Sau đó, dữ liệu đã xử lý được gửi lên cloud để ứng dụng điện thoại của người chăm sóc/bác sĩ nhận thông báo và xem lịch sử. Đây là công cụ hỗ trợ sàng lọc/cảnh báo, chưa phải thiết bị chẩn đoán y khoa độc lập.

## Kiến trúc chính

```text
ECG/ACC input
-> edge device/gateway
-> local preprocessing 130 Hz, window 30s
-> signal quality
-> ECG/HRV/rhythm features
-> local rhythm model + stress model + PVC/PAC ectopy model
-> global anomaly legacy model with signal-quality gate
-> AF episode tracker + ACC activity/fall rules
-> immediate local alert + risk engine
-> local FastAPI dashboard + SQLite/CSV/JSONL
-> cloud sync of processed data
-> mobile app for caregiver/doctor
```

## Chức năng hiện có

- Nhận ECG qua `POST /ingest-ecg` hoặc Polar H10 BLE.
- Đánh giá chất lượng ECG.
- Ước lượng nhịp tim từ RR interval.
- Phân loại rhythm: `normal`, `possible_afib`, `other_rhythm`, `noise`.
- Tính xác suất AFib, theo dõi AF episode và AF burden.
- Dự đoán stress nhị phân: `non_stress`, `stress`, `unknown`.
- Anomaly ECG legacy chạy lại ở dạng global model; calibration cá nhân tắt mặc định để tránh nhiễu từ baseline chưa ổn định.
- Phân loại hoạt động ACC: `REST`, `SLOW_WALK`, `WALK`, `ACTIVE`.
- Phát hiện ngã rule-based: impact, free-fall, post-still.
- Hiệu chỉnh personal baseline lũy tiến tối đa 7 ngày cho từng người dùng; so sánh HR, REST HR, AF suspicion, anomaly và PVC/PAC với mức nền cá nhân.
- Sinh cảnh báo tổng hợp ngay tại thiết bị/gateway: `normal`, `medium`, `high`, `critical`, `unknown`.
- Lưu dữ liệu cục bộ và xem dashboard tại `/dashboard`.
- Đồng bộ prediction metadata, events, session summary và risk summary lên cloud để ứng dụng điện thoại nhận thông báo.

## File quan trọng

- `src/api/pipeline.py`: FastAPI, dashboard, BLE, hàm `predict_ecg`, alert tổng hợp.
- `src/preprocessing.py`: resample, normalize, chia cửa sổ, map label.
- `src/features/ecg_features.py`: R-peak, RR, HRV, signal quality, morphology.
- `src/features/rhythm_features.py`: 41 feature cho rhythm model.
- `src/features/acc_features.py`: parse ACC, activity, fall, HR context.
- `src/inference/rhythm_inference.py`: load và chạy rhythm model.
- `src/inference/af_episode_tracker.py`: theo dõi cơn AF và AF burden.
- `src/training/train_rhythm_features.py`: train rhythm model.
- `src/training/evaluate_long_term_afdb.py`: đánh giá AFDB và tạo decision config.
- `src/storage/ecg_storage.py`: SQLite, raw ECG/ACC CSV, risk/session/event summary.
- `src/calibration/personal_baseline.py`: progressive personal baseline 7 ngày từ SQLite predictions.
- `src/services/collect_real_data.py`: thu dữ liệu Polar H10 thực tế.

## Model và độ chính xác hiện tại

Rhythm model hiện tại:

- Model: `HistGradientBoostingClassifier`.
- Dataset train/eval: 11.751 cửa sổ, mỗi cửa sổ 30 giây, 130 Hz.
- Feature: 41 rhythm features.
- Multiclass accuracy: 73,21%.
- Macro F1: 70,62%.
- AFib precision: 75,74%.
- AFib recall: 63,58%.
- AFib F1: 69,13%.

AFDB long-term evaluation:

- Threshold deployment được chọn: 0,05, `probability_only`.
- AF detection F1: 80,52%.
- Precision: 88,95%.
- Recall: 73,56%.
- Episode sensitivity: 80,42%.
- Episode precision: 79,69%.
- AF burden absolute error: 6,90 điểm %.

Emotion/stress:

- GroupKFold mean accuracy: 61,61%.
- Best fold: 67,34%.
- Full dataset accuracy 93,68% không nên dùng làm kết luận triển khai vì dễ lạc quan.

Anomaly và fall:

- Anomaly legacy chưa có metrics đủ trong repo, nên không công bố accuracy.
- Fall detection là rule-based, chưa có dataset ngã có nhãn để tính độ chính xác.

## Kết luận năng lực

Hệ thống đã đủ tốt cho prototype nghiên cứu và demo vận hành Edge AI: có xử lý tại chỗ, API, dashboard, lưu trữ cục bộ, đồng bộ cloud, model artifacts, metric đánh giá và unit test. Phần rhythm/AFib là thành phần mạnh nhất, có khả năng hỗ trợ cảnh báo sớm ngay tại thời điểm đo. Tuy nhiên hệ thống chưa được validation lâm sàng trên người cao tuổi thực tế, nên không được tuyên bố là chẩn đoán chính xác bệnh.

## Ý nghĩa xã hội

Người cao tuổi ngày càng tăng và có rủi ro cao về rối loạn nhịp, đột quỵ, ngã và phụ thuộc chăm sóc. Theo WHO, đến năm 2050 thế giới dự kiến có khoảng 2,1 tỷ người từ 60 tuổi trở lên. CDC ghi nhận nguy cơ AFib tăng theo tuổi và AFib liên quan mạnh đến đột quỵ; CDC cũng ghi nhận hơn 1/4 người từ 65 tuổi trở lên bị ngã mỗi năm. Vì vậy, hệ thống Edge AI theo dõi từ xa bằng thiết bị đeo có giá trị thực tiễn: cảnh báo có thể phát ngay tại chỗ, còn dữ liệu sau xử lý vẫn được gửi lên cloud để người thân theo dõi qua điện thoại.

## Hướng phát triển

- Thu thêm dữ liệu người cao tuổi thật, có nhãn chuyên gia.
- Cải thiện rhythm model bằng deep learning hoặc hybrid feature + raw ECG.
- Phát triển fusion model ECG + RR + ACC.
- Validation riêng cho fall detection.
- Cá nhân hóa threshold theo từng người.
- Hoàn thiện cloud backend và ứng dụng điện thoại nhận dữ liệu đã xử lý từ thiết bị biên.
- Thêm bảo mật API, cảnh báo người nhà/bác sĩ, dashboard cloud.
- Tối ưu giảm false alert và tăng recall AFib.

## Tham khảo

- WHO Ageing and health: https://www.who.int/en/news-room/fact-sheets/detail/ageing-and-health
- CDC About Atrial Fibrillation: https://www.cdc.gov/heart-disease/about/atrial-fibrillation.html
- CDC Facts About Falls: https://www.cdc.gov/falls/data-research/facts-stats/
- PhysioNet/CinC Challenge 2017: https://physionet.org/content/challenge-2017/1.0.0/
- MIT-BIH AFDB: https://physionet.org/content/afdb/1.0.0/
- UCI WESAD: https://archive.ics.uci.edu/dataset/465/wesad
