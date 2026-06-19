# Truy cập từ xa cho người giám sát (Production) — Tailscale

Tài liệu này mô tả cách chuẩn (production) để **người giám sát ở khác mạng Wi-Fi/từ xa**
theo dõi Raspberry Pi qua app Flutter, dùng **Tailscale**.

## Vì sao chọn Tailscale

Backend chạy trên Pi đặt tại nhà người dùng (sau NAT/CGNAT, IP động, không có cloud
server). Tailscale là phương án tối ưu cho bối cảnh này:

- **Chạy sau mọi NAT/CGNAT** — kết nối outbound, **không cần port-forward / cấu hình router**.
- **Địa chỉ ổn định** (IP `100.x` hoặc tên MagicDNS) — sống qua reboot, đổi IP, đổi Wi-Fi nhà.
- **Mã hoá end-to-end (WireGuard)**, **không expose Pi ra public Internet** — chỉ thiết bị
  trong tailnet thấy được Pi. Phù hợp dữ liệu ECG (PII y tế).
- **Miễn phí** ở quy mô gia đình/đồ án, cài 1 lệnh.

Đánh đổi: máy người giám sát phải cài app Tailscale và join cùng tailnet. Với tập caregiver
biết trước, đây là một lớp bảo mật, không phải bất tiện.

> Nếu cần "chỉ nhập URL, không cài gì trên máy giám sát", dùng Cloudflare Tunnel thay thế
> (public HTTPS endpoint + bắt buộc API key). Không nằm trong tài liệu này.

## 1. Chuẩn bị (1 lần, trên tài khoản Tailscale)

1. Tạo tài khoản tại https://tailscale.com và đăng nhập admin console.
2. Vào **Settings → Keys → Generate auth key**:
   - Bật **Reusable** nếu sẽ cài nhiều Pi.
   - Nên đặt **Expiry** hợp lý và (tùy chọn) gắn tag.
   - Copy key dạng `tskey-auth-xxxxxxxx`.
3. Bật **MagicDNS** trong admin console (DNS → MagicDNS) để dùng tên thay vì IP.

## 2. Cài trên Raspberry Pi (sau install_pi_production.sh)

```bash
cd /home/elcaprj/elderly_care
sudo TAILSCALE_AUTHKEY=tskey-auth-xxxx \
     TAILSCALE_HOSTNAME=elderlycare-pi-001 \
     bash scripts/setup_tailscale_pi.sh
```

- `TAILSCALE_HOSTNAME`: đặt tên **ổn định, duy nhất cho mỗi Pi** (vd theo người dùng).
- Script sẽ in ra địa chỉ cần nhập vào app, ví dụ:
  - `http://elderlycare-pi-001.<tailnet>.ts.net:8000` (ưu tiên — không đổi khi IP đổi)
  - `http://100.x.y.z:8000`

Nếu không truyền `TAILSCALE_AUTHKEY`, script chuyển sang đăng nhập tương tác và in URL để
mở trên trình duyệt authorize Pi một lần.

> Bắt buộc giữ `API_AUTH_ENABLED=1` và `API_KEY=<chuỗi bí mật dài>` trong `.env`.

## 3. Cài trên máy người giám sát

1. Cài app **Tailscale** (iOS/Android/desktop), đăng nhập **cùng tài khoản/tailnet** với Pi
   (hoặc được mời vào tailnet đó).
2. Bật Tailscale (trạng thái Connected).

## 4. Cấu hình trong app Flutter (role Người giám sát)

1. Chọn vai trò **Người giám sát**.
2. **Địa chỉ Pi / Server**: nhập địa chỉ Tailscale của Pi, ưu tiên tên MagicDNS:
   ```
   http://elderlycare-pi-001.<tailnet>.ts.net:8000
   ```
   (hoặc `http://100.x.y.z:8000`). Luôn nhập **đầy đủ scheme** `http://` và cổng `:8000`.
3. **API key backend**: nhập đúng `API_KEY` đã cấu hình trong `.env` của Pi.
4. Nhập tên người giám sát / người được theo dõi → Hoàn tất.
5. Vào **Settings → Test Connection**: kỳ vọng ✓ (200).

REST và WebSocket (`/ws/alerts`, `/ws/vitals`) đều đi qua Tailscale; app tự suy `ws://` từ
`http://` nên không cần cấu hình thêm.

## 5. Bảo mật

- `API_AUTH_ENABLED=1` + API key mạnh (đã có lớp VPN, nhưng giữ auth là defense-in-depth).
- Không commit `TAILSCALE_AUTHKEY`, `API_KEY`, MongoDB URI vào git/log.
- Thu hồi thiết bị qua admin console khi ngừng dùng (bàn giao Pi sang người khác).

## 6. Khắc phục sự cố

- `tailscale status` trên Pi để xem đã online chưa.
- `tailscale ip -4` để lấy lại IP nếu cần.
- App báo lỗi kết nối: kiểm tra (a) máy giám sát đã bật Tailscale và cùng tailnet chưa,
  (b) địa chỉ nhập có đủ `http://...:8000`, (c) API key đúng, (d) service backend đang chạy
  (`sudo systemctl status elderly-care`).
- Khác mạng nhưng vẫn fail: xác nhận cả hai thiết bị đều **Connected** trong Tailscale; thử
  IP `100.x` thay cho MagicDNS để loại trừ DNS.
