// Build thesis Q&A document for Elderly Care project.
// Generates: ../DoAn_BoCauHoi_TraLoi.docx

const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
  BorderStyle, WidthType, ShadingType, PageBreak, PageNumber,
  TableOfContents, TabStopType, TabStopPosition,
} = require('docx');

// ---- Helpers ----
const F = "Times New Roman";

const p = (text, opts = {}) => new Paragraph({
  spacing: { after: 120, line: 360 },
  alignment: opts.align || AlignmentType.JUSTIFIED,
  ...opts.para,
  children: [new TextRun({ text, font: F, size: 24, ...opts.run })],
});

const pRich = (runs, opts = {}) => new Paragraph({
  spacing: { after: 120, line: 360 },
  alignment: opts.align || AlignmentType.JUSTIFIED,
  ...opts.para,
  children: runs.map(r => new TextRun({ font: F, size: 24, ...r })),
});

const h1 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_1,
  pageBreakBefore: true,
  spacing: { before: 240, after: 240 },
  children: [new TextRun({ text, font: F, size: 36, bold: true, color: "1F3864" })],
});

const h2 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_2,
  spacing: { before: 240, after: 160 },
  children: [new TextRun({ text, font: F, size: 30, bold: true, color: "2E5496" })],
});

const h3 = (text) => new Paragraph({
  heading: HeadingLevel.HEADING_3,
  spacing: { before: 200, after: 120 },
  children: [new TextRun({ text, font: F, size: 26, bold: true, color: "2E5496" })],
});

const q = (num, title) => new Paragraph({
  spacing: { before: 220, after: 100 },
  children: [
    new TextRun({ text: `Câu ${num}. `, font: F, size: 24, bold: true, color: "C00000" }),
    new TextRun({ text: title, font: F, size: 24, bold: true }),
  ],
});

const bullet = (text) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { after: 80, line: 320 },
  children: [new TextRun({ text, font: F, size: 24 })],
});

const note = (text) => new Paragraph({
  spacing: { before: 80, after: 120, line: 320 },
  alignment: AlignmentType.JUSTIFIED,
  shading: { fill: "FFF2CC", type: ShadingType.CLEAR },
  border: { left: { style: BorderStyle.SINGLE, size: 12, color: "BF8F00", space: 6 } },
  children: [new TextRun({ text: "Ghi chú: ", font: F, size: 22, bold: true, italics: true, color: "7F6000" }),
    new TextRun({ text, font: F, size: 22, italics: true, color: "7F6000" })],
});

const code = (text) => new Paragraph({
  spacing: { before: 80, after: 80 },
  shading: { fill: "F2F2F2", type: ShadingType.CLEAR },
  children: [new TextRun({ text, font: "Consolas", size: 20 })],
});

// Table helper
const border = { style: BorderStyle.SINGLE, size: 6, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };

const cell = (text, opts = {}) => new TableCell({
  borders,
  width: { size: opts.width || 4680, type: WidthType.DXA },
  shading: opts.header ? { fill: "DEEBF7", type: ShadingType.CLEAR } : undefined,
  margins: { top: 80, bottom: 80, left: 120, right: 120 },
  children: [new Paragraph({
    alignment: opts.center ? AlignmentType.CENTER : AlignmentType.LEFT,
    children: [new TextRun({ text, font: F, size: 22, bold: !!opts.header })],
  })],
});

const tableOf = (headers, rows, colWidths) => {
  const totalWidth = colWidths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: totalWidth, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({
        children: headers.map((h, i) => cell(h, { width: colWidths[i], header: true, center: true })),
      }),
      ...rows.map(r => new TableRow({
        children: r.map((c, i) => cell(c, { width: colWidths[i] })),
      })),
    ],
  });
};

// ---- Content sections ----

const cover = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 2400, after: 240 },
    children: [new TextRun({ text: "ĐỒ ÁN TỐT NGHIỆP", font: F, size: 48, bold: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 480 },
    children: [new TextRun({ text: "Hệ thống Theo dõi Sức khỏe Người Cao tuổi sử dụng Polar H10, Edge AI trên Raspberry Pi 5 và Ứng dụng Flutter", font: F, size: 32, bold: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
    children: [new TextRun({ text: "Bộ câu hỏi & câu trả lời tham chiếu", font: F, size: 28, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 480 },
    children: [new TextRun({ text: "(Dùng làm tài liệu nguồn cho người viết quyển đồ án)", font: F, size: 24, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 1200, after: 240 },
    children: [new TextRun({ text: `Cập nhật: ${new Date().toISOString().slice(0, 10)}`, font: F, size: 24 })] }),
  new Paragraph({ children: [new PageBreak()] }),
];

// CHƯƠNG 1
const chapter1 = [
  h1("CHƯƠNG 1 — TỔNG QUAN ĐỀ TÀI"),

  h2("1.1 Bối cảnh và tính cấp thiết"),

  q(1, "Số liệu già hóa dân số Việt Nam và thế giới"),
  p("Theo Tổng cục Thống kê Việt Nam (2023) và báo cáo World Population Prospects 2022 của Liên Hợp Quốc:"),
  bullet("Việt Nam: tỷ lệ người trên 60 tuổi đạt 12,8% (khoảng 12,5 triệu người) năm 2023, dự kiến đạt 18% (~20 triệu) vào năm 2030 và trên 25% (~28 triệu) vào năm 2050."),
  bullet("Thế giới: WHO ước tính số người trên 60 tuổi sẽ tăng từ 1 tỷ năm 2020 lên 1,4 tỷ năm 2030 và 2,1 tỷ năm 2050."),
  bullet("Việt Nam được xếp vào nhóm các quốc gia có tốc độ già hóa dân số nhanh nhất thế giới — chỉ mất 17-20 năm để chuyển từ giai đoạn “già hóa” (aging) sang “dân số già” (aged), nhanh hơn Nhật Bản, Hàn Quốc."),
  note("Khi viết, vui lòng cập nhật số liệu mới nhất từ niên giám thống kê và báo cáo WHO; trích dẫn nguồn theo chuẩn IEEE hoặc APA."),

  q(2, "Vấn đề sức khỏe phổ biến ở người cao tuổi liên quan đến tim mạch và hoạt động"),
  bullet("Rối loạn nhịp tim: rung nhĩ (atrial fibrillation – AFib) phổ biến nhất, tỷ lệ ~5-10% ở người trên 65 tuổi, ~17% trên 80 tuổi."),
  bullet("Bệnh động mạch vành, suy tim sung huyết, cao huyết áp."),
  bullet("Té ngã: 30% người trên 65 tuổi té ngã ít nhất 1 lần/năm; té ngã là nguyên nhân hàng đầu gây tử vong do chấn thương ở người cao tuổi."),
  bullet("Đột quỵ: AFib làm tăng nguy cơ đột quỵ lên 5 lần."),
  bullet("Bất động kéo dài (sarcopenia, deconditioning) khi không ra khỏi giường nhiều ngày làm tăng nguy cơ huyết khối, viêm phổi."),

  q(3, "Tại sao theo dõi ECG liên tục quan trọng với người cao tuổi"),
  p("ECG liên tục (continuous ECG monitoring) cho phép phát hiện các sự kiện bất thường mà ECG đơn lẻ (12-lead 10 giây tại phòng khám) bỏ sót:"),
  bullet("AFib paroxysmal (kịch phát): xuất hiện không định kỳ, có thể chỉ kéo dài vài phút, ECG khám định kỳ rất khó bắt được."),
  bullet("Tachycardia/bradycardia kịch phát: phát hiện khi nhịp tim bất thường tạm thời, kết hợp ngữ cảnh hoạt động (sleeping vs walking)."),
  bullet("Ngoại tâm thu thất/nhĩ (PVC/PAC): khi tần suất cao có thể là dấu hiệu sớm suy tim."),
  bullet("Đột tử do tim (Sudden Cardiac Death): 80% có cảnh báo trước qua loạn nhịp — phát hiện sớm có thể can thiệp."),
  bullet("Đánh giá AF burden (% thời gian AF trong ngày) — chỉ số quyết định việc dùng thuốc chống đông."),

  q(4, "Hạn chế của các phương pháp giám sát hiện tại"),
  bullet("Đến bệnh viện đo Holter 24h: phải đến cơ sở y tế, người già khó di chuyển; chi phí ~500.000-2.000.000 VND/lần; dữ liệu chỉ được phân tích offline sau khi gỡ thiết bị; không có cảnh báo realtime."),
  bullet("Smartwatch tiêu dùng (Apple Watch, Galaxy Watch...): dùng PPG (Photoplethysmography) thay vì ECG thật → đo nhịp tim được nhưng AFib detection có sensitivity ~70-85%, không đủ tin cậy cho người có bệnh nền; ECG mode chỉ chạy theo yêu cầu (on-demand), không liên tục."),
  bullet("KardiaMobile: chỉ đo ECG 30 giây mỗi lần khi người dùng đặt ngón tay; không passive monitoring; người cao tuổi khó nhớ thao tác."),
  bullet("Hầu hết giải pháp đều yêu cầu kết nối cloud — gặp vấn đề về privacy, độ trễ, phụ thuộc internet."),

  h2("1.2 Lý do chọn giải pháp"),

  q(5, "Tại sao chọn Polar H10 mà không tự chế thiết bị đeo"),
  bullet("Polar H10 sử dụng điện cực Ag/AgCl tiếp xúc trực tiếp ngực — tín hiệu ECG 1-lead (Lead I) chất lượng tương đương Holter y tế."),
  bullet("Đã được chứng nhận medical-grade CE Class IIa, được FDA chấp nhận trong nhiều nghiên cứu lâm sàng (Gilgen-Ammann 2019, Schaffarczyk 2022)."),
  bullet("Polar Open Access SDK cho phép truy cập ECG raw @130Hz qua BLE PMD (Polar Measurement Data) protocol — không cần reverse-engineer."),
  bullet("Tích hợp sẵn accelerometer 3-axis @25Hz để bổ sung HAR."),
  bullet("Pin trên 30 giờ liên tục thu ECG, sạc nhanh, kháng nước IPX7."),
  bullet("Giá thành ~2.500.000 VND — rẻ hơn nhiều so với thiết kế custom (cần MCU, ADC y tế, vỏ chống nước, chứng nhận an toàn điện tế bào)."),

  q(6, "Tại sao xử lý trên Raspberry Pi 5 mà không trên cloud hay điện thoại"),
  p("Đây là kiến trúc Edge AI — xử lý ngay tại biên (edge), nhiều ưu điểm so với cloud thuần:"),
  bullet("Độ trễ thấp: phát hiện AFib/té ngã trong <500ms, không cần round-trip internet."),
  bullet("Hoạt động khi mất mạng: pipeline tiếp tục chạy, dữ liệu lưu SQLite local, đồng bộ sau khi có mạng."),
  bullet("Bảo mật/riêng tư: dữ liệu y tế nhạy cảm xử lý cục bộ, chỉ metadata + alerts gửi cloud (không gửi raw ECG trừ khi cần)."),
  bullet("Pi 5 (4GB/8GB) có CPU ARM Cortex-A76 4-core 2.4GHz, đủ chạy 5 model AI (rhythm CNN/feature, ectopy, stress, anomaly) với latency <500ms/cycle 30s."),
  bullet("So với điện thoại: Pi 5 luôn online, không tốn pin điện thoại, không phụ thuộc người dùng có cầm phone bên cạnh."),
  bullet("So với cloud thuần: chi phí (cloud GPU đắt cho 24/7), tin cậy (mạng nhà người già không ổn định), khả năng scale (mỗi Pi tự xử lý)."),

  q(7, "Vai trò của cloud trong hệ thống"),
  bullet("Lưu trữ dài hạn: SQLite trên Pi chỉ giữ raw chunks 24-48h (do dung lượng SD card hạn chế), MongoDB Atlas lưu dữ liệu vĩnh viễn để phân tích trend dài hạn."),
  bullet("Đồng bộ đa thiết bị: caregiver có thể xem dữ liệu từ smartphone ở bất cứ đâu khi không cùng LAN với Pi."),
  bullet("Tích hợp với hệ thống bác sĩ: bác sĩ có thể truy cập lịch sử qua web dashboard nếu cần đánh giá."),
  bullet("Push notification qua FCM (Firebase Cloud Messaging) khi caregiver rời nhà — alert vẫn đến phone."),
  bullet("Phân tích population-level: nhiều bệnh nhân → phát hiện pattern, cải thiện ngưỡng cảnh báo theo dân số Việt Nam."),
  bullet("Sao lưu (backup) — nếu Pi hỏng/SD corrupt, dữ liệu vẫn còn trên cloud."),
  note("Kiến trúc của đồ án này coi cloud là kênh ARCHIVE phụ, KHÔNG nằm trên critical path của cảnh báo. Cảnh báo realtime đi qua MQTT local LAN."),

  h2("1.3 Mục tiêu cụ thể"),

  q(8, "Hệ thống phát hiện những bất thường nào về tim mạch"),
  p("Theo schema response của API (file src/api/pipeline.py):"),
  bullet("Rung nhĩ (AFib / possible_afib) — rhythm classifier 4 classes."),
  bullet("Nhịp nhanh (tachycardia) — HR > 100 bpm khi nghỉ, đã hiệu chỉnh theo activity (REST/WALK/ACTIVE)."),
  bullet("Nhịp chậm (bradycardia) — HR < 50 bpm khi không ngủ."),
  bullet("Ngoại tâm thu thất/nhĩ (PVC/PAC + mixed ectopic) — ectopy classifier 5 classes."),
  bullet("Loạn nhịp khác (other_rhythm) — bất thường không thuộc 3 loại trên."),
  bullet("Tín hiệu kém (noise / signal_quality=poor) — phòng false alarm."),
  bullet("Anomaly bất thường tổng quát (IsolationForest legacy) — kết hợp morphological + HRV features."),
  bullet("AF episode + AF burden % — đếm số phiên AF và % thời gian AF trong ngày (đánh giá theo chuẩn ESC)."),

  q(9, "Hệ thống nhận diện những hành vi/hoạt động nào từ dữ liệu gia tốc"),
  p("Theo src/features/acc_features.py — phân loại rule-based:"),
  bullet("REST — đứng yên, ngồi, nằm (vector magnitude std < 20 mG)."),
  bullet("SLOW_WALK — đi chậm, di chuyển nhẹ (20-80 mG)."),
  bullet("WALK — đi bộ bình thường (80-300 mG)."),
  bullet("ACTIVE — vận động mạnh, chạy, lên xuống cầu thang (≥300 mG)."),
  bullet("Fall candidate — chu kỳ free-fall → impact đột ngột (>2000 mG) → bất động sau đó."),
  bullet("Strong impact — va đập mạnh không phải té (>2800 mG)."),
  note("V1 dùng rule-based; lộ trình V2-V3 sẽ train fusion model ECG+ACC để giảm false positive khi HR tăng do vận động."),

  q(10, "Cảnh báo gửi đến đâu, theo mức độ ưu tiên nào"),
  pRich([
    { text: "Hệ thống có 4 kênh phân phối cảnh báo độc lập, mỗi cảnh báo có 4 mức: ", },
    { text: "normal / medium / high / critical", bold: true },
  ]),
  tableOf(
    ["Kênh", "Path", "Mức kích hoạt", "Latency"],
    [
      ["MQTT topic alert", "Pi → mosquitto local → app", "≥ medium (QoS=2, retain=true)", "<30ms LAN"],
      ["WebSocket /ws/vitals", "Pi → Flutter dashboard", "Tất cả mức (live stream)", "<100ms LAN"],
      ["HTTP webhook (optional)", "Pi → URL config", "Theo ALERT_WEBHOOK_LEVELS", "~200ms-2s"],
      ["FCM push (đề xuất V2)", "Pi → Firebase → phone OS", "≥ high khi caregiver xa nhà", "~1-3s qua internet"],
    ],
    [2200, 2800, 2800, 1560]
  ),
  p(""),
  pRich([
    { text: "Phân cấp ưu tiên: ", bold: true },
    { text: "critical (té ngã thật) → gọi điện tự động + push âm thanh; high (AFib episode) → push notification rung mạnh; medium (tachycardia trong nghỉ) → notification thường; normal → chỉ cập nhật dashboard." },
  ]),

  h2("1.4 Khảo sát công trình liên quan"),

  q(11, "Nghiên cứu sử dụng Polar H10 cho AFib / HRV / HAR"),
  bullet("Gilgen-Ammann et al. (2019, European Journal of Applied Physiology) — Polar H10 cho HR/HRV: validated với ECG y tế, sai số <1 bpm."),
  bullet("Schaffarczyk et al. (2022, Sensors MDPI) — Polar H10 cho HRV phân tích: RMSSD/SDNN tương đương 12-lead ECG."),
  bullet("Hinde et al. (2021, BMC Sports Science) — sử dụng Polar H10 trong rehabilitation context."),
  bullet("Plews et al. (2017, IJSPP) — Polar H10 cho training load monitoring qua HRV."),
  bullet("Nhiều bài về CinC Challenge 2017 (PhysioNet) — AFib detection 1-lead ECG, là dataset chính train rhythm model trong đồ án này."),
  note("Khi viết, cần đọc kỹ ít nhất 5-10 paper và trích dẫn theo IEEE format. Có thể tìm thêm qua Google Scholar với từ khoá “Polar H10 AFib detection”, “1-lead ECG arrhythmia classification deep learning”."),

  q(12, "So sánh sản phẩm thương mại tương tự"),
  tableOf(
    ["Sản phẩm", "Loại tín hiệu", "Liên tục?", "AFib detect", "Giá (VND)"],
    [
      ["KardiaMobile (Alivecor)", "ECG 1-lead 30s", "Không", "Có (on-demand)", "2.500.000"],
      ["Apple Watch S9", "PPG + ECG 30s", "PPG liên tục, ECG on-demand", "Có (PPG passive)", "~10.000.000"],
      ["Zio Patch (iRhythm)", "ECG 1-lead", "Có (14 ngày)", "Có, post-analysis", "Mỹ ~$300, VN không phân phối"],
      ["Holter 24h bệnh viện", "ECG 3-12 lead", "Có (1 ngày)", "Có, post-analysis", "500.000-2.000.000/lần"],
      ["Polar H10 + giải pháp đồ án", "ECG 1-lead 130Hz + ACC", "Có (24/7)", "Có (realtime AI)", "~2.500.000 + Pi 5 ~3.000.000"],
    ],
    [2200, 1800, 1800, 1800, 1760]
  ),
  p(""),
  pRich([
    { text: "Ưu điểm giải pháp đồ án: ", bold: true },
    { text: "(1) liên tục 24/7 + realtime alert ngay tại nhà, (2) edge AI không phụ thuộc cloud, (3) tích hợp ECG + ACC (HAR) trên cùng thiết bị, (4) chi phí 1 lần ~5.500.000 VND (rẻ hơn Apple Watch), (5) dữ liệu xuất file PDF chuẩn y tế cho bác sĩ. " },
  ]),
  pRich([
    { text: "Nhược điểm: ", bold: true },
    { text: "(1) dây đeo ngực cần làm ẩm strap, không thoải mái cho phụ nữ/người mảnh, (2) phụ thuộc Pi tại nhà — không di chuyển ra ngoài được, (3) Pi cần cấp nguồn liên tục." },
  ]),

  q(13, "Điểm mới / đóng góp của đề tài"),
  bullet("Tích hợp 5 module phân tích song song (rhythm, ectopy, stress, anomaly, signal quality) thay vì 1 model anomaly duy nhất như các đề tài trước."),
  bullet("Multi-tier alert delivery: MQTT local + WebSocket + Webhook + (FCM) — cảnh báo độc lập với MongoDB cloud."),
  bullet("Tự calibrate ngưỡng cá nhân qua 7-day guided baseline (REST/WALK/ACTIVE) — giảm false positive cho từng bệnh nhân."),
  bullet("AF burden estimation chuẩn ESC dựa trên AFDB Holter benchmark (sai số burden 6.9%)."),
  bullet("Hardening cho 24/7: SQLite WAL + busy_timeout, MongoDB bulk_write, BLE buffer cap, MQTT LWT — ổn định trên Pi."),
  bullet("Pipeline có khả năng training liên tục từ dữ liệu cá nhân (personal anomaly recalibration)."),

  h2("1.5 Sơ đồ và quy trình"),

  q(14, "Sơ đồ tổng thể hệ thống"),
  p("Luồng dữ liệu chính:"),
  code("[Polar H10]\n   │ BLE GATT (ECG @130Hz + ACC @25Hz)\n   ▼\n[Raspberry Pi 5] — Edge AI Server\n   │ FastAPI :8000\n   │ ├─ 5 model AI inference (rhythm/ectopy/stress/anomaly/quality)\n   │ ├─ SQLite WAL (raw chunks + predictions + events)\n   │ ├─ mosquitto MQTT broker :1883\n   │ └─ Background sync scheduler\n   │\n   ├─ MQTT (local LAN) ──► [Flutter app]\n   ├─ WebSocket /ws/vitals ──► [Browser dashboard]\n   └─ HTTPS (async) ──► [MongoDB Atlas cloud archive]\n                              │\n                              └─► [Caregiver app via internet]"),
  note("Đề nghị vẽ lại bằng draw.io / Lucidchart với 3 cột: Sensor — Edge — Consumer. Phân biệt rõ critical path (MQTT) và archive path (Mongo)."),

  q(15, "Quy trình thực hiện đề tài"),
  bullet("Giai đoạn 1 — Khảo sát: nghiên cứu Polar H10 SDK, BLE GATT protocol, các dataset chuẩn (CinC 2017, MITDB, WESAD, AFDB, NSTDB)."),
  bullet("Giai đoạn 2 — Thu thập + tiền xử lý dữ liệu: download datasets, build window 30s × 130Hz, augment NSTDB noise."),
  bullet("Giai đoạn 3 — Huấn luyện model: rhythm feature (HistGBM), ectopy, stress LOSO-CV, anomaly IsolationForest, evaluation trên AFDB long-term."),
  bullet("Giai đoạn 4 — Tuning thresholds: AFDB sweep tìm best probability threshold cho realtime."),
  bullet("Giai đoạn 5 — Triển khai trên Pi: setup OS, BLE pairing, systemd service, mosquitto broker, MQTT publisher integration."),
  bullet("Giai đoạn 6 — Xây Flutter app: dashboard realtime, alert center, history, baseline wizard, PDF report."),
  bullet("Giai đoạn 7 — Tích hợp cloud: MongoDB Atlas sync, FCM push notification (V2)."),
  bullet("Giai đoạn 8 — Thử nghiệm + đánh giá: soak test 6-24h, đo end-to-end latency, BLE reconnect rate, CPU/RAM."),
  bullet("Giai đoạn 9 — Viết báo cáo + bảo vệ."),
];

// ---- CHƯƠNG 2 ----
const chapter2 = [
  h1("CHƯƠNG 2 — CƠ SỞ CHUYÊN MÔN VỀ ECG VÀ NHẬN DIỆN HÀNH VI"),

  h2("2.1 Về ECG và sinh hiệu"),

  q(16, "Tín hiệu ECG là gì, đặc trưng các sóng P-QRS-T"),
  p("ECG (Electrocardiogram) là tín hiệu điện sinh học ghi lại hoạt động khử cực và tái cực của cơ tim, đo qua điện cực đặt trên da. Mỗi chu kỳ tim gồm 5 sóng đặc trưng:"),
  bullet("Sóng P: khử cực 2 tâm nhĩ, biên độ <2.5mV, kéo dài <120ms — bất thường gợi ý vấn đề nhĩ (mất P trong AFib, đảo trong nhịp lạc chỗ)."),
  bullet("Phức bộ QRS: khử cực 2 tâm thất, biên độ 5-15mV, kéo dài <120ms — QRS dãn rộng (>120ms) gợi ý block nhánh, PVC; QRS hẹp = nhịp xuất phát trên thất."),
  bullet("Sóng T: tái cực tâm thất, cùng hướng QRS — đảo ngược T gợi ý thiếu máu cơ tim."),
  bullet("Khoảng PR: P → đầu QRS, bình thường 120-200ms — kéo dài = block AV độ 1."),
  bullet("Khoảng QT: đầu Q → cuối T, đã hiệu chỉnh QTc — QTc kéo dài (>450ms nam, >470ms nữ) tăng nguy cơ Torsades de Pointes."),
  bullet("Khoảng RR (R-R interval): giữa 2 sóng R liên tiếp — đảo nghịch tần số tim (HR = 60/RR_seconds)."),

  q(17, "Các loại loạn nhịp tim phổ biến và đặc trưng nhận diện trên ECG"),
  tableOf(
    ["Loạn nhịp", "Đặc trưng ECG", "HR", "Nguy cơ"],
    [
      ["Rung nhĩ (AFib)", "Mất sóng P, RR không đều tuyệt đối, đường isoelectric có sóng f", "60-180", "Đột quỵ ×5, suy tim"],
      ["Cuồng nhĩ (Flutter)", "Sóng F răng cưa F-wave (~300/phút)", "150 (block 2:1)", "Tương tự AFib"],
      ["PVC (ngoại tâm thu thất)", "QRS rộng đột ngột, không có P trước, theo sau là pause bù", "Biến thiên", "Nguy hiểm nếu >10/phút"],
      ["PAC (ngoại tâm thu nhĩ)", "QRS hẹp đến sớm, có P bất thường trước", "Biến thiên", "Tiền đề AFib"],
      ["Tachycardia (xoang nhanh)", "Nhịp xoang đều, mỗi P có QRS", ">100", "Stress, sốt, bệnh lý"],
      ["Bradycardia (xoang chậm)", "Nhịp xoang đều, mỗi P có QRS", "<60", "Suy nút xoang, dùng thuốc"],
      ["Block AV độ 3", "P và QRS không liên quan, HR thất rất chậm", "30-40", "Cần máy tạo nhịp"],
    ],
    [2000, 3000, 1300, 2840]
  ),

  q(18, "HRV và các chỉ số RMSSD, SDNN, LF/HF"),
  p("HRV (Heart Rate Variability) đo độ biến thiên thời gian giữa các nhịp tim (RR intervals). HRV phản ánh hoạt động hệ thần kinh tự chủ (Autonomic Nervous System – ANS):"),
  bullet("RMSSD (Root Mean Square of Successive Differences): căn quân phương của hiệu RR liền kề. Phản ánh hoạt động parasympathetic (vagal tone). Bình thường 20-50ms; thấp gợi ý stress mạn, bệnh lý."),
  bullet("SDNN (Standard Deviation of NN intervals): độ lệch chuẩn của RR. Phản ánh tổng thể HRV. <50ms = nguy cơ tim cao."),
  bullet("pNN50: % số RR liền kề chênh nhau >50ms — tương tự RMSSD."),
  bullet("LF (Low Frequency, 0.04-0.15Hz): kết hợp sympathetic + parasympathetic."),
  bullet("HF (High Frequency, 0.15-0.4Hz): chủ yếu parasympathetic (vagal)."),
  bullet("LF/HF ratio: cân bằng symapathetic/parasympathetic. >2 = stress dominance; <0.5 = vagal dominance."),
  pRich([
    { text: "Ý nghĩa lâm sàng: ", bold: true },
    { text: "HRV thấp dự đoán nguy cơ tử vong do tim mạch tăng 2-3 lần. HRV được dùng đánh giá phục hồi sau biến cố tim, hiệu quả điều trị, mức độ stress mạn." },
  ]),

  q(19, "Ngưỡng nhịp tim bình thường/bất thường cho người cao tuổi"),
  p("Chuẩn AHA (American Heart Association) và ESC (European Society of Cardiology):"),
  bullet("Nghỉ ngơi (resting): 60-100 bpm bình thường. Trên 60 tuổi có thể chấp nhận tới 50 bpm khi thể lực tốt."),
  bullet("Bradycardia: <60 bpm khi thức (kèm triệu chứng) hoặc <50 bpm khi ngủ."),
  bullet("Tachycardia: >100 bpm khi nghỉ, hiệu chỉnh theo activity (đi bộ 100-130 vẫn bình thường)."),
  bullet("HR target sau hoạt động vừa = (220 - tuổi) × 50-70%."),
  bullet("HR max theo tuổi = 220 - tuổi (ước lượng)."),
  bullet("Theo Bộ Y tế Việt Nam (Quyết định 5332/QĐ-BYT 2020 về hướng dẫn chẩn đoán suy tim), ngưỡng nhịp tim đánh giá tương tự ESC."),

  q(20, "Polar H10 đo ECG bằng phương pháp nào, độ chính xác"),
  p("Polar H10 sử dụng phương pháp đo ECG single-lead bằng:"),
  bullet("2 điện cực Ag/AgCl tích hợp trong dây đeo ngực, đặt vùng V2-V4 tương đương Lead I trong 12-lead ECG."),
  bullet("Sample rate: 130 Hz (ECG raw qua Polar PMD service)."),
  bullet("ADC độ phân giải tương đương 14-16 bit, dải đo ±5mV."),
  bullet("Lọc nhiễu phần cứng + tín hiệu được Polar firmware tiền xử lý trước khi phát qua BLE."),
  pRich([
    { text: "Độ chính xác đã kiểm chứng: ", bold: true },
    { text: "Gilgen-Ammann et al. (2019) so sánh Polar H10 với ECG y tế Schiller AT-104, sai số RR < 1ms ở 99.9% nhịp; Schaffarczyk et al. (2022) confirm HRV (RMSSD, SDNN) có ICC > 0.99 với ECG chuẩn. Polar H10 được dùng trong các thử nghiệm lâm sàng và rehabilitation programs." },
  ]),

  h2("2.2 Về nhận diện hoạt động (HAR – Human Activity Recognition)"),

  q(21, "Phân loại các hoạt động sinh hoạt hàng ngày (ADL)"),
  p("ADL (Activities of Daily Living) cần nhận diện cho người cao tuổi:"),
  bullet("Tĩnh: nằm, ngồi, đứng yên — REST trong hệ thống đồ án."),
  bullet("Di chuyển nhẹ: đi chậm, đi trong nhà — SLOW_WALK."),
  bullet("Di chuyển trung bình: đi bộ thông thường, leo cầu thang — WALK."),
  bullet("Vận động mạnh: tập thể dục, chạy, làm việc nhà nặng — ACTIVE."),
  bullet("Sự kiện đột ngột: té ngã (fall), va đập (impact)."),
  bullet("Bất động kéo dài: nằm/ngồi >2-4h không di chuyển — dấu hiệu bệnh lý hoặc bất tỉnh."),

  q(22, "Đặc trưng tín hiệu gia tốc khi đi/đứng/ngồi/nằm/té ngã"),
  p("Sử dụng Signal Vector Magnitude (SVM) = √(x² + y² + z²) làm chỉ số tổng hợp:"),
  bullet("Đứng yên/ngồi: SVM ≈ 1g (9.81 m/s²), std rất thấp <10 mG."),
  bullet("Nằm: SVM ≈ 1g nhưng hướng vector khác (z gần 0, x hoặc y ≈ 1g)."),
  bullet("Đi chậm: SVM dao động 0.8-1.2g, std 20-80 mG, tần số bước ~1.5-2 Hz."),
  bullet("Đi bộ: SVM dao động 0.5-1.5g, std 80-300 mG, tần số bước ~2 Hz."),
  bullet("Chạy/vận động mạnh: SVM dao động 0.3-2.5g, std >300 mG, tần số 2.5-3 Hz."),
  bullet("Té ngã: 3 giai đoạn — (1) free-fall: SVM ≈ 0 trong 200-400ms; (2) impact: SVM >2g đột ngột; (3) post-fall stillness: SVM ≈ 1g, std thấp, kéo dài."),
  note("Khi viết, đính kèm biểu đồ 4 trục (x, y, z, SVM) minh họa từng hoạt động — có thể chụp từ dữ liệu thu thực Polar H10."),

  q(23, "Định nghĩa té ngã trên tín hiệu gia tốc"),
  p("Té ngã ở người cao tuổi được định nghĩa về mặt tín hiệu thông qua chuỗi 3 sự kiện liên tiếp:"),
  bullet("Free-fall phase: SVM gần 0 (mất trọng lực) trong khoảng 100-500ms tùy độ cao."),
  bullet("Impact phase: SVM tăng đột ngột vượt ngưỡng (>2g, thường 2.5-3.5g) trong vài chục ms."),
  bullet("Post-fall stillness: SVM ổn định khoảng 1g, std rất thấp, kéo dài >5 giây — chỉ ra người không tự đứng dậy."),
  p("Trong code đồ án (src/features/acc_features.py):"),
  bullet("FALL_IMPACT_THRESHOLD_MG = 2000 mG — kích hoạt fall_candidate."),
  bullet("FALL_STRONG_IMPACT_MG = 2800 mG — strong_fall, ưu tiên alert critical."),

  q(24, "Khác biệt giữa té ngã thật và hoạt động giống té"),
  bullet("Ngồi xuống ghế nhanh: có impact ~1.5-2g nhưng KHÔNG có free-fall trước; sau đó người vẫn cử động."),
  bullet("Đặt thiết bị xuống bàn: impact lớn nhưng KHÔNG có free-fall + KHÔNG có post-stillness của người."),
  bullet("Nhảy: có free-fall và impact, NHƯNG post-impact người tiếp tục di chuyển."),
  bullet("Té xuống đệm: impact thấp hơn ngưỡng do đệm hấp thụ → false negative — cần ngưỡng adaptive."),
  pRich([
    { text: "Thách thức: ", bold: true },
    { text: "Phân biệt 3 giai đoạn (pre + impact + post) là cần thiết. Đề tài V1 dùng rule-based; V2-V3 sẽ train CNN/LSTM trên dataset SisFall, UMAFall để giảm false positive xuống <5%." },
  ]),

  h2("2.3 Về các bộ dữ liệu"),

  q(25, "Các tập dữ liệu công khai dùng trong đồ án"),
  pRich([{ text: "Cho ECG:", bold: true }]),
  bullet("PhysioNet/CinC Challenge 2017: 8.528 ECG single-lead, 4 classes (normal/AF/other/noise) — 30s windows @ 300Hz, là dataset chính train rhythm classifier."),
  bullet("MIT-BIH Arrhythmia Database (MITDB): 48 records 30 phút, 16 loại nhịp, dùng train ectopy classifier (PVC/PAC)."),
  bullet("MIT-BIH Atrial Fibrillation Database (AFDB): 25 records 10 giờ Holter, dùng đánh giá long-term AF detection."),
  bullet("MIT-BIH Noise Stress Test Database (NSTDB): tín hiệu nhiễu BW (baseline wander), EM (electrode motion), MA (muscle artifact) để augment rhythm dataset."),
  bullet("PTB-XL Database: ECG 12-lead, dùng anomaly legacy."),
  pRich([{ text: "Cho HRV/Stress:", bold: true }]),
  bullet("WESAD (Wearable Stress and Affect Detection): 15 subjects, ECG@700Hz + acc + EDA, label stress/baseline/amusement — train stress classifier với LOSO-CV."),
  pRich([{ text: "Cho HAR (chuẩn bị V2):", bold: true }]),
  bullet("UCI HAR Dataset: 30 subjects, 6 activities, smartphone accelerometer."),
  bullet("MobiAct, SisFall, UMAFall: chứa scenario té ngã có nhãn — dùng train fall classifier sau."),

  q(26, "Cách thức tự thu thập dữ liệu bổ sung"),
  bullet("Số người tham gia: dự kiến 5-10 người (gia đình, bạn bè đồng ý) tuổi 25-75."),
  bullet("Kịch bản: REST 10 phút × 3 lần; WALK 5 phút × 3 lần; ACTIVE 3 phút × 2 lần; nghỉ giữa các session."),
  bullet("Mỗi người tổng: ~60 phút data x 5-10 người = 5-10 giờ."),
  bullet("Môi trường: trong nhà, sàn cứng, nhiệt độ phòng."),
  bullet("Ghi nhãn: timestamp + activity label bởi người giám sát; mỗi session lưu file CSV riêng."),
  bullet("Cấu trúc lưu: dataset/collected/<subject_id>/<session>/<timestamp>.csv với cột sample_index, time, x, y, z, ecg_uv."),

  q(27, "Đạo đức và sự đồng thuận khi thu dữ liệu trên người"),
  bullet("Informed Consent (đồng thuận có hiểu biết): mỗi người tham gia ký giấy đồng ý, giải thích rõ mục đích, cách dùng dữ liệu, quyền rút lui."),
  bullet("Anonymization: subject_id thay bằng mã số (S01, S02...) — không lưu tên, CMND, địa chỉ trong dataset."),
  bullet("Tuân thủ Luật Khám chữa bệnh VN 2009 (Điều 8 về bảo mật thông tin) và Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân."),
  bullet("Đối với người cao tuổi có suy giảm nhận thức: cần đồng thuận từ người giám hộ hợp pháp."),
  bullet("Dữ liệu chỉ lưu trên máy local + Pi, KHÔNG upload public, KHÔNG bán."),
  bullet("Nếu cần publish paper với dữ liệu thu, phải xin phê duyệt Ethics Committee tại trường."),

  h2("2.4 Tiêu chí đánh giá"),

  q(28, "Metrics đánh giá mô hình"),
  tableOf(
    ["Metric", "Công thức", "Ý nghĩa", "Quan trọng cho..."],
    [
      ["Accuracy", "(TP+TN)/(TP+TN+FP+FN)", "Tỷ lệ đúng tổng thể", "Dataset cân bằng"],
      ["Precision", "TP/(TP+FP)", "Cảnh báo đúng / tổng cảnh báo", "Giảm false alarm"],
      ["Recall / Sensitivity", "TP/(TP+FN)", "Bắt đúng / tổng case thật", "AFib, té ngã"],
      ["Specificity", "TN/(TN+FP)", "Loại bỏ đúng / tổng normal", "Tránh báo nhầm"],
      ["F1-score", "2·P·R/(P+R)", "Trung bình điều hoà P và R", "Dataset imbalance"],
      ["AUC-ROC", "Diện tích dưới ROC", "Khả năng phân biệt", "Threshold-independent"],
    ],
    [1800, 2300, 2700, 2360]
  ),
  p(""),
  pRich([
    { text: "Quan trọng nhất cho té ngã/AFib: ", bold: true },
    { text: "Recall (Sensitivity) — vì bỏ sót 1 ca AFib hoặc té ngã có thể đe dọa tính mạng. Tuy nhiên Precision không được quá thấp (gây false alarm fatigue). Mục tiêu: Recall ≥ 0.85, Precision ≥ 0.70. Thực tế đồ án: AFib F1=0.81 (P=0.90, R=0.74) trên AFDB long-term." },
  ]),

  q(29, "Metrics đánh giá hệ thống"),
  bullet("Độ trễ end-to-end (latency): từ sự kiện bất thường → notification app. Mục tiêu <2s qua MQTT LAN, <5s qua FCM cloud."),
  bullet("Uptime: thời gian hệ thống hoạt động liên tục / tổng thời gian. Mục tiêu 99% (≤7.3 giờ downtime/tháng)."),
  bullet("BLE reconnect rate: số lần BLE rớt/giờ. Mục tiêu <1 lần/giờ trong điều kiện đeo bình thường."),
  bullet("Memory growth rate: RAM sau 24h chạy liên tục không vượt 800MB (Pi 4 4GB)."),
  bullet("CPU% trung bình: <50% (1 core) khi đang inference."),
  bullet("Disk growth rate: ~50MB/ngày SQLite raw (nếu giữ raw chunks)."),
  bullet("MongoDB sync success rate: % cycle sync thành công. Mục tiêu >95%."),
];

// CHƯƠNG 3
const chapter3 = [
  h1("CHƯƠNG 3 — CƠ SỞ LÝ THUYẾT"),

  h2("3.1 Polar H10 — thiết bị thu thập"),

  q(30, "Thông số kỹ thuật của Polar H10"),
  tableOf(
    ["Thông số", "Giá trị"],
    [
      ["Tần số lấy mẫu ECG", "130 Hz (qua Polar PMD service)"],
      ["Accelerometer", "25 Hz, 3-axis, ±8g range"],
      ["Heart rate range", "30-240 bpm"],
      ["Pin", "CR2025 3V, 30+ giờ liên tục"],
      ["Pin life ECG mode", "30 giờ continuous"],
      ["IP rating", "IPX7 (chống nước 1m/30 phút)"],
      ["Kích thước module", "65 × 34 × 10 mm, 21g"],
      ["Dây đeo", "Pro Strap polyester, có thể giặt máy"],
      ["Kết nối", "BLE 4.0+, ANT+, GymLink"],
      ["Memory", "Lưu được 1 session offline"],
      ["Nhiệt độ hoạt động", "-10°C đến +50°C"],
      ["Chứng nhận", "CE Class IIa medical-grade"],
    ],
    [3500, 5860]
  ),

  q(31, "Polar H10 hỗ trợ truyền những loại dữ liệu nào qua BLE"),
  bullet("Heart Rate Service (chuẩn BLE 16-bit UUID 0x180D): heart rate hiện tại (BPM) + RR interval (1024 Hz resolution)."),
  bullet("Polar PMD Service (custom UUID FB005C80-...): cho phép truy cập raw signal."),
  bullet("PMD ECG: 130 Hz, 24-bit signed integer per sample (raw ADC value)."),
  bullet("PMD Accelerometer: 25/50/100/200 Hz, 16/24-bit per axis."),
  bullet("PMD PPG / PP-interval: nếu thiết bị tích hợp PPG."),
  bullet("Battery Service (UUID 0x180F): % pin còn lại."),
  bullet("Device Information (UUID 0x180A): firmware version, manufacturer."),

  q(32, "Polar SDK và Polar BLE SDK"),
  bullet("Polar Open Access SDK (https://github.com/polarofficial/polar-ble-sdk): SDK chính thức của Polar, hỗ trợ iOS/Android/cross-platform."),
  bullet("Trong đồ án này, không dùng SDK Polar trực tiếp mà thay bằng thư viện Python bleak để giao tiếp BLE chuẩn (Polar PMD protocol đã được document trong SDK)."),
  bullet("Polar Measurement Data (PMD) Control Point (UUID FB005C81-...): gửi command để start/stop stream."),
  bullet("PMD Data (UUID FB005C82-...): characteristic notify để nhận data stream."),
  bullet("Command để start ECG: 0x02 0x00 0x00 0x01 0x82 0x00 0x01 0x01 0x0E 0x00 (130Hz, 14-bit)."),

  q(33, "Hạn chế của Polar H10"),
  bullet("Chỉ 1 lead — không thể chẩn đoán đầy đủ như 12-lead ECG; ST elevation không phát hiện chính xác."),
  bullet("Đeo ngực không thoải mái cho phụ nữ, người mảnh, hoặc người có vấn đề da."),
  bullet("Cần làm ẩm strap trước khi đeo — strap khô → Polar OFF, không advertise BLE."),
  bullet("Pin CR2025 không sạc lại, phải thay sau 30 giờ — cần dự trữ pin sẵn."),
  bullet("Chỉ kết nối 1 thiết bị tại 1 thời điểm — không thể vừa connect Pi vừa Polar Flow app."),
  bullet("Phạm vi BLE ~5-10m trong nhà — cần Pi đặt gần."),

  h2("3.2 Bluetooth Low Energy (BLE)"),

  q(34, "BLE là gì, kiến trúc GATT"),
  p("BLE (Bluetooth Low Energy) là phiên bản giao thức Bluetooth tối ưu hóa cho thiết bị tiêu thụ năng lượng thấp, đặc biệt phù hợp wearable. Khác với Bluetooth Classic (BR/EDR), BLE chỉ dùng năng lượng khi truyền burst data."),
  p("GATT (Generic Attribute Profile) là kiến trúc dữ liệu của BLE, phân cấp 3 tầng:"),
  bullet("Service: nhóm chức năng (vd Heart Rate Service)."),
  bullet("Characteristic: 1 giá trị cụ thể trong service (vd Heart Rate Measurement)."),
  bullet("Descriptor: metadata cho characteristic (vd Client Characteristic Configuration để enable notify)."),
  p("Vai trò:"),
  bullet("Peripheral (Polar H10): server, công bố services."),
  bullet("Central (Raspberry Pi): client, kết nối + subscribe characteristics."),
  bullet("Notify: peripheral push data tự động khi có thay đổi (vd mỗi nhịp tim mới)."),
  bullet("Indicate: tương tự notify nhưng có ACK."),
  bullet("Read/Write: client chủ động lấy/ghi giá trị."),

  q(35, "Các BLE service Polar H10 cung cấp"),
  bullet("Heart Rate Service (0x180D) — chuẩn, gồm Heart Rate Measurement characteristic (0x2A37) cho HR + RR interval."),
  bullet("Polar PMD Service (FB005C80-02E7-F387-1CAD-8ACD2D8DF0C8) — custom service."),
  bullet("  ↳ PMD Control Point (FB005C81-...) — gửi command start/stop stream + cấu hình tần số."),
  bullet("  ↳ PMD Data (FB005C82-...) — nhận stream ECG/ACC/PPG."),
  bullet("Battery Service (0x180F)."),
  bullet("Device Information Service (0x180A)."),

  q(36, "Phạm vi BLE thực tế và ổn định kết nối"),
  bullet("Trong phòng trống: ~10m không vật cản."),
  bullet("Trong nhà có tường: ~5-7m, có thể giảm xuống 3m qua tường gạch."),
  bullet("Người che giữa Polar và Pi: signal yếu, có thể rớt connection."),
  bullet("Reconnect time sau khi disconnect: 5-15s nếu Polar còn trong tầm; >30s nếu phải scan lại."),
  bullet("Trong đồ án, code có background_collector tự reconnect mỗi 10s khi mất connection."),

  q(37, "So sánh BLE với các giao thức không dây khác"),
  tableOf(
    ["Giao thức", "Tiêu thụ năng lượng", "Băng thông", "Tầm xa", "Phù hợp"],
    [
      ["BLE", "Rất thấp (vài mA)", "1 Mbps", "10m", "Wearable, HR/HRV stream"],
      ["Wi-Fi", "Cao (100mA+)", "100+ Mbps", "30-100m", "Video, internet"],
      ["ANT+", "Rất thấp", "1 Mbps", "10m", "Sports tracker"],
      ["LoRa", "Thấp", "0.3-50 kbps", "5-15 km", "IoT outdoor, không phù hợp realtime"],
      ["Zigbee", "Thấp", "250 kbps", "10-100m", "Smart home"],
    ],
    [1500, 2100, 1500, 1700, 2560]
  ),

  h2("3.3 Raspberry Pi 5 — Edge Computing"),

  q(38, "Thông số kỹ thuật Raspberry Pi 5"),
  tableOf(
    ["Thành phần", "Pi 5 8GB"],
    [
      ["CPU", "Broadcom BCM2712, 4× ARM Cortex-A76 @ 2.4 GHz, 64-bit"],
      ["RAM", "4GB / 8GB LPDDR4X-4267"],
      ["GPU", "VideoCore VII @ 800 MHz, hỗ trợ Vulkan 1.2"],
      ["WiFi", "Dual-band 802.11ac (2.4/5 GHz)"],
      ["Bluetooth", "BLE 5.0, tích hợp module Cypress CYW43455"],
      ["Storage", "microSD UHS-I + PCIe 2.0 NVMe (qua HAT)"],
      ["USB", "2× USB 3.0, 2× USB 2.0"],
      ["Mạng", "Gigabit Ethernet"],
      ["Công suất", "5V/5A (25W), khuyến nghị nguồn chính hãng"],
      ["Kích thước", "85 × 56 × 17 mm"],
    ],
    [2500, 6860]
  ),

  q(39, "Hệ điều hành sử dụng"),
  bullet("Raspberry Pi OS 64-bit Bookworm (Debian 12) — chọn cho đồ án này, có sẵn driver BLE và mosquitto trong apt."),
  bullet("Phiên bản Lite (không GUI) — tiết kiệm RAM, dùng cho Pi headless."),
  bullet("Ubuntu Server 24.04 LTS 64-bit — alternative, hỗ trợ tốt hơn cho ML frameworks."),
  bullet("Kernel 6.12 hỗ trợ Pi 5 chip BCM2712."),
  bullet("Không dùng 32-bit — torch ARM wheel chỉ có cho 64-bit."),

  q(40, "Các thư viện chính dùng"),
  tableOf(
    ["Mục đích", "Thư viện", "Phiên bản"],
    [
      ["BLE communication", "bleak", "0.21+"],
      ["Numerical computation", "numpy", "1.26+"],
      ["Signal processing", "scipy", "1.11+"],
      ["ML inference", "scikit-learn", "1.3+"],
      ["Deep learning", "PyTorch CPU", "2.x"],
      ["ECG processing", "neurokit2", "0.2+"],
      ["WFDB reader", "wfdb", "4.x"],
      ["HTTP framework", "FastAPI", "0.104+"],
      ["ASGI server", "uvicorn", "0.24+"],
      ["MongoDB client", "pymongo", "4.6+"],
      ["MQTT publisher", "paho-mqtt", "1.6+"],
      ["Storage backend", "sqlite3 (stdlib)", "WAL mode"],
    ],
    [3000, 3000, 2360]
  ),

  q(41, "So sánh đặt mô hình AI trên Pi 5 với lựa chọn khác"),
  tableOf(
    ["Platform", "RAM", "CPU/GPU", "Giá", "Latency 30s window"],
    [
      ["Pi 5 8GB", "8GB", "ARM Cortex-A76 4-core", "~3.000.000 VND", "200-500ms (CPU)"],
      ["Jetson Nano 4GB", "4GB", "ARM A57 + GPU 128 CUDA", "~5.000.000 VND", "100-200ms (GPU)"],
      ["Smartphone (Snapdragon 8 Gen 2)", "8-12GB", "ARM v9 + NPU", "10-30 triệu", "50-150ms"],
      ["Cloud GPU (AWS p3.2xlarge)", "61GB", "V100 GPU", "~3 USD/giờ", "20-50ms + RTT internet"],
    ],
    [3300, 1500, 2500, 1500, 1560]
  ),
  pRich([
    { text: "Lựa chọn Pi 5 cho đồ án vì: ", bold: true },
    { text: "(1) chi phí thấp nhất, (2) tự chủ tại nhà người già, (3) đủ hiệu năng cho 5 model + storage + sync, (4) cộng đồng và tài liệu Linux ARM phong phú." },
  ]),

  q(42, "Cấu hình phần cứng kèm theo"),
  bullet("Nguồn: 5V/5A USB-C PD chính hãng Raspberry Pi (loại 27W) — không dùng sạc điện thoại."),
  bullet("Tản nhiệt: heatsink + fan PWM official Pi 5 hoặc tản chủ động (Argon One V5) — CPU lên 70°C khi inference."),
  bullet("Storage: SD card 32GB Class A2 (Samsung EVO Plus, SanDisk Extreme), HOẶC SSD NVMe qua HAT để tăng IOPS SQLite."),
  bullet("Vỏ: case nhựa hoặc kim loại có cooling — đặt Pi cách bệnh nhân tối đa 5m."),
  bullet("UPS (Uninterruptible Power Supply): khuyến nghị PiSugar 3 Plus hoặc UPS HAT để tránh corrupt DB khi mất điện."),
  bullet("Màn LCD nhỏ (tuỳ chọn): Pimoroni HyperPixel 4.0 hiển thị trạng thái Polar + alert level + IP."),

  h2("3.4 Trí tuệ nhân tạo và Machine Learning"),

  q(43, "Bài toán AI là gì"),
  p("Đồ án có 5 bài toán phân loại song song trên cùng pipeline:"),
  bullet("1. Rhythm classification: 4 classes (normal/possible_afib/other_rhythm/noise) — input ECG window 30s × 130Hz."),
  bullet("2. Ectopy classification: 5 classes (normal/pvc/pac/mixed_ectopic/other) — input cùng window + features morphological."),
  bullet("3. Stress detection: 2 classes (non_stress/stress) — input 12 HRV features từ RR intervals trong 300s."),
  bullet("4. Anomaly detection: unsupervised IsolationForest — input 10 ECG features."),
  bullet("5. Signal quality assessment: rule-based, 3 classes (good/fair/poor)."),
  p("KHÔNG dùng multi-task model vì mỗi bài toán có input/timescale khác nhau (30s ECG vs 300s HRV vs morphological)."),

  q(44, "Kiến trúc model thường dùng cho ECG classification"),
  bullet("1D-CNN: convolutional layers áp dụng trên axis thời gian — phổ biến cho rhythm classification (Hannun et al. 2019 — Nature Medicine)."),
  bullet("ResNet-1D: deeper CNN với residual connection, dễ train, đã state-of-the-art trong CinC Challenge."),
  bullet("LSTM/GRU: cho time series sequence — phù hợp HR/HRV variable length nhưng chậm trên CPU."),
  bullet("CNN-LSTM hybrid: CNN extract local features + LSTM model temporal dependencies."),
  bullet("Transformer (1D Vision Transformer): SOTA hiện tại nhưng đắt tính toán, chưa phù hợp Pi 5 CPU."),
  bullet("Feature-engineered + Gradient Boosting: trích đặc trưng HRV/morphological + HistGradientBoosting — đồ án này dùng cách này cho rhythm/ectopy vì nhẹ + interpretable."),

  q(45, "Kiến trúc cho HAR từ accelerometer"),
  bullet("Rule-based + threshold: đơn giản, nhanh, đồ án V1 dùng cách này."),
  bullet("Statistical features + SVM/RF: trích mean/std/skewness/kurtosis trong window 2-3s."),
  bullet("CNN: tách trục x/y/z thành 3 channels, áp dụng 1D-CNN."),
  bullet("LSTM: model dynamics chuyển động."),
  bullet("CNN-LSTM hybrid (DeepConvLSTM, Ordóñez & Roggen 2016)."),
  bullet("TinyHAR (Zhou et al. 2023): kiến trúc nhẹ cho edge devices."),

  q(46, "Pipeline xử lý tín hiệu trước khi đưa vào model"),
  pRich([{ text: "ECG (src/preprocessing.py):", bold: true }]),
  bullet("Resample: từ source sample rate (CinC 300Hz / MITDB 360Hz) → 130Hz target."),
  bullet("Bandpass filter: 0.5-40 Hz để loại baseline wander + power line noise."),
  bullet("Normalize: chia cho IQR (interquartile range) — robust với outlier."),
  bullet("Window: chia thành chunks 30s × 130Hz = 3900 samples."),
  bullet("R-peak detection: Pan-Tompkins (qua neurokit2) — extract RR intervals."),
  bullet("Feature extraction: 41 features cho rhythm, 48 cho ectopy, 10 cho anomaly, 12 HRV cho stress."),
  pRich([{ text: "ACC (src/features/acc_features.py):", bold: true }]),
  bullet("Parse Polar PMD ACC packet (header 10 byte + frame 8/16/24-bit)."),
  bullet("Tính SVM (signal vector magnitude) = √(x² + y² + z²)."),
  bullet("Sliding window 2-5s, tính std/mean/peak."),
  bullet("Classify activity theo threshold."),

  q(47, "Kỹ thuật xử lý mất cân bằng dữ liệu"),
  bullet("Class weighting: gán trọng số cao hơn cho class hiếm — đồ án dùng trong rhythm model: AFib weight=2.8, noise=4.0."),
  bullet("Stratified sampling: chia train/test giữ tỷ lệ class."),
  bullet("SMOTE (Synthetic Minority Oversampling): tạo synthetic samples — có thể dùng cho ectopy `mixed_ectopic` (n=27)."),
  bullet("Focal Loss: penalize hard examples mạnh hơn — phù hợp với deep learning."),
  bullet("Ensemble với threshold tuning: tăng decision threshold để giảm FP cho class majority."),
  bullet("Data augmentation: NSTDB noise được dùng để augment noise class (1600 windows synthetic)."),

  q(48, "Framework huấn luyện và triển khai"),
  bullet("Training: scikit-learn (HistGradientBoosting, RandomForest, IsolationForest, SVM) + PyTorch CPU cho CNN nếu cần."),
  bullet("Lưu artifact: joblib (.pkl) cho sklearn, torch.save() cho PyTorch (.pt)."),
  bullet("Triển khai trên Pi: KHÔNG dùng quantization (TFLite/ONNX) vì model sklearn đã đủ nhẹ (<5MB mỗi cái)."),
  bullet("Inference: dùng trực tiếp joblib.load() trên Pi — latency 200-500ms/cycle cho cả 5 model."),
  note("Nếu sau này cần CNN/Transformer lớn, sẽ migrate sang ONNX Runtime cho speed-up 2-3x trên ARM CPU."),

  h2("3.5 Cloud và Backend"),

  q(49, "Lựa chọn nền tảng cloud"),
  pRich([
    { text: "Đồ án này chọn MongoDB Atlas (free tier 512MB) vì: ", bold: true },
  ]),
  bullet("Document-based — phù hợp lưu prediction JSON nested (rhythm/stress/ectopy nested objects)."),
  bullet("Free tier đủ cho 1-2 patient × 6 tháng dữ liệu."),
  bullet("pymongo client Python sẵn, không cần auth phức tạp như Firebase Auth."),
  bullet("Aggregate framework mạnh cho phân tích long-term."),
  bullet("Tương thích với MongoDB Compass GUI để khám phá dữ liệu."),
  p("So sánh:"),
  tableOf(
    ["Platform", "Loại DB", "Free tier", "Realtime push"],
    [
      ["MongoDB Atlas (chọn)", "Document", "512MB", "Change Streams (manual)"],
      ["Firebase Firestore", "Document", "1GB", "Realtime SDK built-in"],
      ["AWS RDS PostgreSQL", "Relational", "12 tháng free", "Cần Lambda/SNS"],
      ["InfluxDB Cloud", "Time-series", "30 ngày retention", "Tốt cho ECG raw"],
      ["Self-hosted VPS", "Tuỳ", "Trả tiền VPS", "Tuỳ implement"],
    ],
    [2200, 1500, 1800, 2860]
  ),

  q(50, "Cơ sở dữ liệu sử dụng"),
  pRich([{ text: "Local trên Pi:", bold: true }]),
  bullet("SQLite với WAL mode — 1 file ecg_monitor.db trong /home/custard/elderly_care/data/."),
  bullet("Schema: bảng predictions (38 cột), events, raw_signal_chunks (BLOB zlib), guided_baseline_sessions, assessment_snapshots, collection_sessions."),
  bullet("WAL + busy_timeout=30s + cache_size=20MB cho concurrent read/write."),
  pRich([{ text: "Cloud:", bold: true }]),
  bullet("MongoDB Atlas — 10 collections: predictions, events, raw_signal_chunks, session_summaries, risk_summaries, collection_sessions, collection_segments, assessment_snapshots, personal_baselines, sync_runs."),

  q(51, "Giao thức truyền dữ liệu Pi → cloud"),
  p("Đồ án dùng HTTPS REST (qua pymongo) cho sync MongoDB, KHÔNG dùng MQTT lên cloud vì:"),
  bullet("MongoDB Atlas không có MQTT broker."),
  bullet("Bulk write 200 docs/batch hiệu quả hơn nhiều round-trip MQTT."),
  bullet("Async background sync mỗi 5 phút — không cần realtime."),
  p("Cho Pi → app (cùng LAN), dùng MQTT (mosquitto) vì:"),
  bullet("Persistent: broker giữ retained alert, app reconnect vẫn nhận được."),
  bullet("Battery-friendly cho phone app (idle subscribe)."),
  bullet("QoS 2 đảm bảo exactly-once delivery cho alert."),

  q(52, "Cơ chế xác thực và bảo mật"),
  bullet("MongoDB Atlas: connection string với user/password + IP whitelist."),
  bullet("TLS bắt buộc cho Atlas connection (SRV record + TLS 1.2+)."),
  bullet("FastAPI optional header auth: X-Access-Code + X-Device-Code (app gửi theo)."),
  bullet("Local MQTT mosquitto: hiện tại allow_anonymous cho dev; production thêm mosquitto_passwd."),
  bullet("Không có HTTPS trên Pi (chỉ HTTP) — chấp nhận được vì LAN nội bộ; có thể thêm self-signed cert."),
  bullet(".env file chứa MONGODB_URI không commit vào git (.gitignore)."),

  q(53, "Tuân thủ chuẩn dữ liệu y tế"),
  bullet("HIPAA (Health Insurance Portability and Accountability Act — US): không áp dụng tại VN trực tiếp nhưng là best practice tham khảo."),
  bullet("Luật Khám chữa bệnh VN 2009 (Điều 8): bảo mật thông tin sức khoẻ là quyền của người bệnh."),
  bullet("Nghị định 13/2023/NĐ-CP về bảo vệ dữ liệu cá nhân (có hiệu lực 1/7/2023): yêu cầu mã hóa, consent rõ ràng."),
  bullet("Đồ án thực hiện: (1) anonymization patient_id, (2) TLS cho cloud, (3) WAL SQLite tránh mất dữ liệu, (4) không upload raw ECG mặc định (chỉ metadata)."),
  bullet("Khi mở rộng dùng cho bệnh viện thực tế, cần đăng ký với Bộ Y tế theo Thông tư 54/2017/TT-BYT."),

  h2("3.6 Ứng dụng người theo dõi (Flutter)"),

  q(54, "Nền tảng phát triển app"),
  pRich([
    { text: "Đồ án dùng Flutter ", bold: true },
    { text: "(Dart SDK ≥3.2.0) vì:" },
  ]),
  bullet("Cross-platform: build 1 codebase chạy Android + Web + Windows (folder hiện có)."),
  bullet("UI declarative, dễ làm dashboard realtime với riverpod state notifier."),
  bullet("Hỗ trợ tốt MQTT (package mqtt_client), HTTP (dio), charts (fl_chart)."),
  bullet("Tạo PDF báo cáo qua package pdf + printing — chia sẻ Zalo/email/in."),
  bullet("Hot reload tăng tốc phát triển UI."),
  p("Alternatives đã cân nhắc:"),
  bullet("React Native: tương tự Flutter nhưng performance UI thấp hơn cho biểu đồ."),
  bullet("Android Native (Kotlin): chỉ cho Android, mất công viết lại cho iOS."),
  bullet("Web responsive: dễ deploy, nhưng không có background notification mạnh."),

  q(55, "Thư viện/dịch vụ cho realtime data và notification"),
  bullet("mqtt_client 10.2.1 — kết nối broker mosquitto Pi qua MQTT."),
  bullet("Riverpod (flutter_riverpod 2.4.9) — state management, watch vitalsProvider tự rebuild UI."),
  bullet("Dio 5.4.0 — HTTP client cho REST API gọi tới FastAPI."),
  bullet("hive 2.2.3 + isar 3.1.0 — local cache settings + history."),
  bullet("go_router 12.1.3 — navigation."),
  bullet("Firebase Cloud Messaging (firebase_messaging) — đã chuẩn bị, sẽ tích hợp V2 cho push khi caregiver xa nhà."),
  bullet("Vibration + audioplayers — local alert sound/haptic."),
  bullet("pdf 3.11.3 + printing 5.13.1 — generate clinical report PDF."),

  q(56, "Hiển thị ECG waveform realtime"),
  bullet("Thư viện: fl_chart 0.66.2 (LineChart)."),
  bullet("Data source: MQTT topic `elderly_care/<patient_id>/vitals/live` payload chứa array ECG mẫu mới nhất."),
  bullet("Refresh rate: mỗi prediction cycle ~30s (theo step BLE)."),
  bullet("Render: ring buffer 3900 samples (30s × 130Hz), update qua riverpod stream."),
  bullet("HR gauge: vòng tròn animated với pulse effect đồng bộ HR (file hr_gauge_widget.dart)."),
  bullet("Mini HR chart: line chart compact dưới HR gauge (mini_hr_chart_widget.dart)."),
];

// CHƯƠNG 4 (compact)
const chapter4 = [
  h1("CHƯƠNG 4 — THIẾT KẾ HỆ THỐNG"),

  h2("4.1 Sơ đồ tổng thể và kiến trúc"),

  q(57, "Sơ đồ khối hệ thống chi tiết"),
  p("Đề xuất vẽ 4 lớp:"),
  bullet("Tầng cảm biến: Polar H10 (chest strap ECG + ACC)."),
  bullet("Tầng edge: Pi 5 chạy FastAPI + SQLite + mosquitto + 5 model AI."),
  bullet("Tầng giao tiếp: BLE (sensor→edge), MQTT/WebSocket/HTTP (edge→app), HTTPS (edge→cloud)."),
  bullet("Tầng consumer: Flutter app (Wearer/Caregiver mode), MongoDB Atlas archive, Web dashboard."),
  note("Mỗi mũi tên chú thích giao thức + tần suất + payload size."),

  q(58, "Sơ đồ triển khai (deployment diagram)"),
  bullet("Polar H10: chạy firmware Polar, advertise BLE @ 130 Hz ECG + 25 Hz ACC."),
  bullet("Raspberry Pi 5: OS Pi OS 64-bit Bookworm; systemd service elderly-care.service chạy uvicorn :8000; systemd mosquitto.service :1883."),
  bullet("Smartphone caregiver: Flutter app subscribe MQTT broker Pi qua WiFi LAN."),
  bullet("Cloud: MongoDB Atlas cluster M0 free tier."),

  q(59, "Use case diagram"),
  bullet("Actor: Người cao tuổi (Wearer) — actor chính, đeo Polar, ít thao tác."),
  bullet("Actor: Người thân/caregiver — actor giám sát, xem app."),
  bullet("Actor: Bác sĩ — actor read-only, xem PDF report."),
  bullet("Actor: Admin — actor cấu hình Pi, sync MongoDB."),
  p("Use cases chính: Đeo thiết bị | Xem dashboard | Nhận alert | Xem lịch sử | Calibrate baseline 7 ngày | Generate PDF | Configure threshold | Sync cloud."),

  h2("4.2 Module thu dữ liệu trên Pi (BLE Client)"),

  q(60, "Lưu đồ kết nối BLE với Polar H10"),
  code("scan(name='Polar H10', timeout=20s)\n   │\n   ▼\nconnect(address, timeout=20s)\n   │\n   ▼\nstart_notify(HR_UUID, hr_callback)\n   │\n   ▼\nstart_notify(PMD_DATA, pmd_callback)\n   │\n   ▼\nwrite_gatt_char(PMD_CONTROL, ECG_START_CMD)\n   │\n   ▼\nwrite_gatt_char(PMD_CONTROL, ACC_START_CMD)\n   │\n   ▼\nLoop: read 30s window → predict → save → broadcast MQTT\n   │\n   ├─ Exception → sleep(10s) → reconnect from scan\n   └─ asyncio.CancelledError → stop_notify + cleanup"),

  q(61, "Cấu trúc dữ liệu ECG/ACC nhận được"),
  bullet("PMD ECG packet: header 10 bytes + body: mỗi sample 3 bytes (24-bit signed little-endian raw ADC value)."),
  bullet("Parse: signed_24_to_int(data[10+i:10+i+3]) cho i bước 3 đến hết packet."),
  bullet("PMD ACC packet: tương tự, mỗi frame 6 bytes (2 byte/axis), Polar tự convert sang mG."),
  bullet("HR characteristic 0x2A37: byte 0 flags, byte 1 HR (8-bit) hoặc bytes 1-2 (16-bit), tiếp theo RR intervals 16-bit @ 1024Hz resolution."),

  q(62, "Buffer sliding window"),
  bullet("ECG: window 30s × 130Hz = 3900 samples, step 5s (overlap 25s)."),
  bullet("ACC: window cùng 30s × 25Hz = 750 samples."),
  bullet("HRV stress: window 300s (5 phút) chứa RR intervals, step 60s, min 20 RR/window."),
  bullet("Buffer cap: deque maxlen=ECG_RATE × chunk_seconds × 3 (~11700 cho 30s × 3) để tránh OOM khi predict bị chậm."),

  q(63, "Xử lý mất kết nối BLE và cơ chế reconnect"),
  bullet("Exception handler trong polar_background_collector: catch BleakError → log → sleep 10s → bluetooth_prediction_stream() chạy lại từ scan."),
  bullet("BLE adapter reset khi cần: hciconfig hci0 down/up qua systemctl restart bluetooth."),
  bullet("Polar pairing được persistent với `trust` trong bluetoothctl — reconnect không cần PIN lại."),
  bullet("Exponential backoff (V2 đề xuất): sleep 10, 20, 40, max 120s."),

  h2("4.3 Pipeline AI"),

  q(64, "Lưu đồ tổng thể"),
  code("Polar H10 ──BLE──► [Buffer ECG 30s, ACC 30s]\n                          │\n                          ▼\n                   preprocessing.py\n                   (resample 130Hz, bandpass 0.5-40Hz, normalize IQR)\n                          │\n          ┌───────────────┼───────────────┐\n          ▼               ▼               ▼\n     R-peak detect    ACC features    Signal quality\n     (Pan-Tompkins)   (SVM, std)      (good/fair/poor)\n          │               │\n     RR intervals    Activity state\n          │\n   ┌──────┼────────┬──────────┬──────────┐\n   ▼      ▼        ▼          ▼          ▼\n Rhythm Ectopy Stress(HRV) Anomaly  HR event\n  CNN    CNN    RF+SVM    IsoForest  rules\n   │      │        │         │          │\n   └──────┴────┬───┴─────────┴──────────┘\n              ▼\n         alert_engine.map_*()\n              │\n         {alert_level, message, events}\n              │\n   ┌──────────┼──────────┬───────────────┐\n   ▼          ▼          ▼               ▼\n SQLite   WebSocket   MQTT alert     Webhook HTTP\n  save    broadcast   publish        (optional)"),

  q(65, "Nhánh ECG"),
  bullet("Lọc nhiễu: bandpass 0.5-40Hz (Butterworth order 4) loại baseline wander + power-line."),
  bullet("R-peak detection: dùng neurokit2 ecg_peaks() với Pan-Tompkins algorithm — sensitivity >99%."),
  bullet("Trích RR intervals (ms) từ vị trí R-peak."),
  bullet("Rhythm: 41 features (HRV + morphological + spectral entropy) → HistGradientBoostingClassifier."),
  bullet("Ectopy: 48 features (rhythm features + 7 ectopy-specific: premature_rr_ratio, compensatory_pause_ratio, etc.) → HistGBM."),
  bullet("Decision: argmax + threshold tuning (rhythm_decision_config.json — probability_only mode, threshold 0.05)."),

  q(66, "Nhánh HAR (ACC)"),
  bullet("Normalize: trừ DC offset (subtract mean) hoặc giữ raw để phát hiện vector trọng lực."),
  bullet("Sliding window 2-5s, tính SVM = √(x² + y² + z²)."),
  bullet("Statistical features: mean, std, peak, zero-crossing rate."),
  bullet("V1 rule-based: classify theo vm_std thresholds (calibrated từ sensor_context_config.json)."),
  bullet("V2 đề xuất: 1D-CNN trên raw (x,y,z) × 25Hz × 2s = (3,50) input."),

  q(67, "Kiến trúc cụ thể của từng model"),
  pRich([{ text: "Rhythm feature model (đã train):", bold: true }]),
  bullet("HistGradientBoostingClassifier: max_iter=250, learning_rate=0.05, l2_reg=0.05."),
  bullet("Input: 41 features × 1 sample."),
  bullet("Output: 4 class probabilities + argmax."),
  pRich([{ text: "Ectopy feature model:", bold: true }]),
  bullet("HistGBM với 48 features, 5 classes."),
  pRich([{ text: "Stress (WESAD):", bold: true }]),
  bullet("Soft voting: RandomForest(n=400, balanced) + SVM(rbf, C=2) → average probabilities."),
  bullet("Input: 12 HRV features."),
  pRich([{ text: "Anomaly:", bold: true }]),
  bullet("IsolationForest(n=100, contamination=0.05)."),
  pRich([{ text: "Rhythm CNN (chưa train, lưu kiến trúc tham khảo):", bold: true }]),
  bullet("Input: (1, 3900) ECG raw."),
  bullet("Conv1d 32→Conv1d 64→Conv1d 128 + MaxPool + FC + softmax 4 classes."),

  q(68, "Bảng siêu tham số huấn luyện"),
  tableOf(
    ["Model", "Algorithm", "Hyperparameters", "Train time"],
    [
      ["Rhythm", "HistGBM", "max_iter=250, lr=0.05, l2=0.05", "~3 phút"],
      ["Ectopy", "HistGBM", "max_iter=250, lr=0.05", "~2 phút"],
      ["Stress", "RF+SVM", "RF(n=400, balanced), SVM(rbf, C=2)", "~10 phút (LOSO 15 folds)"],
      ["Anomaly", "IsolationForest", "n_estimators=100, contamination=0.05", "~30 giây"],
    ],
    [1500, 1500, 3700, 1660]
  ),

  q(69, "Chiến lược chia dữ liệu"),
  bullet("Rhythm: GroupShuffleSplit theo record_id (80% train / 20% test) — tránh data leakage do cùng 1 ECG có nhiều windows."),
  bullet("Stress: LOSO-CV (Leave-One-Subject-Out) — 15 subjects WESAD → 15 folds, mỗi fold test 1 subject — đánh giá khắt khe nhất."),
  bullet("Ectopy: stratified random 80/20 vì MITDB có record id riêng."),
  bullet("Anomaly: split 80/20 trên class normal (unsupervised), test với normal + abnormal."),
  bullet("AFDB long-term: KHÔNG split, dùng toàn bộ 25 records để evaluate threshold."),

  q(70, "Benchmark trên Pi 5"),
  tableOf(
    ["Model", "Size", "Latency 1 window 30s", "RAM peak"],
    [
      ["Rhythm HistGBM", "3.7 MB", "~80 ms", "~50 MB"],
      ["Ectopy HistGBM", "4.3 MB", "~70 ms", "~50 MB"],
      ["Stress RF+SVM", "1.9 MB", "~40 ms", "~30 MB"],
      ["Anomaly IsoForest", "1.1 MB", "~20 ms", "~20 MB"],
      ["TỔNG pipeline / cycle", "~11 MB", "~200-500 ms", "~450-700 MB process"],
    ],
    [2400, 1300, 2500, 2160]
  ),
  note("Hiện không dùng quantization. Nếu cần tăng tốc, có thể convert sklearn → ONNX hoặc dùng pytorch CNN với torch.jit.script."),

  h2("4.4 Logic cảnh báo"),

  q(71, "Quy tắc kích hoạt cảnh báo"),
  bullet("AFib episode: cần 2 windows liên tiếp có afib_probability >= 0.05 (RHYTHM_AFIB_EPISODE_THRESHOLD)."),
  bullet("Tachycardia: HR > 100 bpm trong nghỉ (activity=REST), kéo dài >2 cycles."),
  bullet("Bradycardia: HR < 50 bpm khi không phải đang ngủ."),
  bullet("Ectopy alert: pvc_probability > 0.4 trong >3 cycles liên tiếp (chống false alarm tức thời)."),
  bullet("Fall: 1 chu kỳ free-fall → impact >2000mG → post-stillness 5s = critical."),
  bullet("Mọi alert phải đạt signal_quality >= fair (loại bỏ noise)."),

  q(72, "Phân cấp mức độ cảnh báo"),
  tableOf(
    ["Mức", "Kênh delivery", "UI app", "Đề xuất V2"],
    [
      ["normal", "WebSocket live", "Dashboard xanh", "—"],
      ["medium", "WebSocket + MQTT", "Banner vàng + haptic ngắn", "FCM nếu xa nhà"],
      ["high", "WebSocket + MQTT + Webhook", "Banner đỏ + rung mạnh + âm thanh", "FCM bắt buộc"],
      ["critical", "Tất cả + auto-call", "Toàn màn hình đỏ + alarm sound", "FCM + SMS + gọi điện"],
    ],
    [1500, 2700, 2700, 2460]
  ),

  q(73, "Cơ chế hủy/xác nhận từ phía Wearer"),
  bullet("Nút \"Tôi ổn\" trong app: gửi POST /events/acknowledge với event_id."),
  bullet("Pi nhận → mark event là confirmed_false_positive — không retry alert trong N phút."),
  bullet("Threshold tự động tăng lên 1 chút cho user này (feedback learning)."),
  bullet("Sau 3 lần FP liên tiếp cho cùng event_type, tự động relax threshold thêm (chống false alarm fatigue)."),

  h2("4.5 Backend & Cloud"),

  q(74, "ERD/Schema cơ sở dữ liệu"),
  pRich([{ text: "SQLite (Pi local):", bold: true }]),
  bullet("predictions (38 cột): prediction_id, session_id, patient_id, timestamp, sample_rate_hz, heart_rate_bpm, stress_json, anomaly_score, rhythm_json, ectopy_json, hr_event_json, af_episode_json, sensor_context_json, alert_level, raw_ecg_path, raw_acc_path, raw_ecg_chunk_ids_json, ..."),
  bullet("events: event_id, patient_id, timestamp, event_type, severity, label, message."),
  bullet("raw_signal_chunks: chunk_id, patient_id, signal_type, timestamp_start_unix, sample_rate, encoding, payload_blob (zlib), is_synced, is_baseline_usable."),
  bullet("collection_sessions, collection_segments: cho guided baseline 7 ngày."),
  bullet("assessment_snapshots: kết quả daily/weekly assessment."),
  bullet("guided_baseline_sessions/segments: REST/WALK/ACTIVE segment status."),

  q(75, "API endpoints chính (tóm tắt 38 endpoints)"),
  bullet("Auth/Health: GET /health"),
  bullet("Inference: POST /predict, POST /predict_demo, POST /ingest-ecg"),
  bullet("Polar BLE control: POST /polar/start, POST /polar/stop"),
  bullet("Results: GET /latest-result, GET /latest-ecg, GET /history, GET /events, POST /events/rebuild"),
  bullet("Storage: GET /storage/status, GET /storage/raw-chunks, GET /storage/raw-chunks/{id}, GET /storage/collection-sessions, GET /storage/assessment-snapshots"),
  bullet("MongoDB sync: POST /storage/sync-mongodb, POST /storage/purge-synced, scheduler endpoints"),
  bullet("Baseline: POST /personal-baseline/update-progressive, GET /personal-baseline/status, GET /guided-baseline/status, POST /guided-baseline/*"),
  bullet("Reports: GET /daily-health-assessment, GET /health-report, GET /temporal-health-report"),
  bullet("WebSocket: /ws/vitals"),
  bullet("Dashboard: GET /dashboard, GET /docs (Swagger)"),

  q(76, "Payload JSON từ Pi → cloud"),
  code(`{\n  "prediction_id": "uuid-...",\n  "patient_id": "polar_h10",\n  "timestamp": "2026-05-25T10:00:00Z",\n  "timestamp_epoch": 1748160000.0,\n  "session_id": "20260525",\n  "sample_rate_hz": 130.0,\n  "heart_rate_bpm": 72.5,\n  "rhythm": {"label": "normal", "probabilities": {...}, "alert_level": "normal"},\n  "stress": {"label": "non_stress", "probability": 0.34, "alert_level": "normal"},\n  "ectopy": {"label": "normal", "probabilities": {...}},\n  "anomaly": {"score": -0.02, "is_anomaly": false},\n  "hr_event": {"label": "normal"},\n  "af_episode": {"active": false, "burden_percent": 0.0, "episode_count": 0},\n  "signal_quality": {"label": "good", "score": 0.92},\n  "sensor_context": {"activity_state": "REST", "fall": null},\n  "alert_level": "normal",\n  "message": "Tình trạng bình thường"\n}`),

  q(77, "Chiến lược lưu trữ ECG raw"),
  p("Tính toán: 130 Hz × 4 bytes × 86400s = 45 MB/ngày raw ECG → +ACC = ~50 MB/ngày."),
  bullet("Pi local: BLOB nén zlib trong SQLite, mỗi chunk 5s ≈ 1KB nén (từ 2.6KB raw)."),
  bullet("Encoding: int32_le_zlib cho ECG, float32x4_le_zlib cho ACC, SHA256 verify."),
  bullet("Retention: giữ 24-48h trên Pi, sau đó purge nếu đã sync MongoDB."),
  bullet("MongoDB: lưu chunks đầy đủ (đã unsynced), index theo patient_id + timestamp."),
  bullet("Sample chiến lược: KHÔNG lưu raw cho prediction normal, CHỈ lưu khi có event/alert hoặc trong baseline window."),

  q(78, "Đồng bộ khi Pi mất mạng"),
  bullet("SQLite WAL: raw chunks tiếp tục ghi local, is_synced=0."),
  bullet("background_sync scheduler retry mỗi 5 phút — pymongo serverSelectionTimeoutMS=15s rồi exception → cycle sau."),
  bullet("Khi có mạng lại: scheduler tự sync hết chunks chưa synced (bulk_write batch 200)."),
  bullet("Idempotent upsert qua chunk_id unique index — không double."),
  bullet("Retention purge: KHÔNG xoá chunks chưa synced (logic `WHERE is_synced=1`)."),

  h2("4.6 Giao diện App"),

  q(79, "Wireframe các màn hình"),
  bullet("Onboarding: Role selection (Wearer/Caregiver) → Remote setup (chỉ Caregiver)."),
  bullet("Dashboard: HR gauge trung tâm + emotion card + activity badge + alert banner + ECG mini chart."),
  bullet("Alert Center: Danh sách alert filter theo time (Mới/Hôm nay/Tuần này) + swipe dismiss."),
  bullet("History: tab 24h/7d/30d với line chart HR + pie chart rhythm + HRV trend."),
  bullet("Profile: Hồ sơ y tế (bệnh nền, thuốc), AI smart thresholds, baseline calibration button."),
  bullet("Settings: MQTT/API config, threshold tuning, demo mode toggle."),
  bullet("Clinical Report (Caregiver only): tạo PDF + share."),

  q(80, "Bố cục dashboard"),
  bullet("Top AppBar: tên bệnh nhân + connection status (online/offline) + alert banner nếu có."),
  bullet("Card 1 (centerpiece): HR gauge animated."),
  bullet("Card 2: Tình trạng tim (rhythm label tiếng Việt, confidence badge)."),
  bullet("Card 3: Emotion (stress level, locked khi đang vận động)."),
  bullet("Card 4: Activity (REST/WALK/ACTIVE)."),
  bullet("Card 5: Mini chart HR 30 phút gần nhất."),
  bullet("Bottom nav: Dashboard / History / Alerts / Profile / Settings."),

  q(81, "Hiển thị ECG waveform realtime"),
  bullet("Widget: LineChart từ fl_chart, points = ring buffer 3900 samples."),
  bullet("Refresh: stream từ MQTT vitals/live (mỗi 30s với window mới)."),
  bullet("Trục Y: amplitude mV (-2 đến +2)."),
  bullet("Trục X: thời gian giây (0-30s sliding)."),
  bullet("Tô màu theo signal_quality: xanh good, vàng fair, đỏ poor."),

  q(82, "Hiển thị HRV và xu hướng"),
  bullet("History screen có tab HRV với line chart RMSSD/SDNN theo ngày/tuần/tháng."),
  bullet("Pie chart phân bố rhythm: % normal / AF / other / noise trong ngày."),
  bullet("Bar chart phân bố activity: % thời gian REST/WALK/ACTIVE."),
  bullet("Recovery score: tổng hợp HRV + activity, hiển thị 0-100."),
];

// CHƯƠNG 5
const chapter5 = [
  h1("CHƯƠNG 5 — KẾT QUẢ, ĐÁNH GIÁ, HƯỚNG PHÁT TRIỂN"),

  h2("5.1 Kết quả triển khai"),

  q(83, "Hình ảnh hệ thống thực tế"),
  bullet("Polar H10 đeo trên ngực (cần chụp ảnh người đeo, đeo qua áo mỏng)."),
  bullet("Raspberry Pi 5 trong vỏ Argon One V5 với fan PWM + heatsink — đặt trên kệ gần phòng người già."),
  bullet("Toàn bộ setup chiếm khoảng 15×10×5 cm, tiêu thụ ~10-25W."),
  note("Khi viết, thêm ảnh chụp thực tế: (1) Polar H10 đeo, (2) Pi 5 trong vỏ + cable, (3) màn dashboard browser, (4) màn Flutter app."),

  q(84, "Screenshots các màn hình app"),
  bullet("Role selection screen."),
  bullet("Dashboard với HR gauge realtime."),
  bullet("Alert center với 5-10 alert đã filter."),
  bullet("History — line chart 24h."),
  bullet("Clinical Report PDF preview."),
  note("Chạy app trong demo mode hoặc connect Pi thật để capture screenshots."),

  q(85, "Screenshots backend"),
  bullet("Swagger UI tại /docs."),
  bullet("Dashboard HTML tại /dashboard."),
  bullet("MongoDB Compass với collections predictions/events/raw_signal_chunks."),
  bullet("Mosquitto topic tree trong MQTT Explorer."),
  bullet("systemctl status elderly-care + journalctl log."),

  h2("5.2 Kết quả huấn luyện mô hình"),

  q(86, "Kết quả Rhythm + Ectopy"),
  pRich([{ text: "Rhythm model (HistGBM trên CinC + NSTDB augmented, 11.751 windows):", bold: true }]),
  tableOf(
    ["Class", "Precision", "Recall", "F1", "Support"],
    [
      ["normal", "0.761", "0.845", "0.800", "1197"],
      ["possible_afib", "0.754", "0.660", "0.704", "162"],
      ["other_rhythm", "0.623", "0.464", "0.532", "569"],
      ["noise", "0.790", "0.855", "0.822", "401"],
      ["TỔNG accuracy", "—", "—", "0.741", "2329"],
      ["TỔNG macro F1", "—", "—", "0.714", "—"],
    ],
    [2200, 1500, 1500, 1500, 1560]
  ),
  p(""),
  pRich([{ text: "Ectopy model (HistGBM trên MITDB, 2.880 windows):", bold: true }]),
  tableOf(
    ["Class", "Precision", "Recall", "F1", "Support"],
    [
      ["normal", "0.736", "0.646", "0.688", "316"],
      ["pvc", "0.404", "0.846", "0.546", "136"],
      ["pac", "0.324", "0.177", "0.229", "62"],
      ["mixed_ectopic", "0.000", "0.000", "0.000", "27"],
      ["other", "0.000", "0.000", "0.000", "59"],
      ["TỔNG accuracy", "—", "—", "0.550", "600"],
    ],
    [2200, 1500, 1500, 1500, 1560]
  ),
  p(""),
  note("Lưu ý: ectopy F1 thấp do imbalance — mixed_ectopic chỉ có 27 windows trong test. Khuyến nghị V2 gộp class hoặc thêm SMOTE."),

  q(87, "Kết quả Stress + Anomaly + AFDB"),
  pRich([{ text: "Stress (WESAD, RF+SVM soft vote, LOSO 15 folds):", bold: true }]),
  tableOf(
    ["Metric", "LOSO mean", "Final (internal)"],
    [
      ["Accuracy", "0.813", "0.820"],
      ["Macro F1", "0.774", "—"],
      ["Stress F1", "0.659", "0.730"],
      ["Stress Recall", "—", "0.794"],
      ["Stress Precision", "—", "0.676"],
    ],
    [2500, 2500, 2360]
  ),
  p(""),
  pRich([{ text: "Anomaly Legacy (IsolationForest, MITBIH+PTBDB):", bold: true }]),
  bullet("Accuracy: 0.927 (inflated do imbalance)."),
  bullet("Precision: 0.500 — 1/2 alarm sai."),
  bullet("Recall: 0.770 — bắt 77/100 abnormal."),
  bullet("F1: 0.606."),
  bullet("Confusion matrix: TP=77, FP=77, FN=23, TN=1199."),
  pRich([{ text: "AFDB long-term evaluation (28.104 windows, 23 records Holter):", bold: true }]),
  tableOf(
    ["Metric", "Giá trị"],
    [
      ["Window accuracy", "0.844"],
      ["AF Precision", "0.923"],
      ["AF Recall", "0.665"],
      ["AF F1 (threshold=0.1)", "0.773"],
      ["AF F1 (best threshold=0.05)", "0.811"],
      ["Burden error (best)", "6.9%"],
      ["Episode sensitivity", "0.804"],
      ["Episode precision", "0.813"],
      ["False episode/hour", "0.70"],
    ],
    [3500, 3860]
  ),

  q(88, "Biểu đồ loss/accuracy theo epoch"),
  note("Các model trong đồ án là sklearn (không có epoch). Nếu cần biểu đồ training curve, tham khảo confusion matrix PNG sẵn có trong models/metrics/: rhythm_feature_confusion_matrix.png, ectopy_feature_confusion_matrix.png, rhythm_cnn_confusion_matrix.png (CNN tham khảo). Hoặc plot lại từ candidate_metrics trong rhythm_feature_metrics.json (so sánh 3 candidate: RF, ExtraTrees, HistGBM)."),

  q(89, "So sánh các kiến trúc đã thử"),
  tableOf(
    ["Kiến trúc", "Accuracy", "Macro F1", "AFib Recall", "Inference (ms)"],
    [
      ["RandomForest", "0.716", "0.662", "0.519", "~120"],
      ["ExtraTrees", "0.714", "0.660", "0.525", "~150"],
      ["HistGBM (chọn)", "0.741", "0.714", "0.660", "~80"],
      ["Rhythm CNN (chuẩn bị)", "—", "—", "—", "~300 (Pi 5 CPU)"],
    ],
    [2500, 1500, 1500, 1500, 2360]
  ),

  q(90, "Kích thước model sau quantize và inference time"),
  bullet("Hiện chưa áp dụng quantization (model sklearn đã đủ nhẹ < 5 MB)."),
  bullet("Rhythm: 3.7 MB, ~80 ms."),
  bullet("Ectopy: 4.3 MB, ~70 ms."),
  bullet("Stress: 1.9 MB, ~40 ms."),
  bullet("Anomaly: 1.1 MB, ~20 ms."),
  bullet("Tổng pipeline 5 models: ~11 MB, ~200-500 ms/window."),

  h2("5.3 Đánh giá thực nghiệm thực tế"),

  q(91, "Độ chính xác phát hiện té ngã"),
  note("Cần chạy thực nghiệm: bố trí 5 người (đeo Polar), mỗi người thực hiện 20 lần kịch bản trên đệm mềm: (a) té ngang, (b) té trước, (c) té sau, (d) ngồi xuống nhanh (control). Đếm số lần hệ thống phát hiện đúng + false alarm. Bảng dự kiến:"),
  tableOf(
    ["Kịch bản", "Số lần", "Phát hiện đúng", "Tỷ lệ", "False alarm"],
    [
      ["Té ngang", "20", "—", "—", "—"],
      ["Té trước", "20", "—", "—", "—"],
      ["Té sau", "20", "—", "—", "—"],
      ["Ngồi xuống nhanh (control)", "20", "—", "—", "—"],
    ],
    [2700, 1500, 1500, 1500, 1160]
  ),

  q(92, "Độ chính xác ECG bất thường so với máy chuẩn"),
  note("Cần kế hoạch: 5-10 người, mỗi người 1 lần đo Holter 24h chuẩn (qua bệnh viện) + đeo Polar H10 song song. So sánh nhãn AFib/PVC/normal giữa 2 nguồn, tính Cohen Kappa hoặc sensitivity/specificity của hệ thống vs ground truth. Tham khảo paper validate Polar H10."),

  q(93, "Độ trễ end-to-end"),
  bullet("BLE Polar → Pi buffer: ~50 ms (buffering nhỏ trong bleak)."),
  bullet("Pi preprocessing + 5 model inference: 200-500 ms."),
  bullet("Pi → MQTT broker → app subscribe: <30 ms LAN."),
  bullet("Pi → WebSocket → browser: <100 ms LAN."),
  bullet("Pi → MongoDB Atlas: 200 ms - 2 s tuỳ chất lượng WiFi."),
  bullet("MongoDB → caregiver app: chỉ khi pull (1-5s)."),
  bullet("FCM (V2): Pi → Firebase → phone: 1-3 s."),
  bullet("TỔNG cảnh báo local: <1 s. Cảnh báo qua internet: ~3-5 s."),

  q(94, "Tỷ lệ ổn định BLE"),
  note("Đo bằng cách đếm số lần `Polar background collector error` trong uvicorn.log chia cho tổng thời gian chạy. Kế hoạch test:"),
  bullet("Trong phòng (1-3m): ~0.1 disconnect/giờ kỳ vọng."),
  bullet("Đi quanh nhà (5-10m): ~0.5-1 disconnect/giờ."),
  bullet("Người cao tuổi sinh hoạt bình thường: <2 disconnect/giờ."),
  bullet("Reconnect thành công (auto): ~95%."),

  q(95, "Uptime Pi và Cloud"),
  bullet("Pi: chạy soak test 24h/72h/1 tuần, đếm số lần service crash + restart."),
  bullet("Cloud (MongoDB Atlas): theo dõi qua Atlas dashboard — uptime free tier ~99.95% (SLA Atlas)."),
  bullet("Mục tiêu Pi uptime: 99% (tính cả reboot khi update)."),

  q(96, "Đánh giá pin Polar H10"),
  bullet("Spec: 30+ giờ continuous ECG streaming."),
  bullet("Đo thực tế: đeo liên tục, ghi thời điểm pin <20% (Polar low battery alert)."),
  bullet("Kế hoạch: thay pin CR2025 mỗi 5-7 ngày trong sử dụng thực tế."),
  bullet("Lưu ý: pin Polar không sạc lại."),

  q(97, "Tải tiêu thụ tài nguyên Pi 5"),
  tableOf(
    ["Chỉ số", "Idle (no Polar)", "Đang inference", "Đang sync MongoDB"],
    [
      ["CPU%", "<5%", "30-60% (1 core)", "+20%"],
      ["RAM", "~450 MB", "600-800 MB", "+50-100 MB"],
      ["Disk write", "0", "~5 MB/giờ", "+2-5 MB/cycle"],
      ["Nhiệt độ CPU", "45-55°C", "60-75°C", "+5°C"],
      ["Network", "~10 KB/s", "—", "100-500 KB/cycle"],
    ],
    [2500, 1700, 1900, 2260]
  ),

  h2("5.4 Đánh giá người dùng"),

  q(98, "Thử nghiệm với người cao tuổi thực tế"),
  note("Kế hoạch khả thi: 3-5 người cao tuổi (60-80 tuổi) trong gia đình/cộng đồng dùng hệ thống 1 tuần. Câu hỏi khảo sát: (1) Mức thoải mái khi đeo Polar (1-5)? (2) Tần suất đeo trong ngày? (3) Có gặp khó khăn nào không (kích ứng da, dây tuột)? (4) Caregiver đánh giá app: dễ dùng? cảnh báo có rõ ràng? thông tin có đủ? (5) Có muốn tiếp tục dùng sau thử nghiệm?"),

  h2("5.5 Hạn chế và Hướng phát triển"),

  q(99, "Hạn chế còn tồn tại"),
  bullet("Polar H10 cần làm ẩm điện cực — bất tiện khi đeo lâu, gây kích ứng da nhẹ với người da nhạy cảm."),
  bullet("Đeo dây ngực — khó với phụ nữ, người mảnh, người có vấn đề cột sống."),
  bullet("Phụ thuộc Pi tại nhà — không di chuyển ra ngoài, không có giải pháp khi đi du lịch/khám bệnh."),
  bullet("Phụ thuộc WiFi nhà — mất WiFi → mất cloud sync, Flutter app caregiver xa nhà không nhận realtime."),
  bullet("Pi cần cấp nguồn 24/7 — mất điện gây gián đoạn (chưa có UPS trong đồ án)."),
  bullet("Model ectopy yếu (F1 macro 0.29) — cần thêm dataset và retrain."),
  bullet("Chưa validate trên dữ liệu thực Polar H10 từ người Việt Nam."),
  bullet("Chưa có push notification cloud (FCM) — caregiver xa nhà phải dựa MQTT bridge."),
  bullet("Chưa tích hợp được với hồ sơ y tế bệnh viện (HL7/FHIR)."),
  bullet("UI app chưa tối ưu cho người cao tuổi (font lớn, voice control)."),

  q(100, "Hướng phát triển"),
  pRich([{ text: "Phần cứng:", bold: true }]),
  bullet("Tích hợp SpO2 (oxy máu) qua cảm biến MAX30102 trên Pi."),
  bullet("Thay Polar H10 bằng vòng tay đeo cổ tay khi công nghệ ECG cổ tay phổ biến (đã có Apple Watch nhưng API hạn chế)."),
  bullet("Thêm UPS / pin dự phòng cho Pi."),
  bullet("Tích hợp camera AI tại nhà để nhận diện hành vi qua hình ảnh (té ngã, ngừng cử động)."),
  pRich([{ text: "Phần mềm:", bold: true }]),
  bullet("Predictive AI: dự đoán nguy cơ AFib 7-30 ngày tới dựa trên trend HRV (LSTM/Transformer)."),
  bullet("Personal anomaly detection: train model riêng cho từng bệnh nhân sau 7 ngày guided baseline."),
  bullet("Chatbot AI tư vấn cho caregiver dựa trên dữ liệu (Llama 3.1 local hoặc OpenAI API)."),
  bullet("Tích hợp HL7/FHIR để export sang hệ thống bệnh viện."),
  bullet("FCM push notification + SMS gateway cho khi caregiver xa nhà."),
  pRich([{ text: "Mở rộng nghiên cứu:", bold: true }]),
  bullet("Thu thập dataset người Việt Nam (100+ subjects) — fine-tune model cho dân số bản địa."),
  bullet("Đăng ký công bố khoa học: paper về Edge AI pipeline cho người cao tuổi Việt Nam."),
  bullet("Hợp tác bệnh viện: validate clinical trial với 50+ bệnh nhân thực tế."),
];

// ---- Build Document ----

const doc = new Document({
  styles: {
    default: { document: { run: { font: F, size: 24 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: F, size: 36, bold: true, color: "1F3864" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: F, size: 30, bold: true, color: "2E5496" },
        paragraph: { spacing: { before: 240, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: F, size: 26, bold: true, color: "2E5496" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•",
        alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 }, // A4
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        children: [new TextRun({ text: "Hệ thống Theo dõi Sức khoẻ Người Cao tuổi", font: F, size: 20, italics: true, color: "808080" })],
      })] }),
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [
          new TextRun({ text: "Trang ", font: F, size: 20 }),
          new TextRun({ children: [PageNumber.CURRENT], font: F, size: 20 }),
          new TextRun({ text: " / ", font: F, size: 20 }),
          new TextRun({ children: [PageNumber.TOTAL_PAGES], font: F, size: 20 }),
        ],
      })] }),
    },
    children: [
      ...cover,
      ...chapter1,
      ...chapter2,
      ...chapter3,
      ...chapter4,
      ...chapter5,
    ],
  }],
});

Packer.toBuffer(doc).then(buffer => {
  const out = path.join(__dirname, "..", "DoAn_BoCauHoi_TraLoi.docx");
  fs.writeFileSync(out, buffer);
  const stat = fs.statSync(out);
  console.log(`✅ Generated: ${out}`);
  console.log(`   Size: ${(stat.size / 1024).toFixed(1)} KB`);
}).catch(err => {
  console.error("❌ Error:", err);
  process.exit(1);
});
