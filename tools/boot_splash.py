"""Build the booth's Plymouth theme from its config.ini, for the installer.

The picture is the welcome background as it stands right now - the event's own
photo when one was uploaded from the admin page - sized to WINDOW_WIDTH x
WINDOW_HEIGHT and turned by ROTATION. The theme is copied into the initramfs, so
a new welcome photo reaches the boot splash only when the installer runs again.

    python3 tools/boot_splash.py <output-dir> <install-dir>

Files are written into <output-dir>; <install-dir> is where install.sh puts
them, which the theme descriptor has to name.
"""

import configparser
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs import event  # noqa: E402
from libs.boot_splash import build_theme  # noqa: E402
from libs.config import Config  # noqa: E402


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    output_directory, install_directory = argv[1], argv[2]

    try:
        config = Config()
    except (OSError, configparser.Error) as error:
        print(str(error), file=sys.stderr)
        return 1

    source = event.welcome_background()
    paths = build_theme(
        output_directory,
        install_directory,
        source,
        config.get_window_size(),
        config.get_window_rotation(),
    )
    for path in paths.values():
        print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
