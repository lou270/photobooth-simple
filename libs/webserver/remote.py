"""Every phone at the event as a camera for the booth.

The page these routes serve is opened by scanning the QR code on the welcome
screen. A guest takes a photo wherever they are, sends it here, and walks to the
booth to print it. Nothing about the capture happens in this process: the phone's
own camera application takes the photo, which is what keeps this working over
plain HTTP on a booth's access point, where the browser camera API is refused
for want of a secure context.

The whole area answers 404 while remote capture is disabled, so a booth that
does not offer the feature does not advertise it either.
"""

from flask import Blueprint, jsonify, make_response, render_template, request, send_file
from kivy.logger import Logger

from libs.remote_store import RemoteSubmissionError, is_valid_sender_id, new_sender_id

# Names the phone that sent a photo, so it can be shown its own queue and
# nobody else's. Not an account and not a secret worth stealing: it exists for
# the length of an event.
SENDER_COOKIE = 'photobooth_sender'
SENDER_COOKIE_MAX_AGE = 12 * 3600


def create_blueprint(server):
    """Build the remote camera routes, closing over the running WebServer."""
    blueprint = Blueprint('remote', __name__)

    def unavailable():
        """The answer a booth with the feature turned off gives to everything here."""
        return jsonify({'error': 'Remote capture is disabled on this booth.'}), 404

    def is_available():
        return bool(server.remote_enabled and server.remote_store is not None)

    def sender_id():
        """The phone making this request, or None when it has no valid cookie yet."""
        candidate = request.cookies.get(SENDER_COOKIE)
        return candidate if is_valid_sender_id(candidate) else None

    def attach_sender(response, value):
        response.set_cookie(
            SENDER_COOKIE, value,
            max_age=SENDER_COOKIE_MAX_AGE,
            httponly=True,
            samesite='Lax',
        )
        return response

    def public_entry(entry):
        """The view of an entry a phone is allowed to see."""
        return {
            'id': entry['id'],
            'received_at': entry['received_at'],
            'status': entry['status'],
        }

    @blueprint.route('/remote')
    def remote_page():
        """The capture page a guest reaches by scanning the welcome screen."""
        if not is_available():
            return render_template('remote/disabled.html'), 404

        store = server.remote_store
        response = make_response(render_template(
            'remote/index.html',
            max_upload_mb=round(store.max_upload_bytes / (1024 * 1024)),
            max_per_sender=store.max_per_sender,
            max_image_pixels=store.max_image_pixels,
        ))
        return attach_sender(response, sender_id() or new_sender_id())

    @blueprint.route('/remote/upload', methods=['POST'])
    def upload_photo():
        """Accept one photo from a phone."""
        if not is_available():
            return unavailable()

        current_sender = sender_id()
        if current_sender is None:
            # The cookie is set when the page is served, so it being absent here
            # means a browser that refuses cookies rather than a broken client.
            return jsonify({'error': 'Enable cookies for this page, then reload it.'}), 400

        uploaded_file = request.files.get('photo')
        if uploaded_file is None:
            return jsonify({'error': 'No photo was attached to the request.'}), 400

        try:
            entry = server.remote_store.submit(
                uploaded_file.read(),
                current_sender,
                source_name=uploaded_file.filename,
            )
        except RemoteSubmissionError as exc:
            Logger.info('WebServer: remote photo refused: %s', exc)
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            Logger.error(f'WebServer: Error storing remote photo: {exc}')
            return jsonify({'error': 'The booth could not store this photo. Try again.'}), 500

        if server.stats_store is not None:
            server.stats_store.track_event('remote_upload')

        return jsonify({'photo': public_entry(entry)}), 201

    @blueprint.app_errorhandler(413)
    def upload_too_large(error):
        """Tell a phone why its photo bounced, in the language its page speaks.

        A body over the server's own ceiling is refused before the view can
        check it against the store's limit, and the default answer is an HTML
        page. The upload script parses JSON, so it would report that as a lost
        connection and send the guest looking for a WiFi problem they do not
        have.
        """
        if not request.path.startswith('/remote/'):
            return error

        limit_mb = server.remote_store.max_upload_bytes / (1024 * 1024) if server.remote_store else 0
        return jsonify({'error': f'The photo is too large. The limit is {limit_mb:.0f} MB.'}), 413

    @blueprint.route('/remote/mine')
    def my_photos():
        """What this phone has sent, and what became of it."""
        if not is_available():
            return unavailable()

        current_sender = sender_id()
        if current_sender is None:
            return jsonify({'photos': []})

        entries = server.remote_store.list_entries(sender_id=current_sender)
        return jsonify({'photos': [public_entry(entry) for entry in entries]})

    @blueprint.route('/remote/photo/<entry_id>')
    def serve_photo(entry_id):
        """Serve a remote photo to the phone that sent it, or to the operator."""
        if not is_available():
            return unavailable()

        entry = server.remote_store.get(entry_id)
        if entry is None:
            return 'Not found', 404

        if not server._is_admin_authenticated() and entry.get('sender_id') != sender_id():
            # 404 rather than 403: whether an id exists is not something to
            # confirm to a phone that was never given it.
            return 'Not found', 404

        photo_path = server.remote_store.photo_path(entry_id, small=request.args.get('size') == 'small')
        if photo_path is None:
            return 'Not found', 404

        return send_file(photo_path, mimetype='image/jpeg')

    @blueprint.route('/remote/photo/<entry_id>', methods=['DELETE'])
    def withdraw_photo(entry_id):
        """Let a phone take back a photo it sent."""
        if not is_available():
            return unavailable()

        current_sender = sender_id()
        if current_sender is None:
            return jsonify({'error': 'This device is not identified.'}), 400

        if not server.remote_store.delete(entry_id, sender_id=current_sender):
            return jsonify({'error': 'Photo not found.'}), 404

        return jsonify({'deleted': True, 'id': entry_id})

    # --- operator side ----------------------------------------------------

    @blueprint.route('/admin/remote')
    def admin_remote_page():
        """Moderation: everything phones have sent, in one page."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        return render_template('admin/remote.html', remote_enabled=is_available())

    @blueprint.route('/api/remote/photos')
    def list_remote_photos():
        """Every remote photo, for the moderation page."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        if not is_available():
            return jsonify({'photos': [], 'enabled': False})

        entries = server.remote_store.list_entries()
        return jsonify({
            'enabled': True,
            'photos': [
                {
                    'id': entry['id'],
                    'received_at': entry['received_at'],
                    'status': entry['status'],
                    # Truncated: enough to tell two phones apart in the list,
                    # not enough to be worth carrying around.
                    'sender': (entry.get('sender_id') or '')[:8],
                }
                for entry in entries
            ],
        })

    @blueprint.route('/api/remote/photos/<entry_id>/reject', methods=['POST'])
    def reject_remote_photo(entry_id):
        """Take a photo out of the booth queue without deleting it."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        if not is_available():
            return unavailable()

        entry = server.remote_store.set_status(entry_id, server.remote_store.STATUS_REJECTED)
        if entry is None:
            return jsonify({'error': 'Photo not found.'}), 404

        return jsonify({'rejected': True, 'id': entry_id})

    @blueprint.route('/api/remote/photos/<entry_id>', methods=['DELETE'])
    def delete_remote_photo(entry_id):
        """Delete a photo and its files."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        if not is_available():
            return unavailable()

        if not server.remote_store.delete(entry_id):
            return jsonify({'error': 'Photo not found.'}), 404

        return jsonify({'deleted': True, 'id': entry_id})

    return blueprint
