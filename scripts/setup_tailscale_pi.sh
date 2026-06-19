#!/usr/bin/env bash
set -Eeuo pipefail

# Production remote-access setup for the Elderly Care Pi using Tailscale.
#
# Why Tailscale: it works behind home NAT/CGNAT with no router/port-forward
# config, gives the Pi a stable address that survives reboots and Wi-Fi
# changes, encrypts traffic end-to-end (WireGuard), and never exposes the
# backend on the public Internet. Only devices in your tailnet can reach it.
#
# Run on the Raspberry Pi after install_pi_production.sh:
#   sudo TAILSCALE_AUTHKEY=tskey-auth-xxxx bash scripts/setup_tailscale_pi.sh
#
# Optional overrides:
#   TAILSCALE_HOSTNAME=elderlycare-pi-001   # stable MagicDNS name for this Pi
#   BACKEND_PORT=8000                        # must match the uvicorn port
#
# If TAILSCALE_AUTHKEY is not provided, the script falls back to interactive
# login and prints the URL you must open once to authorize the device.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
BACKEND_PORT="${BACKEND_PORT:-8000}"
TAILSCALE_HOSTNAME="${TAILSCALE_HOSTNAME:-elderlycare-pi}"
TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ "$(uname -s)" == "Linux" ]] || fail "This setup must run on the Raspberry Pi/Linux."
command -v sudo >/dev/null 2>&1 || fail "sudo is required."
command -v curl >/dev/null 2>&1 || fail "curl is required."

# Sanitize the hostname: Tailscale only accepts lowercase letters, digits and
# hyphens. Anything else becomes a hyphen.
TAILSCALE_HOSTNAME="$(echo "$TAILSCALE_HOSTNAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')"
[[ -n "$TAILSCALE_HOSTNAME" ]] || TAILSCALE_HOSTNAME="elderlycare-pi"

if ! command -v tailscale >/dev/null 2>&1; then
  log "Installing Tailscale (official script)..."
  curl -fsSL https://tailscale.com/install.sh | sh
else
  log "Tailscale already installed: $(tailscale version | head -n1)"
fi

log "Enabling tailscaled service..."
sudo systemctl enable --now tailscaled

log "Bringing the device up on the tailnet as '$TAILSCALE_HOSTNAME'..."
# --accept-dns=true lets the caregiver app reach the Pi by MagicDNS name.
# --ssh is intentionally NOT enabled; we only expose the backend port.
if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
  sudo tailscale up \
    --authkey="$TAILSCALE_AUTHKEY" \
    --hostname="$TAILSCALE_HOSTNAME" \
    --accept-dns=true
else
  log "No TAILSCALE_AUTHKEY provided — starting interactive login."
  log "Open the URL printed below on any browser to authorize this Pi, then re-run is not needed."
  sudo tailscale up \
    --hostname="$TAILSCALE_HOSTNAME" \
    --accept-dns=true
fi

# Give tailscaled a moment to settle and report the assigned address.
sleep 2
TS_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
TS_DNS="$(tailscale status --json 2>/dev/null | grep -oE '"DNSName"[^,]*' | head -n1 | sed -E 's/.*"DNSName":[[:space:]]*"([^"]+)".*/\1/; s/\.$//' || true)"

log "Tailscale is up."
echo "--------------------------------------------------------------------"
echo " Backend port            : ${BACKEND_PORT}"
echo " Tailscale IP (stable)   : ${TS_IP:-<pending - run 'tailscale ip -4'>}"
echo " MagicDNS name           : ${TS_DNS:-<enable MagicDNS in admin console>}"
echo ""
echo " Enter ONE of these in the app's 'Dia chi Pi / Server' field"
echo " (caregiver role), together with the backend API key:"
if [[ -n "$TS_IP" ]]; then
  echo "   http://${TS_IP}:${BACKEND_PORT}"
fi
if [[ -n "$TS_DNS" ]]; then
  echo "   http://${TS_DNS}:${BACKEND_PORT}    (preferred - survives IP changes)"
fi
echo "--------------------------------------------------------------------"

if [[ -f "$ENV_FILE" ]] && ! grep -qE '^API_AUTH_ENABLED=1' "$ENV_FILE"; then
  echo ""
  echo "WARNING: API_AUTH_ENABLED is not set to 1 in $ENV_FILE."
  echo "         For remote access you MUST enable API auth and set a strong API_KEY."
fi

log "Done. The caregiver device must also install Tailscale and join the same tailnet."
