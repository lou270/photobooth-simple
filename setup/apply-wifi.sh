#!/bin/bash
# Generate the access point configuration from config.ini.
#
# The booth shows guests a QR code built from the [WiFi] section of config.ini,
# while hostapd used to carry its own hard-coded copy of the same network name.
# Nothing kept the two in step, so renaming the network in one place handed out
# a QR code that joined a network no longer broadcast.
#
# This script removes that second copy: config.ini is the source of truth, and
# hostapd.conf is generated from it. Run it after changing the network name or
# passphrase - including through the admin page, which writes config.ini too.
#
#     ./setup/apply-wifi.sh [--dry-run] [--no-restart]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHOTOBOOTH_DIR="$(dirname "$SCRIPT_DIR")"
TEMPLATES="$SCRIPT_DIR/templates"

# shellcheck source=setup/lib.sh
source "$SCRIPT_DIR/lib.sh"

RESTART_SERVICES=true

usage() {
    sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)    DRY_RUN=true ;;
        --no-restart) RESTART_SERVICES=false ;;
        -h|--help)    usage; exit 0 ;;
        *) print_error "Unknown option: $1"; usage; exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# Inputs: the profile supplies the radio settings, config.ini the identity
# ---------------------------------------------------------------------------

if [ -f "$SCRIPT_DIR/booth.conf" ]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/booth.conf"
fi

WIFI_COUNTRY="${WIFI_COUNTRY:-FR}"
WIFI_CHANNEL="${WIFI_CHANNEL:-6}"
WIFI_LOG_QUERIES="${WIFI_LOG_QUERIES:-yes}"
WIFI_INTERFACE="${WIFI_INTERFACE:-}"

if [ ! -f "$PHOTOBOOTH_DIR/config.ini" ]; then
    print_error "config.ini not found. Run install.sh first, or copy config.ini.example."
    exit 1
fi

WIFI_SSID="$(booth_config WIFI_SSID)"
WIFI_PASSWORD="$(booth_config WIFI_PASSWORD)"
WIFI_HIDDEN="$(booth_config WIFI_HIDDEN)"
WIFI_AP_ADDRESS="$(booth_config WIFI_AP_ADDRESS)"
WEB_PORT="$(booth_config WEB_PORT)"

WIFI_INTERFACE="$(wlan_interface)" || {
    print_error "No wireless interface found. Set WIFI_INTERFACE in setup/booth.conf."
    exit 1
}

require_vars WIFI_SSID WIFI_AP_ADDRESS WIFI_INTERFACE WIFI_CHANNEL WIFI_COUNTRY WEB_PORT

# ---------------------------------------------------------------------------
# Validation - a bad value here is a booth that comes up with no network at all
# ---------------------------------------------------------------------------

if [ "${#WIFI_SSID}" -gt 32 ]; then
    print_error "WIFI_SSID is ${#WIFI_SSID} characters; the 802.11 limit is 32."
    exit 1
fi

if [ -n "$WIFI_PASSWORD" ] && { [ "${#WIFI_PASSWORD}" -lt 8 ] || [ "${#WIFI_PASSWORD}" -gt 63 ]; }; then
    print_error "WIFI_PASSWORD must be 8-63 characters for WPA2 (got ${#WIFI_PASSWORD})."
    print_info "Leave WIFI_PASSWORD empty in config.ini for an open network."
    exit 1
fi

if ! printf '%s' "$WIFI_AP_ADDRESS" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    print_error "WIFI_AP_ADDRESS is not an IPv4 address: $WIFI_AP_ADDRESS"
    exit 1
fi

# The DHCP pool lives on the access point's own /24, and must not contain the
# booth's address - dnsmasq would happily lease it to a phone.
AP_PREFIX="${WIFI_AP_ADDRESS%.*}"
AP_HOST="${WIFI_AP_ADDRESS##*.}"
DHCP_RANGE_START="${AP_PREFIX}.10"
DHCP_RANGE_END="${AP_PREFIX}.100"

if [ "$AP_HOST" -ge 10 ] && [ "$AP_HOST" -le 100 ]; then
    print_error "WIFI_AP_ADDRESS ($WIFI_AP_ADDRESS) sits inside the DHCP pool ${DHCP_RANGE_START}-${DHCP_RANGE_END}."
    print_info "Use an address below .10 (the default is ${AP_PREFIX}.1)."
    exit 1
fi

# ---------------------------------------------------------------------------
# Derived template fragments - envsubst has no conditionals, so the shell
# decides and passes finished blocks
# ---------------------------------------------------------------------------

if [ -n "$WIFI_PASSWORD" ]; then
    HOSTAPD_SECURITY="$(cat <<SECURITY
# WPA2 personal, passphrase from WIFI_PASSWORD in config.ini
wpa=2
wpa_passphrase=${WIFI_PASSWORD}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=CCMP
rsn_pairwise=CCMP
SECURITY
)"
else
    HOSTAPD_SECURITY="# Open network: WIFI_PASSWORD is empty in config.ini."
fi

if [ "$WIFI_HIDDEN" = "true" ]; then
    HOSTAPD_HIDDEN="# WIFI_HIDDEN is True in config.ini: the QR code is the only way in.
ignore_broadcast_ssid=1"
else
    HOSTAPD_HIDDEN="# Broadcast the SSID (WIFI_HIDDEN is False in config.ini)."
fi

if [ "$WIFI_LOG_QUERIES" = "yes" ]; then
    DNSMASQ_LOGGING="log-queries
log-dhcp"
else
    DNSMASQ_LOGGING="# Logging off (WIFI_LOG_QUERIES=no in setup/booth.conf)."
fi

export WIFI_INTERFACE WIFI_SSID WIFI_CHANNEL WIFI_COUNTRY WIFI_AP_ADDRESS
export WEB_PORT DHCP_RANGE_START DHCP_RANGE_END
export HOSTAPD_SECURITY HOSTAPD_HIDDEN DNSMASQ_LOGGING

print_info "Access point: SSID '${WIFI_SSID}' on ${WIFI_INTERFACE}, address ${WIFI_AP_ADDRESS}, channel ${WIFI_CHANNEL}/${WIFI_COUNTRY}"
if [ -n "$WIFI_PASSWORD" ]; then
    print_info "Security: WPA2"
else
    print_info "Security: open network"
fi

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

render "$TEMPLATES/hostapd.conf.tmpl" /etc/hostapd/hostapd.conf 0600
render "$TEMPLATES/default-hostapd.tmpl" /etc/default/hostapd 0644
render "$TEMPLATES/dnsmasq.conf.tmpl" /etc/dnsmasq.conf 0644
render "$TEMPLATES/photobooth-http-redirect.service.tmpl" /etc/systemd/system/photobooth-http-redirect.service 0644

if has_networkmanager; then
    render "$TEMPLATES/networkmanager-unmanaged.conf.tmpl" \
        "/etc/NetworkManager/conf.d/photobooth-unmanaged.conf" 0644
    render "$TEMPLATES/photobooth-ap-network.service.tmpl" \
        /etc/systemd/system/photobooth-ap-network.service 0644
    render "$TEMPLATES/hostapd-dropin.conf.tmpl" \
        /etc/systemd/system/hostapd.service.d/photobooth-ap.conf 0644
else
    # No NetworkManager: dhcpcd owns the interface, and the address is pinned
    # through a managed block instead of a unit.
    print_info "NetworkManager not present, pinning the address through dhcpcd"
    managed_block /etc/dhcpcd.conf "ap-address" <<DHCPCD
interface ${WIFI_INTERFACE}
    static ip_address=${WIFI_AP_ADDRESS}/24
    nohook wpa_supplicant
DHCPCD
fi

# ---------------------------------------------------------------------------
# Enable and restart
# ---------------------------------------------------------------------------

if ! has_systemd; then
    print_warning "No systemd here; configuration written but no service started."
    exit 0
fi

run sudo systemctl unmask hostapd
run sudo systemctl daemon-reload
run sudo systemctl enable hostapd dnsmasq photobooth-http-redirect.service
if has_networkmanager; then
    run sudo systemctl enable photobooth-ap-network.service
fi

if [ "$RESTART_SERVICES" != "true" ]; then
    print_info "Skipping service restart (--no-restart). Reboot or restart hostapd to apply."
    exit 0
fi

if has_networkmanager; then
    run sudo systemctl restart NetworkManager
    run sudo nmcli device set "$WIFI_INTERFACE" managed no || true
    run sudo systemctl restart photobooth-ap-network.service
else
    run sudo systemctl restart dhcpcd || true
fi

if ! run sudo systemctl restart hostapd; then
    print_error "hostapd failed to start. Its own log says why:"
    sudo journalctl -xeu hostapd.service --no-pager | tail -40 >&2
    exit 1
fi

run sudo systemctl restart dnsmasq
run sudo systemctl restart photobooth-http-redirect.service

print_success "Access point applied"
print_info "Guests join '${WIFI_SSID}' and reach the booth at http://${WIFI_AP_ADDRESS}"
