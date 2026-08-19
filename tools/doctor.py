"""Application-level health check for a freshly built booth.

setup/doctor.sh covers the host - services, addresses, firewall rules. This
covers what only Python can see: whether the dependencies import, whether the
camera backends the booth would pick are actually present, whether CUPS knows
the printer named in config.ini.

What counts as a problem comes from config.ini rather than from a list kept
here: a booth with PRINTER = None is not missing a printer, and one with
RINGLED = False is not missing an LED ring. So the report reflects the booth
that was asked for, not a fixed idea of a complete one.

    python3 tools/doctor.py            # or .venv/bin/python
    python3 tools/doctor.py --quiet    # only what is wrong

Exit code is 1 when a required piece is missing, 0 otherwise.
"""

import argparse
import importlib
import os
import shutil
import sys
from pathlib import Path

# Importing kivy prints its banner and its full dependency list, which would
# bury the one thing this script exists to show. Set before anything imports it.
os.environ.setdefault('KIVY_NO_CONSOLELOG', '1')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OK, WARN, FAIL, SKIP = 'OK', 'WARN', 'FAIL', 'SKIP'

COLORS = {
    OK: '\033[0;32m',
    WARN: '\033[1;33m',
    FAIL: '\033[0;31m',
    SKIP: '\033[0;90m',
}
RESET = '\033[0m'


class Report:
    def __init__(self, quiet=False):
        self.rows = []
        self.quiet = quiet
        self.color = sys.stdout.isatty()

    def add(self, status, name, detail=''):
        self.rows.append((status, name, detail))
        if self.quiet and status in (OK, SKIP):
            return
        label = status
        if self.color:
            label = f'{COLORS[status]}{status}{RESET}'
        line = f'  [{label}] {name}'
        if detail:
            line += f' - {detail}'
        print(line)

    @property
    def failed(self):
        return [row for row in self.rows if row[0] == FAIL]


def try_import(name):
    """Import a module, returning it or None, mirroring libs/device_utils.py."""
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def check_python(report):
    report.add(OK, 'Python', f'{sys.version.split()[0]} at {sys.executable}')

    in_venv = sys.prefix != sys.base_prefix
    venv_dir = PROJECT_ROOT / '.venv'
    if in_venv:
        report.add(OK, 'Virtual environment', sys.prefix)
    elif venv_dir.exists():
        report.add(
            WARN,
            'Virtual environment',
            f'{venv_dir} exists but is not the interpreter running this check',
        )
    else:
        report.add(WARN, 'Virtual environment', 'not created; install.sh makes one at .venv')

    for module, required in (
        ('kivy', True),
        ('flask', True),
        ('numpy', True),
        ('cv2', True),
        ('psutil', True),
        ('qrcode', True),
    ):
        if try_import(module) is not None:
            report.add(OK, f'import {module}')
        else:
            report.add(FAIL if required else WARN, f'import {module}', 'missing')


def load_config(report):
    try:
        from libs.config import Config
    except Exception as error:
        report.add(FAIL, 'config.ini', f'cannot import libs.config: {error}')
        return None

    try:
        config = Config()
    except FileNotFoundError:
        report.add(FAIL, 'config.ini', 'missing; copy config.ini.example')
        return None
    except Exception as error:
        report.add(FAIL, 'config.ini', f'unreadable: {error}')
        return None

    report.add(OK, 'config.ini', 'loaded')
    return config


def check_admin_password(report, config):
    password = config.get_admin_password()
    if password is None:
        report.add(WARN, 'Admin password', 'not set; the admin pages stay disabled')
        return

    # Reuse the server's own rules rather than restating them, so this cannot
    # pass a password the application will then reject at startup.
    try:
        from libs.webserver.server import WebServer

        minimum = WebServer.MIN_ADMIN_PASSWORD_LENGTH
        forbidden = WebServer.FORBIDDEN_ADMIN_PASSWORDS
    except Exception as error:
        report.add(WARN, 'Admin password', f'cannot verify against the server rules: {error}')
        return

    if len(password) < minimum:
        report.add(FAIL, 'Admin password', f'shorter than {minimum} characters; admin stays disabled')
    elif password.lower() in forbidden:
        report.add(FAIL, 'Admin password', 'is a well-known value; admin stays disabled')
    else:
        report.add(OK, 'Admin password', 'set and accepted')


def check_cameras(report, config):
    backend = config.get_camera_backend()

    available = []
    if try_import('picamera2') is not None:
        available.append('picamera2')
    if try_import('cv2') is not None:
        available.append('opencv')

    gphoto = try_import('libs.gphoto2')
    gphoto_ok = False
    if gphoto is not None:
        try:
            # The module loads libgphoto2.so on first use rather than at
            # import, so importing it proves nothing: load_library() is what
            # surfaces a missing shared library.
            gphoto.load_library()
            gphoto_ok = True
        except gphoto.LibraryUnavailable:
            gphoto_ok = False
        except Exception:
            gphoto_ok = False
        if gphoto_ok:
            available.append('gphoto2')

    if backend == 'fake':
        report.add(OK, 'Camera', 'CAMERA = fake, no hardware needed')
        return

    if not available:
        report.add(FAIL, 'Camera', 'no backend available (picamera2, opencv, gphoto2 all missing)')
        return

    report.add(OK, 'Camera backends', ', '.join(available))

    if backend != 'auto' and backend not in available:
        report.add(FAIL, 'Camera', f'CAMERA = {backend} but that backend is not available here')
    else:
        report.add(OK, 'Camera', f'CAMERA = {backend}')


def check_printer(report, config):
    printer_name = config.get_printer()
    if printer_name is None:
        report.add(SKIP, 'Printer', 'PRINTER = None, printing disabled')
        return

    cups = try_import('cups')
    if cups is None:
        report.add(FAIL, 'Printer', 'python3-cups not installed but PRINTER is set')
        return

    try:
        connection = cups.Connection()
        printers = connection.getPrinters()
    except Exception as error:
        report.add(FAIL, 'Printer', f'cannot reach the CUPS daemon: {error}')
        return

    if printer_name not in printers:
        known = ', '.join(sorted(printers)) or 'none'
        report.add(FAIL, 'Printer', f"CUPS has no queue named '{printer_name}' (known: {known})")
        return

    state = printers[printer_name].get('printer-state-message') or ''
    report.add(OK, 'Printer', f"'{printer_name}' registered{f' - {state}' if state else ''}")


def check_led(report, config):
    if not config.get_ringled():
        report.add(SKIP, 'LED ring', 'RINGLED = False')
        return

    if try_import('spidev') is None:
        report.add(FAIL, 'LED ring', 'RINGLED = True but spidev is not installed')
        return

    devices = sorted(Path('/dev').glob('spidev*'))
    if not devices:
        report.add(FAIL, 'LED ring', 'no /dev/spidev*; enable SPI and reboot')
        return

    report.add(OK, 'LED ring', f'spidev present ({devices[0].name})')


def check_storage(report, config):
    directory = Path(config.get_dcim_directory())
    parent = directory if directory.exists() else directory.parent

    if not parent.exists():
        report.add(FAIL, 'Photo storage', f'{directory} does not exist and neither does its parent')
        return

    if not os.access(parent, os.W_OK):
        report.add(FAIL, 'Photo storage', f'{parent} is not writable')
        return

    usage = shutil.disk_usage(parent)
    free_gb = usage.free / (1024 ** 3)
    minimum = config.get_disk_min_free_gb()

    if free_gb < minimum:
        report.add(FAIL, 'Photo storage', f'{free_gb:.1f} GB free, below DISK_MIN_FREE_GB ({minimum})')
    else:
        report.add(OK, 'Photo storage', f'{directory} - {free_gb:.1f} GB free')


def check_web(report, config):
    report.add(OK, 'Web server', f'configured on {config.get_web_host()}:{config.get_web_port()}')


def main():
    parser = argparse.ArgumentParser(description='Application-level checks for a PhotoBooth install.')
    parser.add_argument('--quiet', action='store_true', help='only print problems')
    args = parser.parse_args()

    report = Report(quiet=args.quiet)

    check_python(report)

    config = load_config(report)
    if config is not None:
        check_admin_password(report, config)
        check_cameras(report, config)
        check_printer(report, config)
        check_led(report, config)
        check_storage(report, config)
        check_web(report, config)

    if report.failed:
        print(f'\n{len(report.failed)} problem(s) found.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
