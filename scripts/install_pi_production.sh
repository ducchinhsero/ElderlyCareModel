#!/usr/bin/env bash
set -Eeuo pipefail

# One-shot production installer for Raspberry Pi.
# Run from the unpacked project:
#   bash scripts/install_pi_production.sh
#
# Optional overrides:
#   ELDERLY_CARE_HOSTNAME=elderlycare POLAR_H10_MAC=AA:BB:CC:DD:EE:FF bash scripts/install_pi_production.sh

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_USER="${ELDERLY_CARE_USER:-$(stat -c '%U' "$PROJECT_DIR")}"
if [[ "$PROJECT_USER" == "root" && -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  PROJECT_USER="$SUDO_USER"
fi
PROJECT_GROUP="$(id -gn "$PROJECT_USER")"
HOSTNAME_TARGET="${ELDERLY_CARE_HOSTNAME:-elderlycare}"
ENV_FILE="$PROJECT_DIR/.env"
PYTHON_BIN="${PYTHON_BIN:-python3}"
START_SERVICES="${START_SERVICES:-1}"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || fail "This installer must run on Raspberry Pi/Linux."
  command -v sudo >/dev/null 2>&1 || fail "sudo is required."
  id "$PROJECT_USER" >/dev/null 2>&1 || fail "Project user '$PROJECT_USER' does not exist."
}

set_env() {
  local key="$1"
  local value="$2"
  local escaped
  escaped="${value//\\/\\\\}"
  escaped="${escaped//&/\\&}"
  escaped="${escaped//|/\\|}"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${escaped}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

set_env_default() {
  local key="$1"
  local value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    set_env "$key" "$value"
  fi
}

generate_ap_password() {
  "$PROJECT_DIR/.venv/bin/python" - <<'PY'
import secrets
print("EC-" + secrets.token_urlsafe(14)[:18])
PY
}

install_system_packages() {
  log "Installing Raspberry Pi system packages"
  sudo apt-get update
  sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    build-essential gfortran pkg-config \
    libopenblas-dev libffi-dev libssl-dev libgomp1 \
    bluetooth bluez libbluetooth-dev rfkill \
    network-manager wireless-tools dnsmasq-base \
    avahi-daemon mosquitto mosquitto-clients \
    sqlite3 unzip git curl htop
}

configure_hostname_and_mdns() {
  log "Configuring hostname and mDNS: ${HOSTNAME_TARGET}.local"
  if [[ "$(hostname)" != "$HOSTNAME_TARGET" ]]; then
    sudo hostnamectl set-hostname "$HOSTNAME_TARGET"
  fi
  sudo systemctl enable --now avahi-daemon
}

enable_base_services() {
  log "Enabling base services"
  sudo systemctl enable --now bluetooth
  sudo systemctl enable --now NetworkManager
  sudo systemctl enable --now mosquitto || true
  sudo rfkill unblock bluetooth || true
  sudo rfkill unblock wifi || true
}

setup_python_environment() {
  log "Creating/updating Python virtual environment"
  "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
  "$PROJECT_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$PROJECT_DIR/.venv/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"
}

setup_env_file() {
  log "Creating/updating .env"
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
  fi

  set_env_default "ECG_DATA_DIR" "./data"
  set_env_default "API_HOST" "0.0.0.0"
  set_env_default "API_PORT" "8000"
  set_env_default "POLAR_AUTO_START" "1"
  set_env_default "POLAR_AUTO_START_CHUNK_SECONDS" "10"
  set_env_default "POLAR_ENABLE_HR_STREAM" "${POLAR_ENABLE_HR_STREAM:-1}"
  set_env_default "POLAR_ENABLE_ACC_STREAM" "${POLAR_ENABLE_ACC_STREAM:-1}"
  set_env_default "POLAR_CONNECT_TIMEOUT_SECONDS" "${POLAR_CONNECT_TIMEOUT_SECONDS:-20}"
  set_env_default "POLAR_RECONNECT_SECONDS" "${POLAR_RECONNECT_SECONDS:-10}"
  set_env_default "LATEST_RESULT_FRESH_SECONDS" "90"
  set_env_default "WIFI_PROVISIONING_STATUS_PATH" "/run/elderly-care/network_status.json"
  set_env_default "WIFI_PROVISIONING_STATE_DIR" "/var/lib/elderly-care/wifi_provisioning"
  set_env_default "WIFI_SETUP_TRIGGER_PATH" "/var/lib/elderly-care/wifi_setup_mode"
  set_env_default "MQTT_ENABLED" "1"
  set_env_default "MQTT_HOST" "localhost"

  if [[ -n "${POLAR_H10_MAC:-}" ]]; then
    set_env "POLAR_H10_MAC" "$POLAR_H10_MAC"
  fi

  for optional_key in \
    MONGODB_URI MONGODB_SYNC_ENABLED MONGODB_DB \
    API_KEY API_AUTH_ENABLED \
    MQTT_HOST MQTT_PORT MQTT_USERNAME MQTT_PASSWORD; do
    if [[ -n "${!optional_key:-}" ]]; then
      set_env "$optional_key" "${!optional_key}"
    fi
  done

  if ! grep -q '^WIFI_AP_PASSWORD=.\{8,\}' "$ENV_FILE"; then
    set_env "WIFI_AP_PASSWORD" "$(generate_ap_password)"
  fi
}

prepare_directories() {
  log "Preparing data/log/state directories"
  mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/logs"
  sudo mkdir -p /run/elderly-care /var/lib/elderly-care/wifi_provisioning
  sudo chown -R "$PROJECT_USER:$PROJECT_GROUP" "$PROJECT_DIR/data" "$PROJECT_DIR/logs" "$ENV_FILE"
  sudo chmod 600 "$ENV_FILE"
}

install_unit() {
  local source="$1"
  local target="$2"
  local escaped_project_dir
  escaped_project_dir="${PROJECT_DIR//\\/\\\\}"
  escaped_project_dir="${escaped_project_dir//&/\\&}"
  escaped_project_dir="${escaped_project_dir//|/\\|}"
  sed \
    -e "s|/home/elcaprj/elderly_care|${escaped_project_dir}|g" \
    -e "s|^User=.*|User=${PROJECT_USER}|g" \
    -e "s|^Group=.*|Group=${PROJECT_GROUP}|g" \
    "$source" | sudo tee "$target" >/dev/null
}

setup_systemd_services() {
  log "Installing systemd services"
  install_unit "$PROJECT_DIR/deploy/systemd/elderly-care.service" \
    "/etc/systemd/system/elderly-care.service"
  install_unit "$PROJECT_DIR/deploy/systemd/elderly-care-wifi-provisioner.service" \
    "/etc/systemd/system/elderly-care-wifi-provisioner.service"

  sudo systemctl daemon-reload
  sudo systemctl enable elderly-care
  sudo systemctl enable elderly-care-wifi-provisioner

  if [[ "$START_SERVICES" == "1" ]]; then
    sudo systemctl restart elderly-care
    sudo systemctl restart elderly-care-wifi-provisioner
  fi
}

smoke_test() {
  if [[ "$START_SERVICES" != "1" ]]; then
    return
  fi
  log "Waiting for backend health endpoint"
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:8000/health" >/dev/null; then
      log "Backend health OK"
      return
    fi
    sleep 2
  done
  echo "Backend did not answer /health yet. Check: sudo journalctl -u elderly-care -n 100 --no-pager" >&2
}

print_summary() {
  local ap_password
  ap_password="$(grep '^WIFI_AP_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
  cat <<EOF

Production setup complete.

Local backend:
  http://127.0.0.1:8000/health

LAN/app backend:
  http://${HOSTNAME_TARGET}.local:8000

Setup Wi-Fi AP:
  SSID prefix: ElderlyCare-Setup-XXXX
  Password:    ${ap_password}
  Portal:      http://10.42.0.1

Useful checks:
  systemctl status elderly-care --no-pager
  systemctl status elderly-care-wifi-provisioner --no-pager
  journalctl -u elderly-care -f
  curl http://127.0.0.1:8000/health

If the hostname was changed, reboot once if ${HOSTNAME_TARGET}.local is not visible immediately:
  sudo reboot
EOF
}

main() {
  require_linux
  install_system_packages
  configure_hostname_and_mdns
  enable_base_services
  setup_python_environment
  setup_env_file
  prepare_directories
  setup_systemd_services
  smoke_test
  print_summary
}

main "$@"
