#!/bin/bash
# Shared primitives for the PhotoBooth provisioning scripts.
#
# Everything that writes to the host goes through this file, for two reasons.
#
# Idempotence: the installer must be safe to re-run. The old script appended its
# lines to /boot/firmware/config.txt on every pass, so a second run silently
# duplicated every overlay. managed_block() rewrites a delimited region instead
# of appending, which makes running the installer twice a no-op.
#
# Capability detection: the old script gated half its steps on "is this a
# Raspberry Pi", which meant a mini PC got no access point and no autostart even
# though both work there. The has_* helpers below test for the thing actually
# needed - a boot config file, a wireless interface, an SPI device - so each
# step is skipped only when the host genuinely cannot do it.

# Colors, kept identical to the ones install.sh used.
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'
NC='\033[0m'

DRY_RUN="${DRY_RUN:-false}"

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }
print_skip()    { echo -e "${GRAY}[SKIP]${NC} $1"; }
print_dry()     { echo -e "${GRAY}[DRY-RUN]${NC} $1"; }

is_dry_run() { [ "$DRY_RUN" = "true" ]; }

# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

# run <command...> - execute, or print it under --dry-run.
run() {
    if is_dry_run; then
        print_dry "$*"
        return 0
    fi
    "$@"
}

# ---------------------------------------------------------------------------
# Package installation
# ---------------------------------------------------------------------------

APT_UPDATED=false

apt_refresh() {
    [ "$APT_UPDATED" = "true" ] && return 0
    run sudo apt-get update
    APT_UPDATED=true
}

# apt_ensure <packages...> - install only what is missing, so a re-run costs
# nothing instead of walking the whole dependency tree again.
apt_ensure() {
    local missing=()
    local pkg
    for pkg in "$@"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q '^install ok installed$'; then
            missing+=("$pkg")
        fi
    done
    if [ ${#missing[@]} -eq 0 ]; then
        print_skip "already installed: $*"
        return 0
    fi
    apt_refresh
    print_info "Installing: ${missing[*]}"
    run sudo apt-get install -y "${missing[@]}"
}

# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

# write_root_file <destination> [mode] - content on stdin, written with sudo.
# Creates parent directories. Under --dry-run it prints the content instead.
write_root_file() {
    local dest="$1"
    local mode="${2:-0644}"
    local tmp
    tmp="$(mktemp)"
    cat > "$tmp"

    if is_dry_run; then
        print_dry "write $dest (mode $mode):"
        sed 's/^/          | /' "$tmp"
        rm -f "$tmp"
        return 0
    fi

    # Unchanged content must not count as a change: it keeps re-runs quiet and
    # avoids restarting services that did not need it.
    if [ -f "$dest" ] && sudo cmp -s "$tmp" "$dest"; then
        print_skip "$dest already up to date"
        rm -f "$tmp"
        return 0
    fi

    sudo install -D -m "$mode" "$tmp" "$dest"
    rm -f "$tmp"
    print_success "Wrote $dest"
}

# managed_block <destination> <block-name> - content on stdin, wrapped in
# markers and written into an existing file, replacing any previous version of
# the same block. This is what makes editing /boot/firmware/config.txt safe to
# repeat: the region is rewritten, never appended to.
managed_block() {
    local dest="$1"
    local name="$2"
    local begin="# >>> photobooth:${name} >>>"
    local end="# <<< photobooth:${name} <<<"
    local body tmp mode
    body="$(cat)"
    tmp="$(mktemp)"

    if [ -f "$dest" ]; then
        mode="$(stat -c '%a' "$dest" 2>/dev/null || echo 644)"
        # Drop any earlier copy of this block, keep everything else verbatim.
        sudo cat "$dest" | awk -v b="$begin" -v e="$end" 'BEGIN { skip = 0 } $0 == b { skip = 1 } skip != 1 { print } $0 == e { skip = 0 }' > "$tmp"
    else
        mode=644
        : > "$tmp"
    fi

    {
        printf '%s\n' "$begin"
        printf '%s\n' "$body"
        printf '%s\n' "$end"
    } >> "$tmp"

    write_root_file "$dest" "$mode" < "$tmp"
    rm -f "$tmp"
}

# require_vars <NAME...> - fail loudly when a value a template depends on is
# empty. Without this an undefined variable renders as an empty string and the
# broken result lands in /etc, where it is much harder to notice.
require_vars() {
    local name
    local missing=()
    for name in "$@"; do
        [ -n "${!name:-}" ] || missing+=("$name")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        print_error "Missing required value(s): ${missing[*]}"
        return 1
    fi
}

# render <template> <destination> [mode] - substitute ${VAR} from the current
# environment. envsubst comes from gettext-base, which the installer ensures.
render() {
    local template="$1"
    local dest="$2"
    local mode="${3:-0644}"
    local rendered

    if [ ! -f "$template" ]; then
        print_error "Missing template: $template"
        return 1
    fi

    # envsubst turns an undefined variable into an empty string without
    # complaining, which is how an empty ssid= reaches /etc/hostapd. So the
    # template states its own requirements: every ${NAME} it mentions must be
    # set and non-empty before anything is written.
    # `|| true` is load-bearing: a template with no placeholders at all makes
    # grep exit 1, which under `set -e` would abort the caller mid-way through
    # writing the access point configuration.
    local names
    names="$(grep -o '[$][{][A-Za-z_][A-Za-z0-9_]*[}]' "$template" \
        | tr -d '${}' | sort -u | tr '\n' ' ' || true)"
    # Deliberate word splitting: require_vars takes one name per argument.
    # shellcheck disable=SC2086
    if [ -n "$names" ] && ! require_vars $names; then
        print_error "Cannot render $template"
        return 1
    fi

    rendered="$(envsubst < "$template")"

    printf '%s\n' "$rendered" | write_root_file "$dest" "$mode"
}

# ---------------------------------------------------------------------------
# Capability detection - what this host can do, not what board it is
# ---------------------------------------------------------------------------

# Firmware config path: Bookworm and later use /boot/firmware, older images
# /boot. A mini PC has neither, and every device-tree step is skipped there.
boot_config_path() {
    local candidate
    for candidate in /boot/firmware/config.txt /boot/config.txt; do
        if [ -f "$candidate" ]; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

has_boot_config() { boot_config_path > /dev/null; }

has_wayfire() { [ -f /etc/wayfire/defaults.ini ]; }

has_systemd() { command -v systemctl > /dev/null 2>&1; }

has_unit() {
    has_systemd || return 1
    systemctl list-unit-files 2>/dev/null | grep -q "^$1"
}

has_networkmanager() { has_unit 'NetworkManager.service'; }

# Wireless interface to run the access point on. wlan0 on a Pi; a mini PC may
# name it differently, so fall back to the first wireless device present.
wlan_interface() {
    if [ -n "${WIFI_INTERFACE:-}" ]; then
        printf '%s' "$WIFI_INTERFACE"
        return 0
    fi
    if ip link show wlan0 > /dev/null 2>&1; then
        printf 'wlan0'
        return 0
    fi
    local iface=""
    local candidate
    for candidate in /sys/class/net/*; do
        if [ -d "$candidate/wireless" ]; then
            iface="$(basename "$candidate")"
            break
        fi
    done
    [ -n "$iface" ] || return 1
    printf '%s' "$iface"
}

has_wlan() { wlan_interface > /dev/null 2>&1; }

has_spi_device() { ls /dev/spidev* > /dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------

ask_yes_no() {
    local prompt="$1"
    local answer
    while true; do
        read -r -p "$prompt (y/n): " answer
        case "$answer" in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            *) echo "Please answer yes (y) or no (n)." ;;
        esac
    done
}

# ask_yes_no_var <VAR> <prompt> - fill VAR with yes/no unless the profile
# already answered it. This is what lets --profile and the interactive run
# share a single code path.
ask_yes_no_var() {
    local var="$1"
    local prompt="$2"
    if [ "${!var:-ask}" != "ask" ]; then
        return 0
    fi
    if ask_yes_no "$prompt"; then
        printf -v "$var" 'yes'
    else
        printf -v "$var" 'no'
    fi
}

enabled() { [ "${1:-no}" = "yes" ]; }

# ---------------------------------------------------------------------------
# Config reading
# ---------------------------------------------------------------------------

# booth_config <KEY> - read one resolved value out of config.ini through the
# application's own libs/config.py, so the shell never re-implements the
# parsing, the fallbacks or the "None means disabled" convention.
booth_config() {
    local key="$1"
    "${PHOTOBOOTH_PYTHON:-python3}" "${PHOTOBOOTH_DIR:?}/tools/booth_config.py" "$key"
}
