#!/bin/bash
# Is this booth actually ready?
#
# The installer finishing without an error is not the same as a booth that
# works: the printer can be registered and paused, the camera library missing,
# the web server not answering. This reports on each of those, so a booth built
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

    # Earlier versions ran their own access point, and the booth no longer
    # answers the portal those services send every phone to. Left running, they
    # hand guests a network that leads nowhere.
    for legacy_unit in hostapd.service dnsmasq.service photobooth-http-redirect.service photobooth-ap-network.service; do
        if has_unit "$legacy_unit" && systemctl is-active --quiet "$legacy_unit"; then
            warn "$legacy_unit" "left from the old access point; see INSTALLATION.md to remove it"
        fi
    done
fi

# ---------------------------------------------------------------------------
echo ""
echo "Network"
# ---------------------------------------------------------------------------

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

# The address the QR codes carry when REMOTE_URL is left empty: the one the
# booth uses to reach its network. No address at all means no QR code works,
# which only matters to a booth with SHARE or REMOTE_CAPTURE on.
if command -v ip > /dev/null 2>&1; then
    ROUTE_ADDRESS="$(ip -4 route get 192.168.255.255 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)"
    if [ -n "$ROUTE_ADDRESS" ]; then
        ok "Booth address" "$ROUTE_ADDRESS, phones must be on that network"
    else
        warn "Booth address" "no network; QR codes would carry 127.0.0.1"
    fi
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
