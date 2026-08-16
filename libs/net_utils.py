"""Where a phone has to point its browser to reach the booth.

The QR code on the welcome screen is the only address a guest ever gets, and it
is printed on a screen in a room with no second chance to correct it. So the
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
