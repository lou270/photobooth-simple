"""How a phone reaches the booth: which network to join, and which address.

The QR code on the welcome screen is the only instruction a guest ever gets, and
it is shown on a screen in a room with no second chance to correct it. So the
address is derived from the interface the booth actually answers on, and the
operator can override it outright for the case this cannot know about: a captive
portal hostname, or a booth behind a router that forwards the port.
"""

import logging
import socket

Logger = logging.getLogger('kivy.photobooth')

# Addresses that mean "every interface" rather than naming one, so they can
# never be handed to a phone as somewhere to connect.
WILDCARD_HOSTS = frozenset({'', '0.0.0.0', '::', '[::]', '*'})

# Characters that end a field in a WIFI: payload, and so have to be escaped
# inside one. An SSID containing a semicolon is unusual; an SSID containing a
# space and an apostrophe is not, and only the former would break.
WIFI_ESCAPED_CHARACTERS = '\\;,:"'


def get_local_ip():
    """The address of the interface that carries the booth's traffic.

    No packet is sent: connecting a UDP socket only makes the kernel pick the
    route it would use, which is what the phones on that same network will see.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # An address on the local AP subnet, chosen because it needs no DNS and
        # no reachability: nothing is ever sent to it.
        probe.connect(('192.168.255.255', 9))
        return probe.getsockname()[0]
    except OSError as exc:
        Logger.warning('NetUtils: could not determine the local address: %s', exc)
        return '127.0.0.1'
    finally:
        probe.close()


def _escape_wifi_value(value):
    escaped = []
    for character in str(value):
        if character in WIFI_ESCAPED_CHARACTERS:
            escaped.append('\\')
        escaped.append(character)
    return ''.join(escaped)


def build_wifi_payload(ssid, password=None, hidden=False):
    """The QR payload that makes a phone join the booth's access point.

    Scanning this joins the network; it cannot also open a page, because no
    phone supports a payload that does both. What opens the page afterwards is
    the captive portal: the booth's dnsmasq answers every name with its own
    address, so the phone's own connectivity check lands on the booth.

    An empty password means an open network, which is how install.sh sets the
    access point up. The SSID is not guessed from the hardware: hostapd is
    configured with a name this process never sees, so it comes from config.ini
    and an operator who renames the network renames it in one place.
    """
    ssid = (ssid or '').strip()
    if not ssid:
        return None

    password = (password or '').strip()
    security = 'WPA' if password else 'nopass'

    return (
        f'WIFI:T:{security};'
        f'S:{_escape_wifi_value(ssid)};'
        f'P:{_escape_wifi_value(password)};'
        f'H:{"true" if hidden else "false"};;'
    )


def build_url(port, path='/', host=None, override=None):
    """Absolute URL a phone can open, from the bind address or an override."""
    if override:
        base = override.strip().rstrip('/')
        if base:
            if '://' not in base:
                base = f'http://{base}'
            return f'{base}{path}'

    address = (host or '').strip()
    if address in WILDCARD_HOSTS:
        address = get_local_ip()

    # A bare IPv6 address has to be bracketed before a port can follow it.
    if ':' in address and not address.startswith('['):
        address = f'[{address}]'

    return f'http://{address}:{port}{path}'
