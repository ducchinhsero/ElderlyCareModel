# Thiết lập Raspberry Pi cho Elderly Care

Ngày cập nhật: 2026-06-08

Tài liệu này dùng để chuẩn bị Raspberry Pi trước khi chạy backend `ElderlyCareModel`. Phần cài backend production chi tiết nằm trong `docs/deploy-raspberry-pi.md`.

## 1. Phần cứng

- Raspberry Pi 4 hoặc 5, ưu tiên OS 64-bit.
- microSD/SSD từ 32GB.
- Nguồn ổn định.
- Polar H10 + dây đeo.
- Wi-Fi hoặc LAN cho lần setup đầu.
- Tản nhiệt/quạt nếu chạy nhiều giờ.

## 2. Flash Raspberry Pi OS

Dùng Raspberry Pi Imager:

1. Chọn Raspberry Pi OS 64-bit.
2. Bật SSH.
3. Hostname khuyến nghị: `elderlycare`.
4. Username đang dùng trong project hiện tại: `elcaprj`.
5. Đặt password mạnh.
6. Có thể cấu hình Wi-Fi ban đầu nếu biết SSID/password.
7. Locale: `Asia/Ho_Chi_Minh`, keyboard `us`.

Sau khi ghi thẻ, cắm vào Pi và cấp nguồn. Đợi 1-3 phút.

## 3. SSH vào Pi

Từ Windows PowerShell:

```powershell
ssh elcaprj@elderlycare.local
```

Nếu không vào được bằng `.local`, lấy IP từ router hoặc trên màn hình Pi:

```bash
hostname -I
ip addr show wlan0
```

SSH bằng IP:

```powershell
ssh elcaprj@<IP_RASPBERRY>
```

Nếu gặp cảnh báo host key changed sau khi đổi thẻ/mạng:

```powershell
ssh-keygen -R elderlycare.local
ssh-keygen -R <IP_CU>
```

## 4. Cập nhật hệ thống

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

SSH lại sau reboot:

```powershell
ssh elcaprj@elderlycare.local
```

## 5. Bật VNC nếu cần giao diện

Nếu dùng Raspberry Pi OS Desktop:

```bash
sudo raspi-config
```

Chọn:

- `Interface Options` -> `VNC` -> enable.
- `Display Options` -> `VNC Resolution` -> chọn `1280x720` hoặc `1920x1080`.
- Reboot nếu được yêu cầu.

Kết nối bằng VNC Viewer:

```text
elderlycare.local:5900
```

hoặc:

```text
<IP_RASPBERRY>:5900
```

Nếu đang dùng Bookworm/Wayland và VNC không ổn định, chuyển sang X11 trong `raspi-config` hoặc dùng SSH là chính cho production.

## 6. Cài backend production

Clone repo:

```bash
cd /home/elcaprj
git clone https://github.com/ducchinhsero/ElderlyCareModel.git elderly_care
cd elderly_care
```

Cài production:

```bash
bash scripts/install_pi_production.sh
```

Hoặc set MAC Polar ngay:

```bash
POLAR_H10_MAC=24:AC:AC:13:EB:86 bash scripts/install_pi_production.sh
```

Kiểm tra:

```bash
sudo systemctl status elderly-care --no-pager
sudo systemctl status elderly-care-wifi-provisioner --no-pager
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

## 7. Mang Pi sang nơi mới

Chuẩn hiện tại của dự án vẫn dùng `wlan0` và Wi-Fi provisioning:

1. Pi cố kết nối Wi-Fi đã lưu.
2. Nếu không kết nối được, service `elderly-care-wifi-provisioner` phát AP `ElderlyCare-Setup-XXXX`.
3. Người dùng kết nối điện thoại/laptop vào AP này.
4. Mở app màn "Thiết lập Wi-Fi Raspberry" hoặc browser `http://10.42.0.1`.
5. Chọn Wi-Fi nhà, nhập password.
6. Pi tắt AP và chuyển sang Wi-Fi nhà nếu thông tin đúng.
7. App truy cập backend qua `elderlycare.local:8000` hoặc IP mới.

Không tự cấu hình AP thủ công bằng `hostapd.conf` cho dự án này. Production service điều khiển AP qua NetworkManager.

## 8. Kiểm tra Raspberry đang chạy và thu tín hiệu

Backend:

```bash
sudo systemctl is-active elderly-care
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

Polar:

```bash
sudo timeout 15 bluetoothctl --timeout 10 scan on 2>&1 | grep -i polar
curl -s http://127.0.0.1:8000/health | python3 -m json.tool | grep -A30 '"polar"'
```

Dữ liệu mới nhất:

```bash
curl -s http://127.0.0.1:8000/latest-result | python3 -m json.tool
```

Log:

```bash
tail -f /home/elcaprj/elderly_care/logs/uvicorn.log
sudo journalctl -u elderly-care -f
sudo journalctl -u elderly-care-wifi-provisioner -f
```

## 9. Lỗi thường gặp

### Không SSH được

- Kiểm tra Pi đã cùng mạng với máy Windows.
- Kiểm tra IP trên router.
- Nếu `.local` không resolve, dùng IP trực tiếp.
- Nếu host key changed, chạy `ssh-keygen -R`.

### App/browser mở `0.0.0.0:8000` không được

`0.0.0.0` là địa chỉ server bind, không phải địa chỉ client truy cập. Dùng:

```text
http://elderlycare.local:8000
http://<IP_RASPBERRY>:8000
```

### Polar không tự thu sau boot

```bash
grep '^POLAR_AUTO_START' /home/elcaprj/elderly_care/.env
sudo systemctl restart elderly-care
```

Giá trị production phải là:

```env
POLAR_AUTO_START=1
```

### AP Wi-Fi setup hiện lại sau khi gửi cấu hình

Thường là Pi không kết nối được Wi-Fi nhà. Kiểm tra trạng thái:

```bash
cd /home/elcaprj/elderly_care
sudo .venv/bin/python -m src.network.provisioning --status
sudo journalctl -u elderly-care-wifi-provisioner -n 100 --no-pager
```

Nếu lỗi `802-11-wireless-security.key-mgmt`, cập nhật code mới nhất và chạy lại installer để dùng bản provisioning đã thêm `wpa-psk` rõ ràng.

## 10. Tài liệu tiếp theo

- `docs/deploy-raspberry-pi.md`: cài backend production.
- `docs/wifi-provisioning-production.md`: chi tiết Wi-Fi AP setup.
- `README.md`: tổng quan backend/API/model.
