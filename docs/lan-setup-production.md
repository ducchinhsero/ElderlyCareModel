# Production LAN setup cho Raspberry Pi

Ngay cap nhat: 2026-06-01

Tai lieu nay mo ta cach dua Raspberry Pi sang nha nguoi dung moi bang Ethernet LAN, khong dung Wi-Fi AP/captive portal.

## Mo hinh

```mermaid
flowchart LR
  A["Cam Raspberry Pi vao router bang Ethernet"] --> B["Router cap IP DHCP"]
  B --> C["Backend chay tren 0.0.0.0:8000"]
  C --> D["App nhap IP hoac quet LAN"]
  D --> E["GET http://IP:8000/health"]
  E --> F["Dashboard / alerts / history"]
```

## Cai dat tren Raspberry Pi

Backend service van chay nhu cu, nhung can bind ra LAN:

```bash
uvicorn pipeline:app --host 0.0.0.0 --port 8000 --app-dir .
```

Khi dung systemd, `ExecStart` cung phai co:

```text
--host 0.0.0.0 --port 8000
```

Khuyen nghi dat DHCP reservation tren router de Raspberry luon nhan cung mot IP.

## Kiem tra tren Pi

```bash
ip addr show eth0
curl http://127.0.0.1:8000/health
```

Trong `/health` can co:

```json
{
  "network_setup": {
    "mode": "lan",
    "setup_method": "router_dhcp",
    "lan_addresses": ["http://10.10.56.149:8000"]
  }
}
```

Field `network_provisioning` van duoc giu tam thoi nhu alias de app/test cu khong vo, nhung khong con dieu khien Wi-Fi.

## Cau hinh app

1. Cam Raspberry vao router/switch bang day LAN.
2. Mo app -> Ket noi Raspberry qua LAN.
3. Nhap IP Raspberry, vi du `10.10.56.149`, hoac bam quet LAN.
4. Bam kiem tra ket noi. App se goi:

```text
http://<raspberry-ip>:8000/health
```

Neu thanh cong, app luu IP nay lam gateway noi bo.

## Gioi han v1

- Khong ho tro direct Ethernet PC-Pi bang static IP.
- Khong dieu khien Wi-Fi `wlan0` tu app/backend.
- Neu can Wi-Fi, cau hinh ngoai app bang OS/router/admin.
