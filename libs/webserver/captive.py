"""The portal a phone meets before it meets the booth.

Three mechanisms are answered here, because phones do not agree on one:

  - the Captive Portal API of RFC 8908, which the access point advertises with
    the DHCP option of RFC 8910, and which iOS 14 and Android 11 read first;
  - the connectivity probes every operating system has used for a decade, which
    are what the rest still rely on;
  - plain browsing to any other domain, which the booth's DNS captures, and
    which should land on the page rather than on a bare 404.

All three ask the same question, "am I stuck?", and all three get the same
answer, taken from whether this phone has been through the portal yet.
"""

import ipaddress

from flask import Blueprint, jsonify, redirect, request
from kivy.logger import Logger

from libs.captive_portal import PROBE_RESPONSES

# RFC 8908 defines this media type, and clients ask for it by name. Anything
# else in the Content-Type and the phone falls back to guessing from probes.
CAPTIVE_API_MEDIA_TYPE = 'application/captive+json'


def create_blueprint(server):
    """Build the captive portal routes, closing over the running WebServer."""
    blueprint = Blueprint('captive', __name__)

    def portal_path():
        """The page a guest is sent to, which is what the booth is for."""
        if server.remote_enabled and server.remote_store is not None:
            return '/remote'
        return '/'

    def portal_url():
        """Absolute, because RFC 8908 has no room for a relative one.

        Built from the address the phone itself used rather than from the
        booth's configuration: on an access point behind a DNS hijack, that is
        the only address known to work from where the phone is standing.
        """
        return request.host_url.rstrip('/') + portal_path()

    def client_key():
        return server._client_key()

    def is_released():
        return server.captive_clients.is_released(client_key())

    @blueprint.route('/captive-portal/api')
    def captive_api():
        """The RFC 8908 endpoint the access point advertises in DHCP option 114.

        A browser that follows the advertised URI without asking for the API
        media type is redirected to the page instead, which RFC 8910 asks for
        and which keeps the address usable by hand.
        """
        if CAPTIVE_API_MEDIA_TYPE not in (request.headers.get('Accept') or ''):
            return redirect(portal_path())

        if is_released():
            # venue-info-url, not user-portal-url: the phone is free, and this
            # is only the way back to the page if the guest wants it.
            payload = {'captive': False, 'venue-info-url': portal_url()}
        else:
            payload = {'captive': True, 'user-portal-url': portal_url()}

        response = jsonify(payload)
        response.mimetype = CAPTIVE_API_MEDIA_TYPE
        # An answer of "you are free" must never be served from a cache after
        # the session behind it has expired.
        response.headers['Cache-Control'] = 'no-store'
        return response

    @blueprint.route('/captive-portal/release', methods=['POST'])
    def release_client():
        """Let the guest say they are done, so their phone stops complaining.

        Reached from a button on the capture page. Without it, a phone whose
        owner only browses the gallery would be nagged all evening, and on
        Android eventually dropped onto mobile data.
        """
        server.captive_clients.release(client_key())
        return jsonify({'released': True})

    @blueprint.route('/generate_204')
    @blueprint.route('/gen_204')
    @blueprint.route('/generate204')
    @blueprint.route('/hotspot-detect.html')
    @blueprint.route('/library/test/success.html')
    @blueprint.route('/success.txt')
    @blueprint.route('/canonical.html')
    @blueprint.route('/connecttest.txt')
    @blueprint.route('/ncsi.txt')
    def connectivity_probe():
        """Answer the check an operating system runs to decide if it is stuck."""
        if not is_released():
            # A redirect is what makes the portal notification appear, and the
            # sheet open on the page. It is the whole discovery mechanism.
            return redirect(portal_path())

        body, status, mimetype = PROBE_RESPONSES[request.path.lower()]
        response = server.app.response_class(body, status=status, mimetype=mimetype)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @blueprint.route('/redirect')
    @blueprint.route('/fwlink')
    @blueprint.route('/check_network_status.txt')
    @blueprint.route('/mobile/status.php')
    def portal_entry():
        """Where an operating system sends the guest to find the portal."""
        return redirect(portal_path())

    @blueprint.app_errorhandler(404)
    def unknown_address(error):
        """Send a guest browsing the open web to the booth instead of nowhere.

        The access point resolves every domain to itself, so a guest who opens
        their browser and types anything at all arrives here. A 404 makes the
        network look broken; the portal page is the honest answer to "where am
        I?". Requests aimed at the booth's own address keep their 404: a
        mistyped admin URL is not a guest looking for the portal.
        """
        if not _asks_for_a_page() or not _is_captured_domain():
            return error

        Logger.info('CaptivePortal: sending %s to the portal from %s', client_key(), request.host)
        return redirect(portal_url())

    def _asks_for_a_page():
        """True for a browser navigating, false for a fetch() or an image."""
        return 'text/html' in (request.headers.get('Accept') or '')

    def _is_captured_domain():
        """True when the Host is a name the booth's DNS answered for.

        Guests reach the booth by address, so a hostname in the Host header is
        one the wildcard DNS captured on its way somewhere else.
        """
        hostname = (request.host or '').rsplit(':', 1)[0].strip('[]').lower()
        if not hostname or hostname == 'localhost':
            return False

        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return False

    return blueprint
