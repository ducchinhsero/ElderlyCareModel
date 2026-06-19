# Đặt vấn đề và giải pháp đề xuất

Ngày cập nhật: 2026-06-10

Tài liệu này dùng cho phần mở đầu báo cáo/thuyết trình: nêu vấn đề thực tế, khoảng trống của các giải pháp hiện có, giải pháp dự án đề xuất và lý do vì sao nên sử dụng hệ thống này.

## 1. Đặt vấn đề

Xã hội đang bước vào giai đoạn già hóa dân số. Người cao tuổi thường có nguy cơ cao hơn về rối loạn nhịp tim, rung nhĩ, tăng/giảm nhịp tim bất thường, té ngã, suy giảm khả năng tự chăm sóc và các biến cố sức khỏe xảy ra đột ngột tại nhà. Trong nhiều trường hợp, người thân hoặc người chăm sóc không thể theo dõi liên tục 24/7, trong khi người cao tuổi lại có thể không nhận biết rõ triệu chứng hoặc không kịp gọi hỗ trợ khi có sự cố.

Một số vấn đề nổi bật:

- Rung nhĩ và các rối loạn nhịp có thể xuất hiện theo cơn, không phải lúc nào cũng xảy ra khi người bệnh đi khám.
- Té ngã ở người cao tuổi có thể gây chấn thương nặng nếu không được phát hiện và hỗ trợ kịp thời.
- Nhịp tim tăng/giảm bất thường cần được xem trong ngữ cảnh hoạt động, ví dụ đang nghỉ hay đang đi lại.
- Dữ liệu sức khỏe rời rạc theo từng lần đo thường không đủ để nhận biết xu hướng bất thường theo ngày hoặc theo tuần.
- Việc phụ thuộc hoàn toàn vào cloud hoặc điện thoại có thể làm chậm cảnh báo khi mất mạng, hết pin hoặc app bị tắt.

Vì vậy, cần một hệ thống có khả năng theo dõi tại nhà, xử lý dữ liệu gần người dùng, phát hiện sớm dấu hiệu bất thường và gửi cảnh báo cho người chăm sóc theo thời gian thực.

## 2. Hạn chế của một số cách tiếp cận hiện tại

### 2.1 Theo dõi thủ công

Gia đình thường hỏi thăm hoặc gọi điện để kiểm tra tình trạng người cao tuổi. Cách này đơn giản nhưng phụ thuộc vào cảm nhận chủ quan và không phát hiện được biến cố xảy ra giữa các lần kiểm tra.

Hạn chế:

- Không có dữ liệu liên tục.
- Không có cảnh báo tự động.
- Khó phát hiện các sự kiện ngắn như rối loạn nhịp theo cơn.

### 2.2 Đồng hồ thông minh phổ thông

Đồng hồ thông minh có thể đo nhịp tim, phát hiện té ngã hoặc đo ECG ngắn. Tuy nhiên, phần lớn hệ thống tập trung vào trải nghiệm cá nhân, không phải một pipeline theo dõi chuyên sâu cho người chăm sóc tại nhà.

Hạn chế:

- ECG thường là đo chủ động trong thời gian ngắn, không phải luồng ECG/RR chuyên sâu liên tục.
- Nhiều tính năng phụ thuộc vào điện thoại/cloud/ecosystem riêng.
- Dữ liệu raw và pipeline xử lý thường không mở để tùy biến nghiên cứu.
- Khó tích hợp mô hình riêng, baseline cá nhân và báo cáo theo yêu cầu đề tài.

### 2.3 Nút bấm khẩn cấp hoặc thiết bị SOS

Thiết bị SOS hữu ích khi người dùng còn đủ tỉnh táo để bấm nút. Tuy nhiên, nó không phân tích tín hiệu sinh lý và không hỗ trợ phát hiện sớm các dấu hiệu bất thường về nhịp tim.

Hạn chế:

- Phụ thuộc vào hành động chủ động của người dùng.
- Không có phân tích ECG/rhythm/HRV.
- Không tạo được lịch sử sức khỏe có cấu trúc để xem lại.

### 2.4 Hệ thống chỉ dùng cloud

Một số hệ thống gửi dữ liệu lên cloud rồi mới xử lý. Cách này thuận tiện cho quản lý tập trung nhưng có rủi ro khi mạng không ổn định.

Hạn chế:

- Mất Internet có thể làm chậm hoặc mất cảnh báo.
- Gửi dữ liệu thô liên tục lên cloud tốn băng thông và tăng rủi ro riêng tư.
- Thiết bị tại nhà không tự chủ khi cloud không truy cập được.

## 3. Giải pháp đề xuất của dự án

Dự án đề xuất hệ thống **Elderly Care Edge AI**: một hệ thống theo dõi sức khỏe người cao tuổi tại nhà bằng ECG/ACC từ Polar H10, xử lý tại Raspberry Pi, cảnh báo realtime cho ứng dụng và lưu trữ dữ liệu để phân tích dài hạn.

Thành phần chính:

- **Polar H10**: thu ECG/RR và gia tốc ACC từ thiết bị đeo ngực.
- **Raspberry Pi Edge AI**: nhận dữ liệu, xử lý tín hiệu, chạy model/rule, lưu cục bộ và phát cảnh báo.
- **FastAPI backend**: cung cấp API, WebSocket, dashboard local và endpoint cho app.
- **SQLite local storage**: lưu prediction, event, raw signal chunk và baseline ngay trên thiết bị.
- **MongoDB sync tùy chọn**: đồng bộ dữ liệu đã xử lý lên cloud khi có Internet.
- **Flutter app**: hiển thị realtime, cảnh báo, lịch sử, báo cáo sức khỏe và hướng dẫn cấu hình Wi-Fi/baseline.

Luồng xử lý tổng quát:

```text
Polar H10 ECG/ACC
-> Raspberry Pi Edge AI
-> kiểm tra chất lượng tín hiệu
-> trích xuất ECG/RR/HRV/morphology/ACC features
-> rhythm/stress/ectopy/anomaly/fall inference
-> rule engine tổng hợp alert_level
-> lưu SQLite local
-> gửi realtime qua REST/WebSocket/MQTT
-> đồng bộ cloud khi có mạng
-> app người đeo/người giám sát hiển thị và cảnh báo
```

## 4. Hệ thống giải quyết vấn đề như thế nào?

### 4.1 Xử lý tại biên, cảnh báo nhanh hơn

Raspberry Pi xử lý dữ liệu ngay tại nhà. Khi phát hiện tín hiệu đáng chú ý, hệ thống có thể cập nhật dashboard/app và tạo event mà không cần chờ cloud xử lý. Điều này phù hợp với các tình huống cần phản ứng nhanh như nghi rối loạn nhịp, nhịp tim bất thường hoặc té ngã.

### 4.2 Vẫn hoạt động khi mất Internet

Hệ thống ưu tiên offline-first:

- ECG/ACC vẫn được thu.
- Kết quả vẫn được xử lý cục bộ.
- SQLite vẫn lưu dữ liệu.
- Khi có Internet trở lại, dữ liệu được sync bù lên MongoDB nếu cấu hình.

Điều này giúp hệ thống phù hợp hơn với môi trường gia đình, nơi Wi-Fi có thể không ổn định.

### 4.3 Theo dõi nhiều khía cạnh thay vì một chỉ số đơn lẻ

Hệ thống không chỉ đo nhịp tim. Pipeline hiện kết hợp:

- Heart rate.
- Rhythm status.
- AFib-like suspicion và AF episode/burden.
- PVC/PAC-like ectopy screening.
- Stress sinh lý từ RR/HRV.
- ECG anomaly screening.
- Signal quality.
- Activity context từ ACC.
- Fall candidate.
- Personal baseline 7 ngày.
- Daily/long-term health report.

Cách tiếp cận đa tín hiệu giúp giảm phụ thuộc vào một model duy nhất và hỗ trợ diễn giải kết quả tốt hơn.

### 4.4 Kiểm tra chất lượng tín hiệu trước khi dự đoán

ECG thực tế dễ bị nhiễu do dây đeo lỏng, da khô, vận động hoặc mất kết nối Bluetooth. Vì vậy hệ thống có signal quality gate:

- Nếu tín hiệu tốt hoặc chấp nhận được, model mới đưa ra kết quả.
- Nếu tín hiệu kém, hệ thống trả `unknown` và yêu cầu kiểm tra dây đeo.
- Điều này giúp tránh việc ép model dự đoán trên dữ liệu sai.

### 4.5 Cá nhân hóa theo người dùng

Mỗi người cao tuổi có mức nhịp tim, hoạt động và biến thiên sinh lý khác nhau. Hệ thống có baseline cá nhân 7 ngày để so sánh người dùng với chính họ thay vì chỉ dùng một ngưỡng chung cho mọi người.

Ví dụ:

- REST HR tăng so với baseline.
- AF suspicion ratio tăng so với baseline.
- PVC/PAC-like activity tăng so với baseline.
- Signal quality thường xuyên kém.

## 5. Lý do nên sử dụng hệ thống của dự án

### 5.1 Phù hợp bài toán chăm sóc người cao tuổi tại nhà

Hệ thống được thiết kế xoay quanh người cao tuổi và người chăm sóc, không chỉ là một demo đo ECG đơn lẻ. Các chức năng như cảnh báo realtime, lịch sử sự kiện, báo cáo sức khỏe, baseline cá nhân và fall/activity context đều phục vụ trực tiếp cho chăm sóc tại nhà.

### 5.2 Có dữ liệu ECG/RR thật từ thiết bị đeo ngực

Polar H10 là cảm biến đeo ngực, phù hợp hơn cho RR/HRV và ECG một chuyển đạo so với nhiều cảm biến cổ tay khi cần tín hiệu nhịp tim ổn định. Điều này giúp hệ thống có nền dữ liệu tốt hơn cho các bài toán rhythm, HRV và stress sinh lý.

### 5.3 Kiến trúc edge AI tăng tính ổn định

Việc xử lý tại Raspberry Pi giúp:

- Giảm độ trễ cảnh báo.
- Giảm phụ thuộc cloud.
- Lưu dữ liệu cục bộ khi mất mạng.
- Giảm nhu cầu gửi raw ECG liên tục lên Internet.
- Dễ triển khai trong gia đình hoặc phòng lab.

### 5.4 Có khả năng mở rộng nghiên cứu và sản phẩm

Hệ thống đã có cấu trúc module:

- `src/features`: trích xuất đặc trưng.
- `src/inference`: chạy model.
- `src/storage`: lưu trữ SQLite/MongoDB.
- `src/api`: API realtime.
- `src/services`: thu dữ liệu, monitor, collector.
- `docs`: tài liệu kỹ thuật và báo cáo.

Cấu trúc này giúp dễ tích hợp thêm model stress, model bệnh lý dài hạn, dashboard cloud hoặc quy trình calibration mới.

### 5.5 Có cơ chế lưu trữ và truy vết

Kết quả không chỉ hiển thị một lần rồi mất. Hệ thống lưu:

- Prediction.
- Event timeline.
- Risk summary.
- Session summary.
- Raw ECG/ACC chunks.
- Personal baseline.

Điều này giúp xem lại lịch sử và phân tích xu hướng, thay vì chỉ phản ứng với từng thời điểm rời rạc.

### 5.6 Minh bạch về độ tin cậy

Hệ thống không che giấu giới hạn. Output được thiết kế theo hướng:

- `normal`
- `possible/suspicion`
- `unknown`
- `poor signal`
- `screening risk`

Cách đặt tên này phù hợp với bản chất nghiên cứu/sàng lọc và tránh tuyên bố quá mức.

## 6. Giá trị thực tế

### 6.1 Với người cao tuổi

- Được theo dõi liên tục hơn mà không phải thao tác nhiều.
- Có thể nhận hỗ trợ sớm hơn khi có dấu hiệu bất thường.
- Không cần tự hiểu các chỉ số kỹ thuật phức tạp.

### 6.2 Với người chăm sóc

- Xem được trạng thái realtime.
- Nhận cảnh báo khi có sự kiện đáng chú ý.
- Xem lịch sử, báo cáo và xu hướng theo ngày/tuần.
- Có thêm dữ liệu khách quan khi trao đổi với bác sĩ.

### 6.3 Với bác sĩ hoặc nhân viên y tế

- Có dữ liệu lịch sử có cấu trúc.
- Có event timeline để biết thời điểm nghi ngờ bất thường.
- Có thể xem thêm ECG raw/summary nếu cần phân tích sâu.
- Tuy nhiên, kết quả vẫn cần được xác nhận bằng phương pháp y khoa chuẩn.

### 6.4 Với nhóm phát triển/nghiên cứu

- Có nền tảng thu thập dữ liệu thực tế.
- Có pipeline huấn luyện/evaluate model.
- Có cơ chế deploy Raspberry Pi production-like.
- Có tài liệu để bàn giao và mở rộng.

## 7. Điểm khác biệt chính

| Tiêu chí | Cách thông thường | Hệ thống dự án |
|---|---|---|
| Dữ liệu | Đo rời rạc hoặc phụ thuộc thiết bị đóng | ECG/RR/ACC từ Polar H10, có raw/history |
| Xử lý | Cloud/app là chính | Edge AI trên Raspberry Pi |
| Mất mạng | Có thể gián đoạn | Vẫn lưu và xử lý local |
| Cảnh báo | Thường theo một tín hiệu | Kết hợp rhythm, HR, signal quality, ACC, fall, risk |
| Cá nhân hóa | Ít hoặc không rõ | Baseline cá nhân 7 ngày |
| Mở rộng nghiên cứu | Hạn chế | Code/module/dataset pipeline có thể mở rộng |
| Minh bạch | Phụ thuộc nhà sản xuất | Có artifact, metrics, docs và source code |

## 8. Phạm vi và giới hạn cần nói rõ

Hệ thống hiện là công cụ hỗ trợ theo dõi, sàng lọc và cảnh báo sớm. Không nên trình bày là thiết bị chẩn đoán bệnh độc lập.

Các giới hạn chính:

- ECG một chuyển đạo không thay thế ECG 12 chuyển đạo.
- Model rhythm/AFib vẫn có khả năng bỏ sót hoặc báo sai.
- Stress chỉ dùng ECG/RR, thiếu các modal như EDA/RESP/TEMP.
- PVC/PAC model còn yếu ở PAC và mixed ectopic.
- Anomaly legacy chưa có accuracy hợp lệ để công bố.
- Fall detection hiện là rule-based, cần validation thêm bằng dữ liệu té ngã có nhãn.
- Trước khi thương mại hóa y tế cần validation lâm sàng, bảo mật, hướng dẫn sử dụng, quy trình hỗ trợ và xem xét pháp lý.

## 9. Kết luận

Dự án có ý nghĩa vì giải quyết một nhu cầu thực tế: theo dõi sức khỏe người cao tuổi tại nhà một cách chủ động hơn, không chỉ dựa vào gọi điện thủ công, đồng hồ thông minh hoặc nút SOS. Bằng cách kết hợp Polar H10, Raspberry Pi Edge AI, lưu trữ cục bộ, cảnh báo realtime và báo cáo sức khỏe, hệ thống tạo ra một nền tảng có thể mở rộng từ prototype nghiên cứu sang pilot thực tế.

Lý do nên sử dụng hệ thống này không nằm ở việc thay thế bác sĩ, mà ở việc:

- phát hiện sớm dấu hiệu cần theo dõi,
- phản ứng nhanh hơn với biến cố,
- tạo lịch sử sức khỏe có cấu trúc,
- hỗ trợ người chăm sóc ra quyết định tốt hơn,
- và cung cấp nền tảng kỹ thuật để phát triển các model y sinh chính xác hơn trong tương lai.

