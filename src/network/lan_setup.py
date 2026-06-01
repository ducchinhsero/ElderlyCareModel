"""LAN setup helpers for Raspberry Pi deployments."""

import os
import socket
import subprocess


DEFAULT_API_PORT = 8000


def _api_port():
    value = os.getenv("API_PORT") or os.getenv("PORT") or str(DEFAULT_API_PORT)
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_API_PORT


def _is_private_ipv4(address):
    try:
        parts = [int(part) for part in str(address).split(".")]
    except ValueError:
        return False
    if len(parts) != 4 or any(part < 0 or part > 255 for part in parts):
        return False
    a, b, _, _ = parts
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def _host_ipv4_addresses():
    addresses = set()
    hostname = socket.gethostname()
    candidates = {hostname, f"{hostname}.local"}
    try:
        candidates.update(socket.gethostbyname_ex(hostname)[2])
    except OSError:
        pass

    for candidate in candidates:
        try:
            infos = socket.getaddrinfo(candidate, None, family=socket.AF_INET)
        except OSError:
            continue
        for info in infos:
            address = info[4][0]
            if _is_private_ipv4(address):
                addresses.add(address)
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            check=False,
            timeout=2,
            text=True,
            capture_output=True,
        )
        for address in (result.stdout or "").split():
            if _is_private_ipv4(address):
                addresses.add(address)
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(addresses)


def read_lan_setup_status():
    port = _api_port()
    addresses = _host_ipv4_addresses()
    lan_urls = [f"http://{address}:{port}" for address in addresses]
    advertised_host = os.getenv("LAN_ADVERTISE_HOST", "").strip()
    if advertised_host:
        lan_urls.insert(0, f"http://{advertised_host}:{port}")

    return {
        "mode": "lan",
        "setup_method": "router_dhcp",
        "interface": "ethernet_or_lan",
        "lan_addresses": lan_urls,
        "internet_reachable": None,
        "last_error": None,
        "notes": [
            "Connect Raspberry Pi to the router or switch with Ethernet.",
            "Use one of the LAN addresses with /health to configure the app.",
        ],
    }
