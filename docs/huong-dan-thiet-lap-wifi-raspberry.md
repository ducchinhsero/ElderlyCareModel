# Huong Dan Thiet Lap Wi-Fi Moi Cho Raspberry Pi

Tai lieu nay huong dan nguoi dung cau hinh Wi-Fi moi cho Raspberry Pi khi mang thiet bi den mot dia diem moi, vi du nha nguoi cao tuoi, phong kham, hoac noi cham soc khac.

Muc tieu: nguoi dung chi can dung dien thoai, ket noi vao Wi-Fi setup do Raspberry Pi phat ra, sau do mo `http://10.42.0.1` de nhap Wi-Fi moi.

## 1. Khi nao can lam buoc nay?

Can thiet lap Wi-Fi moi khi:

- Raspberry Pi duoc mang den noi moi.
- Wi-Fi cu khong con ton tai.
- Doi ten Wi-Fi hoac mat khau Wi-Fi nha.
- App khong ket noi duoc voi Raspberry Pi vi Pi chua vao mang.

Neu Raspberry Pi da tung duoc cau hinh dung Wi-Fi tai dia diem hien tai, thiet bi se tu ket noi va khong can lam buoc nay.

## 2. Chuan bi

Can co:

- Raspberry Pi da duoc cap nguon.
- Dien thoai co Wi-Fi.
- Ten Wi-Fi nha/phong can ket noi.
- Mat khau Wi-Fi.
- Password Wi-Fi setup cua thiet bi, neu duoc dan tren vo hop/thiet bi.

Sau khi cam nguon, cho Raspberry Pi khoi dong khoang 1-2 phut.

## 3. Cach hoat dong cua thiet bi

Khi Raspberry Pi bat len, no se tu kiem tra cac Wi-Fi da luu.

- Neu tim thay Wi-Fi da biet: Pi tu ket noi vao Wi-Fi do.
- Neu khong tim thay Wi-Fi nao dung: Pi tu phat Wi-Fi setup tam thoi.

Wi-Fi setup thuong co ten:

```text
ElderlyCare-Setup-XXXX
```

Trong do `XXXX` la ma rieng cua thiet bi.

## 4. Cac buoc thiet lap bang dien thoai

### Buoc 1: Bat Raspberry Pi

Cam nguon cho Raspberry Pi va cho khoang 1-2 phut de thiet bi khoi dong.

Neu Polar H10 da san sang, Raspberry Pi van co the tiep tuc thu va luu du lieu cuc bo khi chua co Internet. Sau khi co Wi-Fi, du lieu se duoc dong bo theo cau hinh he thong.

### Buoc 2: Mo Wi-Fi tren dien thoai

Vao man hinh Wi-Fi tren dien thoai.

Tim mang co ten dang:

```text
ElderlyCare-Setup-XXXX
```

Chon mang nay de ket noi.

Neu dien thoai bao "Wi-Fi nay khong co Internet", hay chon van ket noi. Day la binh thuong vi day chi la Wi-Fi setup noi bo cua Raspberry Pi.

### Buoc 3: Nhap password Wi-Fi setup

Nhap password Wi-Fi setup cua thiet bi neu dien thoai yeu cau.

Password nay khong phai password Wi-Fi nha. No la password rieng de vao mang setup cua Raspberry Pi.

### Buoc 4: Mo trang cau hinh

Sau khi dien thoai da ket noi vao Wi-Fi setup, mo trinh duyet tren dien thoai va nhap:

```text
http://10.42.0.1
```

Khong nhap `https`.

Dung dia chi:

```text
http://10.42.0.1
```

Khong dung:

```text
https://10.42.0.1
10.42.0.1:8000
elderlycare.local
```

### Buoc 5: Chon Wi-Fi moi

Trong trang cau hinh, chon Wi-Fi nha/phong can ket noi.

Neu danh sach Wi-Fi chua hien:

- bam nut quet lai neu co;
- doi 10-20 giay;
- dam bao Raspberry Pi dat gan router Wi-Fi.

### Buoc 6: Nhap mat khau Wi-Fi

Nhap mat khau Wi-Fi moi.

Can luu y:

- phan biet chu hoa/chu thuong;
- khong them dau cach o dau/cuoi;
- chon dung Wi-Fi 2.4 GHz neu router co tach rieng 2.4 GHz va 5 GHz.

Sau do bam nut ket noi.

### Buoc 7: Cho Raspberry Pi chuyen sang Wi-Fi moi

Neu thong tin dung, Wi-Fi setup `ElderlyCare-Setup-XXXX` se bien mat sau mot luc. Day la dau hieu binh thuong: Raspberry Pi da tat Wi-Fi setup va dang chuyen sang Wi-Fi moi.

Dien thoai co the tu dong quay lai Wi-Fi nha. Neu khong, hay vao man hinh Wi-Fi va ket noi lai Wi-Fi nha.

### Buoc 8: Mo app va ket noi lai

Sau khi Pi da vao Wi-Fi moi, mo app Elderly Care.

Neu app can nhap backend URL, thu dung:

```text
http://elderlycare.local:8000
```

Neu khong ket noi duoc bang ten nay, can tim IP moi cua Raspberry Pi trong router hoac bang cong cu scan mang, sau do nhap:

```text
http://<IP-cua-Raspberry-Pi>:8000
```

Vi du:

```text
http://192.168.1.18:8000
```

## 5. Dau hieu thiet lap thanh cong

Thiet lap thanh cong khi:

- Wi-Fi setup `ElderlyCare-Setup-XXXX` bien mat.
- Dien thoai/laptop dang ket noi Wi-Fi nha.
- App ket noi duoc backend Raspberry Pi.
- Trang health backend mo duoc:

```text
http://elderlycare.local:8000/health
```

Hoac:

```text
http://<IP-cua-Raspberry-Pi>:8000/health
```

- App hien trang thai Raspberry Pi da ket noi.
- Khi Polar H10 san sang, app co the nhan du lieu realtime sau khoang 30-60 giay.

## 6. Neu khong thay Wi-Fi ElderlyCare-Setup

Thu cac buoc sau:

1. Cho Pi khoi dong du 2 phut.
2. Dat dien thoai gan Raspberry Pi hon.
3. Tat/bat lai Wi-Fi tren dien thoai.
4. Quet Wi-Fi bang mot dien thoai khac.
5. Kiem tra xem Pi co the da tu ket noi vao Wi-Fi da luu hay chua.

Neu Pi da ket noi duoc Wi-Fi moi hoac Wi-Fi cu, no se khong phat `ElderlyCare-Setup-XXXX`.

Neu van khong thay Wi-Fi setup, can ky thuat vien kiem tra service tren Pi:

```bash
systemctl status elderly-care-wifi-provisioner --no-pager
journalctl -u elderly-care-wifi-provisioner -n 120 --no-pager
```

## 7. Neu mo 10.42.0.1 khong duoc

Kiem tra:

- Dien thoai da ket noi vao Wi-Fi `ElderlyCare-Setup-XXXX` chua.
- Dia chi da nhap dung la `http://10.42.0.1` chua.
- Khong dung `https`.
- Khong bat 4G/5G thay cho Wi-Fi setup neu dien thoai tu dong chuyen mang.

Mot so dien thoai se bao Wi-Fi setup khong co Internet va tu dong dung du lieu di dong. Neu gap truong hop nay:

- tat tam thoi du lieu di dong;
- ket noi lai Wi-Fi `ElderlyCare-Setup-XXXX`;
- mo lai `http://10.42.0.1`.

## 8. Neu nhap Wi-Fi xong nhung Pi khong ket noi duoc

Nguyen nhan thuong gap:

- sai password Wi-Fi;
- chon nham ten Wi-Fi;
- Wi-Fi qua xa;
- router chi cho phep thiet bi da dang ky MAC;
- Wi-Fi 5 GHz khong tuong thich voi cau hinh hien tai;
- mang Wi-Fi yeu cau dang nhap web portal rieng, vi du Wi-Fi cong cong/khach san.

Cach xu ly:

1. Cho 1-2 phut de Pi thu ket noi.
2. Neu Wi-Fi setup hien lai, ket noi lai vao `ElderlyCare-Setup-XXXX`.
3. Mo lai `http://10.42.0.1`.
4. Nhap lai Wi-Fi va password.
5. Uu tien Wi-Fi nha rieng, WPA/WPA2, khong dung Wi-Fi cong cong can dang nhap web.

## 9. Luu y bao mat

- Chi dua password Wi-Fi nha cho nguoi co trach nhiem cai dat.
- Khong chia se password Wi-Fi setup cong khai.
- Khong nhap MongoDB URI, API key, mat khau cloud vao trang setup Wi-Fi.
- Trang `10.42.0.1` chi dung de nhap Wi-Fi cho Raspberry Pi.

## 10. Tom tat nhanh cho nguoi dung

```text
1. Cam nguon Raspberry Pi.
2. Cho 1-2 phut.
3. Tren dien thoai, ket noi Wi-Fi ElderlyCare-Setup-XXXX.
4. Mo trinh duyet: http://10.42.0.1
5. Chon Wi-Fi nha.
6. Nhap mat khau Wi-Fi.
7. Bam ket noi.
8. Cho Wi-Fi setup bien mat.
9. Ket noi dien thoai lai Wi-Fi nha.
10. Mo app Elderly Care de kiem tra trang thai.
```

