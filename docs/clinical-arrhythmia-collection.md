# Thu Du Lieu Lam Sang Ngan Han Cho Rung Nhi

File chinh:

```bash
python -m src.services.collect_clinical_arrhythmia_data
```

Muc tieu cua script nay la thu ECG/ACC tu Polar H10 trong 1-2 gio de tao dataset sang loc co metadata lam sang. Script khong tu gan nhan y khoa chac chan cho tung cua so ECG neu khong co Holter, ECG 12 chuyen dao, hoac bac si annotation theo thoi gian.

## Lenh Thu Khuyen Nghi

Thu 1 gio:

```bash
python -m src.services.collect_clinical_arrhythmia_data \
  --participant-id p001 \
  --condition-group confirmed_afib \
  --clinical-source doctor_confirmed \
  --duration-minutes 60 \
  --address 24:AC:AC:13:EB:86
```

Thu 2 gio:

```bash
python -m src.services.collect_clinical_arrhythmia_data \
  --participant-id p001 \
  --condition-group confirmed_afib \
  --clinical-source doctor_confirmed \
  --duration-minutes 120 \
  --address 24:AC:AC:13:EB:86
```

Test nhanh khong can Polar:

```bash
python -m src.services.collect_clinical_arrhythmia_data \
  --participant-id test001 \
  --condition-group confirmed_afib \
  --clinical-source doctor_confirmed \
  --duration-minutes 5 \
  --allow-short-test \
  --dry-run
```

## Cach Chon Phan Loai

`condition_group`:

- `confirmed_afib`: nguoi tham gia co chan doan rung nhi tu nguon y khoa.
- `suspected_afib`: chi nghi ngo hoac tu khai, chua co xac nhan.
- `other_cardiac`: benh tim khac nhu ngoai tam thu, suy tim, tang huyet ap.
- `control`: nguoi doi chung.
- `unknown`: chua ro thong tin.

`clinical_source`:

- `doctor_confirmed`: bac si da xac nhan tien su/chan doan.
- `holter_report`: co bao cao Holter.
- `ecg_12lead`: co ECG 12 chuyen dao.
- `self_reported`: nguoi tham gia tu khai.
- `unknown`: chua ro nguon.

`window_rhythm_label` mac dinh la `unlabeled`. Khong doi sang `afib` chi vi nguoi do co tien su AFib. AFib co the xuat hien theo con, nen trong 1 gio thu co the co hoac khong co AFib. Chi gan nhan `afib`, `normal`, `other_rhythm`, `noise` khi co annotation theo thoi gian.

## Event Marker Trong Luc Thu

Trong terminal co the nhap:

```text
symptom palpitation
symptom dizziness
symptom chest_discomfort
activity movement
activity strap_adjustment
note patient talked for several minutes
stop
```

Event duoc luu vao `events.csv` voi thoi gian tuong doi so voi luc bat dau thu.

## Output

Mac dinh output nam tai:

```text
data_raw/clinical_arrhythmia/<participant_id>/<visit_id>/
  ecg.csv
  acc.csv
  rr.csv
  events.csv
  segments.csv
  metadata.json
  quality_report.json
  predictions_preview.csv
```

Sau khi thu, mo `quality_report.json` truoc. Session chi nen dung cho phan tich neu:

- `usable_for_analysis = true`
- `valid_signal_ratio >= 0.70`
- `ecg_sample_loss_ratio <= 0.10`
- `metadata_complete = true`

Neu `usable_for_analysis = false`, session van co the dung de debug signal quality hoac BLE, nhung khong nen dua vao train/evaluate model benh ly.

## Quy Trinh An Toan

- Dung ma an danh nhu `p001`, khong dung ten that.
- Khong luu so dien thoai, dia chi, CCCD, hoac thong tin dinh danh.
- Nguoi tham gia nen ngoi/nam nghi la chinh.
- Dung thu neu nguoi tham gia kho chiu, dau nguc, chong mat nang, hoac yeu cau dung.
- Output cua he thong la sang loc/nghi ngo, khong phai chan doan y khoa.
