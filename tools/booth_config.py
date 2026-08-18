"""Read one resolved setting out of config.ini, for the provisioning scripts.

The shell needs a handful of values from config.ini: the SSID to put in
hostapd.conf, the printer name to hand to lpadmin, the port to probe when
checking the booth is alive. Parsing the file in bash would mean a second
implementation of the fallbacks and of the "None means disabled" convention
that libs/config.py already owns, and the two would drift. So this reads
through Config instead, and prints a single plain value.

Booleans print as true/false, a disabled setting prints as an empty line, so
callers can test with [ -n "$value" ].

    python3 tools/booth_config.py WIFI_SSID
    python3 tools/booth_config.py --all
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.config import Config  # noqa: E402

# Only the settings provisioning actually needs. Keeping the map explicit means
# a typo in a script fails loudly here instead of silently yielding an empty
# string that some template then writes into /etc.
KEYS = {
    'ADMIN_PASSWORD': 'get_admin_password',
    'CAMERA': 'get_camera_backend',
    'DCIM_DIRECTORY': 'get_dcim_directory',
    'PRINTER': 'get_printer',
    'RINGLED': 'get_ringled',
    'WEB_HOST': 'get_web_host',
    'WEB_PORT': 'get_web_port',
    'WIFI_AP_ADDRESS': 'get_wifi_ap_address',
    'WIFI_HIDDEN': 'get_wifi_hidden',
    'WIFI_PASSWORD': 'get_wifi_password',
    'WIFI_SSID': 'get_wifi_ssid',
}


def format_value(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    key = argv[1]

    try:
        config = Config()
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1

    if key == '--all':
        for name in sorted(KEYS):
            print(f'{name}={format_value(getattr(config, KEYS[name])())}')
        return 0

    if key not in KEYS:
        print(
            f'Unknown key {key!r}. Known keys: {", ".join(sorted(KEYS))}',
            file=sys.stderr,
        )
        return 2

    print(format_value(getattr(config, KEYS[key])()))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
