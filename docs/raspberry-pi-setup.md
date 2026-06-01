# Hướng dẫn cài đặt Raspberry Pi 5 và deploy ElderlyCareModel

## 1. Chuẩn bị

**Phần cứng:**
- Raspberry Pi 5 (khuyến nghị bản 4GB hoặc 8GB)
- Thẻ microSD ≥ 32GB (class 10/A2) hoặc SSD NVMe qua HAT
- Nguồn USB-C 5V/5A chính hãng (Pi 5 cần dòng cao, sạc điện thoại thường không đủ)
- Đầu đọc thẻ SD cắm vào PC Windows
- Cáp mạng LAN (khuyến nghị cho lần đầu) hoặc WiFi
- Tản nhiệt + quạt (Pi 5 nóng nhanh)

**Phần mềm trên PC Windows:**
- [Raspberry Pi Imager](https://www.raspberrypi.com/software/) — công cụ flash chính thức
- [RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/) — client VNC
- PuTTY hoặc Windows Terminal (SSH)
- Git for Windows

---

## 2. Flash Raspberry Pi OS lên thẻ nhớ

### Bước 1: Mở Raspberry Pi Imager

1. Chọn **Device** → `Raspberry Pi 5`
2. Chọn **Operating System** → `Raspberry Pi OS (64-bit)` (bản Bookworm Desktop, không chọn Lite vì cần GUI cho VNC)
3. Chọn **Storage** → chọn thẻ SD của bạn

### Bước 2: Cấu hình trước (rất quan trọng)

Click **Next** → chọn **EDIT SETTINGS**:

**Tab General:**
```
Hostname:     elderlycare-pi
Username:     huy
Password:     <mật khẩu mạnh>
Wireless LAN: <SSID + password WiFi nhà bạn>
Wireless LAN country: VN
Locale:       Asia/Ho_Chi_Minh, keyboard: us
```

**Tab Services:**
- ☑ Enable SSH
- ☑ Use password authentication

Click **Save** → **Yes** → xác nhận xóa thẻ SD → đợi 5–10 phút.

### Bước 3: Boot lần đầu

1. Tháo thẻ SD khỏi PC, cắm vào Pi 5
2. Cắm cáp LAN (hoặc dùng WiFi đã cấu hình)
3. Cắm nguồn → đèn xanh nhấp nháy → đợi 2–3 phút cho lần boot đầu

---

## 3. Kết nối SSH lần đầu

Từ PowerShell trên Windows:

```powershell
ssh huy@elderlycare-pi.local
```

Nếu `.local` không resolve được, tìm IP qua router hoặc:

```powershell
ping elderlycare-pi.local
```

Sau khi vào được, update hệ thống:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git python3-pip python3-venv build-essential
```

---

## 3.1 Đem Pi sang nơi khác (không có mạng cũ)

**Vấn đề:** WiFi được cấu hình lúc flash OS chỉ có ở nơi ban đầu. Khi mang Pi sang nơi khác, sẽ không có WiFi đó.

**Giải pháp:** Có **4 cách chính**:

### **Cách 1: Thêm nhiều WiFi trước khi đi (khuyến nghị)**

Khi còn ở nơi cũ, thêm sẵn **3-4 WiFi có thể gặp**:

```bash
ssh huy@elderlycare-pi.local
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```

Cuộn xuống cuối file, thêm các network mới:

```ini
# Hiện tại
network={
    ssid="WiFi-nhà-gốc"
    psk="password-gốc"
    key_mgmt=WPA-PSK
}

# Thêm WiFi phòng khám/bệnh viện
network={
    ssid="WiFi-phòng-khám"
    psk="password1"
    key_mgmt=WPA-PSK
}

# Thêm WiFi khách sạn
network={
    ssid="WiFi-khách-sạn"
    psk="password2"
    key_mgmt=WPA-PSK
}

# **Quan trọng nhất:** Thêm hotspot laptop Windows
network={
    ssid="Laptop-Hotspot"
    psk="hotspotpass"
    key_mgmt=WPA-PSK
}
```

Lưu (Ctrl+X → Y → Enter)

**Khi đến nơi mới:**
- Bật **Mobile Hotspot** trên laptop Windows: Settings → Network & internet → Mobile hotspot → On
- Pi sẽ tự kết nối vào hotspot trong 10-15 giây
- SSH từ Windows: `ssh huy@elderlycare-pi.local` (vẫn dùng hostname được)

### **Cách 2: Kết nối WiFi mới tại chỗ (nếu có màn hình + bàn phím)**

Nếu mang theo HDMI + USB hub trên Pi, có thể kết nối WiFi qua GUI:
- Desktop → WiFi icon (góc trên cùng) → chọn mạng → nhập password

Hoặc dùng `nmtui` (text-based):
```bash
nmtui
```

### **Cách 3: USB-C to Ethernet (không cần WiFi)**

Khi không có WiFi nào khả dụng:

1. Mua **USB-C to Ethernet adapter** (≈ 150k, phải hỗ trợ Power Delivery cho Pi 5)
2. Cắm cáp mạng LAN vào adapter → cắm vào Pi 5
3. Pi sẽ nhận IP qua DHCP (192.168.x.x)
4. Tìm IP:
```powershell
arp -a | findstr /I "raspberry\|pi\|elderlycare"
# hoặc quét toàn bộ mạng (cần cài nmap trước)
nmap -sn 192.168.1.0/24
```
5. SSH: `ssh huy@<IP-tìm-được>`

**Ưu điểm:** Ổn định, không phụ thuộc WiFi, vẫn có internet qua LAN

### **Cách 4: Pi thành WiFi Access Point (phát WiFi)**

Pi **phát** WiFi thay vì **kết nối** WiFi — bạn kết nối vào Pi (offline):

```bash
sudo apt install -y hostapd dnsmasq
sudo nano /etc/hostapd/hostapd.conf
```

Thêm:
```ini
interface=wlan0
driver=nl80211
ssid=ElderlyCare-Pi-AP
hw_mode=g
channel=6
wpa=2
wpa_passphrase=your_secure_password
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
```

```bash
sudo systemctl enable hostapd
sudo systemctl restart hostapd
```

Từ laptop Windows, kết nối vào WiFi `ElderlyCare-Pi-AP` → SSH:
```powershell
ssh huy@192.168.4.1  # IP mặc định của Pi khi chế độ AP
```

**Nhưng nhược điểm:** Pi không kết nối internet nữa (chỉ local network với laptop)

---

### **🎯 Recommendation cho use case của bạn:**

**Nếu di chuyển thường xuyên:** Dùng **Cách 1** (thêm sẵn WiFi) + **Mobile Hotspot laptop**
- Đơn giản, không cần phần cứng thêm, vẫn có internet
- Pi tự kết nối, SSH từ Windows như bình thường

**Nếu không có WiFi nào có sẵn:** Dùng **Cách 3** (USB-C Ethernet)
- Ổn định, không phụ thuộc WiFi
- Chi phí adapter ≈ 150k

**Nếu muốn offline (không cần internet):** Dùng **Cách 4** (Pi Access Point)
- Pi phát WiFi, laptop kết nối vào
- Chỉ local network, không internet

---

## 4. Bật và cấu hình VNC trên Pi 5

Raspberry Pi OS Bookworm dùng **Wayland + WayVNC** mặc định (không phải RealVNC Server cũ).

### Cách 1: Dùng raspi-config (đơn giản)

```bash
sudo raspi-config
```

- `3 Interface Options` → `I3 VNC` → **Yes** để bật
- `6 Advanced Options` → `A6 Wayland` → chọn `W1 X11` (để dùng RealVNC tương thích tốt hơn) hoặc giữ Wayland nếu dùng WayVNC
- `1 System Options` → `S5 Boot / Auto Login` → `B4 Desktop Autologin`
- `2 Display Options` → `D5 VNC Resolution` → chọn `1280x720` hoặc `1920x1080`
- **Finish** → reboot

### Cách 2: Cài RealVNC Server (nếu muốn dùng VNC Viewer của RealVNC)

```bash
sudo apt install -y realvnc-vnc-server
sudo systemctl enable vncserver-x11-serviced
sudo systemctl start vncserver-x11-serviced
```

Đặt mật khẩu VNC:
```bash
sudo vncpasswd -service
```

### Kiểm tra VNC đã chạy

```bash
sudo systemctl status vncserver-x11-serviced
# hoặc với WayVNC:
sudo systemctl status wayvnc
```

---

## 5. Kết nối từ máy Windows qua VNC Viewer

1. Mở **RealVNC Viewer** trên Windows
2. Nhập địa chỉ: `elderlycare-pi.local:5900` (hoặc IP của Pi)
3. Nhập username/password đã đặt
4. Màn hình desktop Pi 5 hiện ra

**Lưu ý:** nếu Pi không có HDMI cắm, mặc định độ phân giải sẽ bé tí. Fix bằng cách thiết lập độ phân giải ảo:

```bash
sudo nano /boot/firmware/cmdline.txt
```

Thêm vào cuối dòng (không xuống dòng):
```
video=HDMI-A-1:1920x1080@60D
```

Reboot: `sudo reboot`

---

## 6. Cài đặt môi trường Python cho ElderlyCareModel

### Clone code

```bash
cd ~
git clone <URL-repo-của-bạn> ElderlyCareModel
cd ElderlyCareModel
```

Nếu repo private, dùng SSH key hoặc Personal Access Token.

### Tạo virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
```

### Cài dependencies

```bash
pip install -r requirements.txt
```

**Lưu ý cho Pi 5:** nếu project có `numpy`, `scipy`, `scikit-learn`, `tensorflow`, nên cài bản pre-built ARM64:

```bash
sudo apt install -y python3-numpy python3-scipy python3-sklearn libatlas-base-dev
```

Nếu có TFLite (suy luận inference cho stress/ectopy):
```bash
pip install tflite-runtime
```

### Cài MQTT broker (cho vai trò Wearer)

```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Test: `mosquitto_sub -t test &` rồi `mosquitto_pub -t test -m "hello"`

---

## 7. Deploy code từ Windows lên Pi 5

### Cách 1: Git pull (khuyến nghị)

Push code từ Windows lên GitHub/GitLab, rồi trên Pi:
```bash
cd ~/ElderlyCareModel
git pull
```

### Cách 2: SCP đẩy thẳng

Từ PowerShell trên Windows:
```powershell
scp -r C:\Users\huyma\Desktop\ElderlyCareModel\src huy@elderlycare-pi.local:~/ElderlyCareModel/
```

### Cách 3: rsync (đồng bộ delta, nhanh hơn)

Cài rsync trong WSL hoặc Git Bash trên Windows:
```bash
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    /c/Users/huyma/Desktop/ElderlyCareModel/ \
    huy@elderlycare-pi.local:~/ElderlyCareModel/
```

### Cách 4: VS Code Remote SSH (tiện nhất khi dev)

1. Cài extension **Remote - SSH** trên VS Code
2. `Ctrl+Shift+P` → `Remote-SSH: Connect to Host` → `huy@elderlycare-pi.local`
3. Mở thư mục `~/ElderlyCareModel` — chỉnh sửa và chạy trực tiếp trên Pi

---

## 8. Chạy hệ thống

### Test thủ công (qua SSH hoặc VNC terminal)

```bash
cd ~/ElderlyCareModel
source .venv/bin/activate
python3 -m src.main --role wearer
```

### Tự động chạy khi boot (systemd service)

Tạo file service:
```bash
sudo nano /etc/systemd/system/elderlycare.service
```

Nội dung:
```ini
[Unit]
Description=ElderlyCare Wearer Service
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
Type=simple
User=huy
WorkingDirectory=/home/huy/ElderlyCareModel
Environment="PATH=/home/huy/ElderlyCareModel/.venv/bin"
ExecStart=/home/huy/ElderlyCareModel/.venv/bin/python -m src.main --role wearer
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Kích hoạt:
```bash
sudo systemctl daemon-reload
sudo systemctl enable elderlycare.service
sudo systemctl start elderlycare.service
sudo systemctl status elderlycare.service
```

Xem log realtime:
```bash
journalctl -u elderlycare.service -f
```

---

## 9. Troubleshooting thường gặp

| Vấn đề | Cách xử lý |
|---|---|
| VNC kết nối được nhưng màn hình đen | Bật `Desktop Autologin` trong raspi-config; nếu dùng Wayland đổi sang X11 |
| `Cannot currently show the desktop` | Pi không có HDMI → cần set `video=HDMI-A-1:1920x1080@60D` trong cmdline.txt |
| Pi 5 throttle / tắt đột ngột | Nguồn yếu — phải dùng adapter 5V/5A chính hãng |
| `pip install` báo lỗi build | `sudo apt install python3-dev libffi-dev libssl-dev` |
| Không ping được `*.local` | Cài Bonjour trên Windows hoặc dùng IP trực tiếp; check qua `arp -a` |
| Service không start | `journalctl -u elderlycare -n 100` xem lỗi chi tiết |
| GPIO/I2C cho cảm biến không hoạt động | `sudo raspi-config` → Interface → bật I2C/SPI/Serial |

---

## 10. Checklist hoàn thành

- [ ] Pi boot được và SSH vào được qua hostname
- [ ] VNC Viewer kết nối thấy desktop ở độ phân giải mong muốn
- [ ] `git pull` hoặc `scp` đẩy được code lên `~/ElderlyCareModel`
- [ ] `python -m src.main` chạy không lỗi import
- [ ] Mosquitto broker `active (running)`
- [ ] systemd service tự khởi động sau `sudo reboot`
- [ ] Log không có lỗi sau 5 phút chạy
