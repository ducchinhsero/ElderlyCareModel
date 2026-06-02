import argparse
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.config.env_loader import load_env_file


DEFAULT_SETUP_IP = "10.42.0.1"
DEFAULT_AP_PREFIX = "ElderlyCare-Setup"
DEFAULT_AP_CONNECTION_NAME = "elderly-care-setup-ap"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _default_data_dir():
    return Path(os.getenv("ECG_DATA_DIR") or "dataset/realtime_logs")


def _env(name, default=None):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def network_status_path():
    return Path(
        _env(
            "WIFI_PROVISIONING_STATUS_PATH",
            str(_default_data_dir() / "network_status.json"),
        )
    )


def read_network_status(path=None):
    status_path = Path(path) if path else network_status_path()
    if not status_path.exists():
        return {
            "mode": "unknown",
            "internet_reachable": False,
            "last_error": None,
            "updated_at": None,
            "status_path": str(status_path),
        }
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "mode": "unknown",
            "internet_reachable": False,
            "last_error": f"cannot_read_status: {exc}",
            "updated_at": None,
            "status_path": str(status_path),
        }
    payload.setdefault("status_path", str(status_path))
    return payload


@dataclass
class ProvisioningConfig:
    interface: str = "wlan0"
    setup_ip: str = DEFAULT_SETUP_IP
    ap_ssid_prefix: str = DEFAULT_AP_PREFIX
    ap_connection_name: str = DEFAULT_AP_CONNECTION_NAME
    ap_password: str | None = None
    state_dir: Path = _default_data_dir() / "wifi_provisioning"
    status_path: Path = network_status_path()
    portal_host: str = "0.0.0.0"
    portal_port: int = 80
    check_host: str = "1.1.1.1"
    check_port: int = 443
    connect_timeout_seconds: int = 25
    monitor_interval_seconds: int = 60
    setup_trigger_path: Path = _default_data_dir() / "wifi_setup_mode"

    @classmethod
    def from_env(cls):
        data_dir = _default_data_dir()
        return cls(
            interface=_env("WIFI_INTERFACE", "wlan0"),
            setup_ip=_env("WIFI_SETUP_IP", DEFAULT_SETUP_IP),
            ap_ssid_prefix=_env("WIFI_AP_SSID_PREFIX", DEFAULT_AP_PREFIX),
            ap_connection_name=_env("WIFI_AP_CONNECTION_NAME", DEFAULT_AP_CONNECTION_NAME),
            ap_password=_env("WIFI_AP_PASSWORD") or None,
            state_dir=Path(_env("WIFI_PROVISIONING_STATE_DIR", str(data_dir / "wifi_provisioning"))),
            status_path=network_status_path(),
            portal_host=_env("WIFI_PORTAL_HOST", "0.0.0.0"),
            portal_port=int(_env("WIFI_PORTAL_PORT", "80")),
            check_host=_env("WIFI_INTERNET_CHECK_HOST", "1.1.1.1"),
            check_port=int(_env("WIFI_INTERNET_CHECK_PORT", "443")),
            connect_timeout_seconds=int(_env("WIFI_CONNECT_TIMEOUT_SECONDS", "25")),
            monitor_interval_seconds=int(_env("WIFI_MONITOR_INTERVAL_SECONDS", "60")),
            setup_trigger_path=Path(_env("WIFI_SETUP_TRIGGER_PATH", str(data_dir / "wifi_setup_mode"))),
        )


class CommandRunner:
    def run(self, args, check=True, timeout=30):
        return subprocess.run(
            args,
            check=check,
            timeout=timeout,
            text=True,
            capture_output=True,
        )


class NetworkProvisioner:
    def __init__(self, config=None, runner=None, sleep=time.sleep):
        self.config = config or ProvisioningConfig.from_env()
        self.runner = runner or CommandRunner()
        self.sleep = sleep
        self._last_error = None

    def write_status(self, mode, **extra):
        payload = {
            "mode": mode,
            "interface": self.config.interface,
            "setup_ssid": self.ap_ssid(),
            "setup_ip": self.config.setup_ip,
            "internet_reachable": bool(extra.pop("internet_reachable", False)),
            "connected_ssid": extra.pop("connected_ssid", None),
            "last_error": extra.pop("last_error", self._last_error),
            "updated_at": utc_now_iso(),
            **extra,
        }
        self.config.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def ap_ssid(self):
        suffix = self._wifi_mac_suffix()
        return f"{self.config.ap_ssid_prefix}-{suffix}" if suffix else self.config.ap_ssid_prefix

    def ap_password(self):
        if self.config.ap_password:
            return self.config.ap_password
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        password_path = self.config.state_dir / "ap_password"
        if password_path.exists():
            return password_path.read_text(encoding="utf-8").strip()
        password = secrets.token_urlsafe(12)
        password_path.write_text(password, encoding="utf-8")
        try:
            os.chmod(password_path, 0o600)
        except OSError:
            pass
        return password

    def _wifi_mac_suffix(self):
        mac_path = Path(f"/sys/class/net/{self.config.interface}/address")
        try:
            mac = mac_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return mac.replace(":", "")[-4:].upper()

    def _run_nmcli(self, *args, check=True, timeout=30):
        return self.runner.run(["nmcli", *args], check=check, timeout=timeout)

    def internet_reachable(self):
        try:
            with socket.create_connection(
                (self.config.check_host, self.config.check_port),
                timeout=3,
            ):
                return True
        except OSError:
            return False

    def active_wifi_connection(self):
        result = self._run_nmcli(
            "-t",
            "-f",
            "DEVICE,TYPE,STATE,CONNECTION",
            "device",
            "status",
            check=False,
        )
        for line in (result.stdout or "").splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] == self.config.interface and parts[1] == "wifi":
                state = parts[2]
                connection = ":".join(parts[3:]) or None
                return {"state": state, "connection": connection}
        return {"state": "unknown", "connection": None}

    def known_wifi_connections(self):
        result = self._run_nmcli(
            "-t",
            "-f",
            "NAME,TYPE",
            "connection",
            "show",
            check=False,
        )
        connections = []
        for line in (result.stdout or "").splitlines():
            if not line:
                continue
            name, _, conn_type = line.partition(":")
            if conn_type in {"802-11-wireless", "wifi"} and name != self.config.ap_connection_name:
                connections.append(name.replace("\\:", ":"))
        return connections

    def scan_wifi(self):
        result = self._run_nmcli(
            "-t",
            "-f",
            "SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            self.config.interface,
            "--rescan",
            "yes",
            check=False,
            timeout=20,
        )
        networks = []
        seen = set()
        for line in (result.stdout or "").splitlines():
            parts = _split_nmcli_line(line)
            if not parts or not parts[0]:
                continue
            ssid = parts[0]
            if ssid in seen:
                continue
            seen.add(ssid)
            networks.append(
                {
                    "ssid": ssid,
                    "signal": _safe_int(parts[1] if len(parts) > 1 else None),
                    "security": parts[2] if len(parts) > 2 else "",
                }
            )
        networks.sort(key=lambda item: item.get("signal") or 0, reverse=True)
        return networks

    def ensure_client_mode(self):
        active = self.active_wifi_connection()
        if active.get("state") == "connected" and self.internet_reachable():
            return self.write_status(
                "client",
                internet_reachable=True,
                connected_ssid=active.get("connection"),
            )

        for connection in self.known_wifi_connections():
            self._run_nmcli(
                "connection",
                "up",
                connection,
                "ifname",
                self.config.interface,
                check=False,
                timeout=self.config.connect_timeout_seconds,
            )
            self.sleep(2)
            active = self.active_wifi_connection()
            if active.get("state") == "connected" and self.internet_reachable():
                self.stop_ap()
                return self.write_status(
                    "client",
                    internet_reachable=True,
                    connected_ssid=active.get("connection"),
                )

        active = self.active_wifi_connection()
        if active.get("state") == "connected":
            return self.write_status(
                "offline",
                internet_reachable=False,
                connected_ssid=active.get("connection"),
                last_error="wifi_connected_but_internet_unreachable",
            )
        return self.write_status(
            "offline",
            internet_reachable=False,
            last_error="no_known_wifi_connected",
        )

    def start_ap(self):
        password = self.ap_password()
        if len(password) < 8:
            raise ValueError("WIFI_AP_PASSWORD must be at least 8 characters for WPA2.")
        self._run_nmcli(
            "device",
            "wifi",
            "hotspot",
            "ifname",
            self.config.interface,
            "con-name",
            self.config.ap_connection_name,
            "ssid",
            self.ap_ssid(),
            "password",
            password,
            check=True,
            timeout=30,
        )
        return self.write_status(
            "ap",
            internet_reachable=False,
            portal_url=f"http://{self.config.setup_ip}",
        )

    def stop_ap(self):
        self._run_nmcli(
            "connection",
            "down",
            self.config.ap_connection_name,
            check=False,
            timeout=15,
        )

    def connect_wifi(self, ssid, password):
        ssid = str(ssid or "").strip()
        if not ssid:
            raise ValueError("ssid is required.")
        self.write_status("connecting", internet_reachable=False, connected_ssid=ssid)
        self.stop_ap()
        self.sleep(4)
        self._run_nmcli("device", "wifi", "rescan", "ifname", self.config.interface, check=False, timeout=25)
        self.sleep(4)
        self._run_nmcli("connection", "delete", ssid, check=False, timeout=15)
        add_args = [
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            self.config.interface,
            "con-name",
            ssid,
            "ssid",
            ssid,
        ]
        if password:
            add_args.extend(["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", str(password)])
        add_result = self._run_nmcli(*add_args, check=False, timeout=20)
        if add_result.returncode != 0:
            self._last_error = (add_result.stderr or add_result.stdout or "wifi_profile_add_failed").strip()
            self.start_ap()
            return self.write_status(
                "ap",
                internet_reachable=False,
                last_error=self._last_error,
                attempted_ssid=ssid,
            )
        result = self._run_nmcli(
            "connection",
            "up",
            ssid,
            "ifname",
            self.config.interface,
            check=False,
            timeout=self.config.connect_timeout_seconds,
        )
        if result.returncode != 0:
            self._last_error = (result.stderr or result.stdout or "wifi_connect_failed").strip()
            self.start_ap()
            return self.write_status(
                "ap",
                internet_reachable=False,
                last_error=self._last_error,
                attempted_ssid=ssid,
            )
        self.sleep(3)
        if not self.internet_reachable():
            self._last_error = "wifi_connected_but_internet_unreachable"
            return self.write_status(
                "offline",
                internet_reachable=False,
                connected_ssid=ssid,
                last_error=self._last_error,
            )
        self._last_error = None
        return self.write_status(
            "client",
            internet_reachable=True,
            connected_ssid=ssid,
        )

    def trigger_setup_requested(self):
        return self.config.setup_trigger_path.exists()

    def clear_setup_trigger(self):
        try:
            self.config.setup_trigger_path.unlink()
        except FileNotFoundError:
            pass

    def run_boot_flow(self):
        if self.trigger_setup_requested():
            self.clear_setup_trigger()
            self.start_ap()
            return "ap"
        status = self.ensure_client_mode()
        if status["mode"] == "client":
            return "client"
        if status["mode"] == "offline" and status.get("connected_ssid"):
            return "offline"
        self.start_ap()
        return "ap"


def _split_nmcli_line(line):
    parts = []
    current = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


PORTAL_HTML = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Elderly Care Wi-Fi Setup</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #f4f7fb; color: #10213f; }
    main { max-width: 720px; margin: 0 auto; padding: 24px; }
    section { background: #fff; border: 1px solid #d8e1ef; border-radius: 12px; padding: 18px; margin-top: 16px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    label { display: block; font-weight: 650; margin: 14px 0 6px; }
    input, select, button { width: 100%; box-sizing: border-box; font-size: 16px; padding: 12px; border-radius: 8px; border: 1px solid #b9c7da; }
    button { border: 0; background: #1463ff; color: white; font-weight: 700; margin-top: 14px; }
    button.secondary { background: #eef3fb; color: #10213f; }
    .muted { color: #5c6f8d; }
    .status { white-space: pre-wrap; background: #edf7ef; border-radius: 8px; padding: 12px; }
  </style>
</head>
<body>
<main>
  <h1>Elderly Care Wi-Fi Setup</h1>
  <p class="muted">Chọn Wi-Fi nhà để Raspberry Pi chuyển sang chế độ giám sát và đồng bộ cloud.</p>
  <section>
    <h2>Trạng thái</h2>
    <div id="status" class="status">Đang tải...</div>
    <button class="secondary" onclick="loadStatus()">Làm mới trạng thái</button>
  </section>
  <section>
    <h2>Kết nối Wi-Fi</h2>
    <button class="secondary" onclick="scanWifi()">Quét mạng Wi-Fi</button>
    <label for="ssid">Tên Wi-Fi</label>
    <select id="ssid"></select>
    <label for="manual_ssid">Hoặc nhập SSID thủ công</label>
    <input id="manual_ssid" autocomplete="off">
    <label for="password">Mật khẩu Wi-Fi</label>
    <input id="password" type="password" autocomplete="current-password">
    <button onclick="connectWifi()">Kết nối</button>
    <p class="muted">Sau khi bấm kết nối, điện thoại có thể mất mạng setup. Hãy chuyển lại Wi-Fi nhà rồi mở app.</p>
  </section>
</main>
<script>
async function loadStatus() {
  const res = await fetch('/api/status');
  const data = await res.json();
  document.getElementById('status').textContent = JSON.stringify(data, null, 2);
}
async function scanWifi() {
  const res = await fetch('/api/wifi/scan');
  const data = await res.json();
  const select = document.getElementById('ssid');
  select.innerHTML = '';
  for (const item of data.networks || []) {
    const opt = document.createElement('option');
    opt.value = item.ssid;
    opt.textContent = `${item.ssid} (${item.signal || '?'}%) ${item.security || ''}`;
    select.appendChild(opt);
  }
}
async function connectWifi() {
  const selected = document.getElementById('ssid').value;
  const manual = document.getElementById('manual_ssid').value.trim();
  const password = document.getElementById('password').value;
  const ssid = manual || selected;
  const res = await fetch('/api/wifi/connect', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ssid, password})
  });
  const data = await res.json();
  document.getElementById('status').textContent = JSON.stringify(data, null, 2);
}
loadStatus();
scanWifi();
</script>
</body>
</html>
"""


class PortalServer:
    def __init__(self, provisioner):
        self.provisioner = provisioner

    def make_handler(self):
        provisioner = self.provisioner

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload, status=200):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_html(self, payload, status=200):
                data = payload.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self._send_cors_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_cors_headers(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def do_OPTIONS(self):
                self.send_response(204)
                self._send_cors_headers()
                self.end_headers()

            def do_GET(self):
                path = urlparse(self.path).path
                if path in {"/", "/index.html", "/generate_204", "/hotspot-detect.html"}:
                    self._send_html(PORTAL_HTML)
                    return
                if path == "/api/status":
                    self._send_json(read_network_status(provisioner.config.status_path))
                    return
                if path == "/api/wifi/scan":
                    try:
                        self._send_json({"networks": provisioner.scan_wifi()})
                    except Exception as exc:
                        self._send_json({"networks": [], "error": str(exc)}, status=500)
                    return
                self._send_html(PORTAL_HTML)

            def do_POST(self):
                path = urlparse(self.path).path
                if path != "/api/wifi/connect":
                    self._send_json({"error": "not_found"}, status=404)
                    return
                try:
                    payload = self._read_payload()
                    ssid = payload.get("ssid")
                    password = payload.get("password") or ""
                    if not ssid:
                        self._send_json({"ok": False, "error": "ssid is required"}, status=400)
                        return
                    provisioner.write_status("connecting", internet_reachable=False, connected_ssid=ssid)
                    threading.Thread(
                        target=_connect_after_response,
                        args=(provisioner, ssid, password),
                        daemon=True,
                    ).start()
                    self._send_json(
                        {
                            "ok": True,
                            "message": "Connecting. The setup Wi-Fi may disappear if credentials are correct.",
                            "ssid": ssid,
                        }
                    )
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=500)

            def _read_payload(self):
                content_type = self.headers.get("Content-Type", "")
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length else b""
                if "application/json" in content_type:
                    return json.loads(raw.decode("utf-8") or "{}")
                parsed = parse_qs(raw.decode("utf-8"))
                return {key: values[0] if values else "" for key, values in parsed.items()}

            def log_message(self, fmt, *args):
                print(f"{self.address_string()} - {fmt % args}")

        return Handler

    def serve_forever(self):
        server = ThreadingHTTPServer(
            (self.provisioner.config.portal_host, self.provisioner.config.portal_port),
            self.make_handler(),
        )
        print(
            "Wi-Fi setup portal running at "
            f"http://{self.provisioner.config.setup_ip}:{self.provisioner.config.portal_port}"
        )
        server.serve_forever()


def _connect_after_response(provisioner, ssid, password):
    time.sleep(2)
    try:
        provisioner.connect_wifi(ssid, password)
    except Exception as exc:
        provisioner.write_status("ap", internet_reachable=False, last_error=str(exc))
        try:
            provisioner.start_ap()
        except Exception:
            pass


def run_provisioner_service(config=None):
    provisioner = NetworkProvisioner(config=config)
    mode = provisioner.run_boot_flow()
    if mode == "ap":
        PortalServer(provisioner).serve_forever()
        return
    while True:
        status = provisioner.ensure_client_mode()
        if status.get("mode") != "client" and (
            provisioner.trigger_setup_requested() or not status.get("connected_ssid")
        ):
            provisioner.clear_setup_trigger()
            provisioner.start_ap()
            PortalServer(provisioner).serve_forever()
            return
        time.sleep(provisioner.config.monitor_interval_seconds)


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Elderly Care Wi-Fi provisioning service")
    parser.add_argument("--status", action="store_true", help="Print provisioning status and exit")
    parser.add_argument("--scan", action="store_true", help="Scan Wi-Fi networks and exit")
    parser.add_argument("--start-ap", action="store_true", help="Start setup AP and exit")
    parser.add_argument("--connect", metavar="SSID", help="Connect to a Wi-Fi SSID and exit")
    parser.add_argument("--password", default="", help="Wi-Fi password for --connect")
    args = parser.parse_args()

    provisioner = NetworkProvisioner()
    if args.status:
        print(json.dumps(read_network_status(provisioner.config.status_path), indent=2))
        return
    if args.scan:
        print(json.dumps({"networks": provisioner.scan_wifi()}, indent=2, ensure_ascii=False))
        return
    if args.start_ap:
        print(json.dumps(provisioner.start_ap(), indent=2, ensure_ascii=False))
        return
    if args.connect:
        print(json.dumps(provisioner.connect_wifi(args.connect, args.password), indent=2, ensure_ascii=False))
        return
    run_provisioner_service(provisioner.config)


if __name__ == "__main__":
    main()
