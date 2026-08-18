#!/bin/bash
# Is this booth actually ready?
#
# The installer finishing without an error is not the same as a booth that
# works: the access point can be configured and refuse to come up, the printer
# can be registered and paused, the SSID in the QR code can have drifted from
# the one hostapd broadcasts. This reports on each of those, so a booth built
# an hour before an event can be trusted rather than hoped for.
#
#     ./setup/doctor.sh [--quiet]
#
# Exit code is 1 if anything required is wrong.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHOTOBOOTH_DIR="$(dirname "$SCRIPT_DIR")"
export PHOTOBOOTH_DIR

# shellcheck source=setup/lib.sh
source "$SCRIPT_DIR/lib.sh"

QUIET=false
[ "${1:-}" = "--quiet" ] && QUIET=true

FAILURES=0

ok()   { [ "$QUIET" = "true" ] || echo -e "  [${GREEN}OK${NC}] $1${2:+ - $2}"; }
warn() { echo -e "  [${YELLOW}WARN${NC}] $1${2:+ - $2}"; }
bad()  { echo -e "  [${RED}FAIL${NC}] $1${2:+ - $2}"; FAILURES=$((FAILURES + 1)); }
skip() { [ "$QUIET" = "true" ] || echo -e "  [${GRAY}SKIP${NC}] $1${2:+ - $2}"; }

if [ -f "$SCRIPT_DIR/booth.conf" ]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/booth.conf"
fi

VENV_PYTHON="$PHOTOBOOTH_DIR/.venv/bin/python"
if [ -n "${PHOTOBOOTH_PYTHON:-}" ]; then
    :
elif [ -x "$VENV_PYTHON" ]; then
    PHOTOBOOTH_PYTHON="$VENV_PYTHON"
else
    PHOTOBOOTH_PYTHON="python3"
fi
export PHOTOBOOTH_PYTHON

echo ""
echo "PhotoBooth health check"
echo ""

# ---------------------------------------------------------------------------
echo "Host"
# ---------------------------------------------------------------------------

if has_boot_config; then
    ok "Firmware config" "$(boot_config_path)"
else
    skip "Firmware config" "not a Raspberry Pi; device-tree settings do not apply"
fi

if has_systemd; then
    ok "systemd" "present"
else
    warn "systemd" "absent; nothing starts on boot"
fi

# ---------------------------------------------------------------------------
echo ""
echo "Application"
# ---------------------------------------------------------------------------

if [ -x "$VENV_PYTHON" ]; then
    ok "Virtual environment" ".venv"
else
    bad "Virtual environment" "missing; run ./install.sh"
fi

DOCTOR_ARGS=()
[ "$QUIET" = "true" ] && DOCTOR_ARGS+=(--quiet)
if ! "$PHOTOBOOTH_PYTHON" "$PHOTOBOOTH_DIR/tools/doctor.py" "${DOCTOR_ARGS[@]+"${DOCTOR_ARGS[@]}"}"; then
    FAILURES=$((FAILURES + 1))
fi

# ---------------------------------------------------------------------------
echo ""
echo "Services"
# ---------------------------------------------------------------------------

check_unit() {
    local unit="$1"
    local label="$2"
    if ! has_unit "$unit"; then
        skip "$label" "not installed"
        return
    fi
    if systemctl is-active --quiet "$unit"; then
        ok "$label" "active"
    elif systemctl is-enabled --quiet "$unit" 2>/dev/null; then
        bad "$label" "enabled but not running (systemctl status $unit)"
    else
        skip "$label" "installed but not enabled"
    fi
}

if has_systemd; then
    check_unit photobooth.service "photobooth.service"
    if enabled "${WIFI_AP:-no}"; then
        check_unit hostapd.service "hostapd"
        check_unit dnsmasq.service "dnsmasq"
        check_unit photobooth-http-redirect.service "HTTP redirect 80 to 5000"
        if has_networkmanager; then
            check_unit photobooth-ap-network.service "AP static address"
        fi
    else
        skip "Access point services" "WIFI_AP is not enabled in setup/booth.conf"
    fi
fi

# ---------------------------------------------------------------------------
echo ""
echo "Network"
# ---------------------------------------------------------------------------

if enabled "${WIFI_AP:-no}"; then
    IFACE="$(wlan_interface 2>/dev/null || true)"
    if [ -z "$IFACE" ]; then
        bad "Wireless interface" "none found"
    else
        ok "Wireless interface" "$IFACE"

        AP_ADDRESS="$(booth_config WIFI_AP_ADDRESS 2>/dev/null || true)"
        if [ -n "$AP_ADDRESS" ]; then
            if ip -4 addr show "$IFACE" 2>/dev/null | grep -q "inet ${AP_ADDRESS}/"; then
                ok "AP address" "$AP_ADDRESS on $IFACE"
            else
                bad "AP address" "$AP_ADDRESS is not on $IFACE (ip addr show $IFACE)"
            fi
        fi

        # The one failure that is invisible until a guest scans the code: the
        # booth advertises the SSID from config.ini, hostapd broadcasts the one
        # in its own file, and nothing else compares them.
        CONFIG_SSID="$(booth_config WIFI_SSID 2>/dev/null || true)"
        if [ -f /etc/hostapd/hostapd.conf ]; then
            HOSTAPD_SSID="$(sudo grep -E '^ssid=' /etc/hostapd/hostapd.conf 2>/dev/null | head -1 | cut -d= -f2-)"
            if [ -z "$HOSTAPD_SSID" ]; then
                warn "SSID match" "could not read /etc/hostapd/hostapd.conf"
            elif [ "$HOSTAPD_SSID" = "$CONFIG_SSID" ]; then
                ok "SSID match" "'$CONFIG_SSID' in both config.ini and hostapd.conf"
            else
                bad "SSID match" "QR code says '$CONFIG_SSID', hostapd broadcasts '$HOSTAPD_SSID'; run ./setup/apply-wifi.sh"
            fi
        else
            bad "hostapd.conf" "missing; run ./setup/apply-wifi.sh"
        fi

        WEB_PORT="$(booth_config WEB_PORT 2>/dev/null || echo 5000)"
        if sudo iptables -t nat -C PREROUTING -i "$IFACE" -p tcp --dport 80 \
            -j REDIRECT --to-ports "$WEB_PORT" 2>/dev/null; then
            ok "HTTP redirect" "80 to $WEB_PORT on $IFACE"
        else
            bad "HTTP redirect" "NAT rule absent; guests reaching http://$AP_ADDRESS get nothing"
        fi
    fi
else
    skip "Access point" "WIFI_AP is not enabled in setup/booth.conf"
fi

# The booth answers on its own port whether or not the access point is up.
WEB_PORT="$(booth_config WEB_PORT 2>/dev/null || echo 5000)"
if command -v curl > /dev/null 2>&1; then
    if curl -fs -m 3 -o /dev/null "http://127.0.0.1:${WEB_PORT}/" 2>/dev/null; then
        ok "Web server" "answering on port $WEB_PORT"
    else
        warn "Web server" "no answer on port $WEB_PORT (normal if the booth is not running)"
    fi
else
    skip "Web server" "curl not installed"
fi

# ---------------------------------------------------------------------------
echo ""
# ---------------------------------------------------------------------------

if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}Booth looks ready.${NC}"
    exit 0
fi

echo -e "${RED}${FAILURES} check(s) failed.${NC}"
exit 1
