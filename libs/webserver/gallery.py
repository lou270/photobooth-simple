"""What a guest can reach: the collages, and the page they land on first."""

from flask import Blueprint, g, redirect, render_template, request, send_file, session

from libs import i18n
from libs.webserver import paths


def create_blueprint(server):
    """Build the gallery routes, closing over the running WebServer."""
    blueprint = Blueprint('gallery', __name__)

    @blueprint.before_request
    def _negotiate_guest_language():
        """A guest's phone, not the booth, decides the language here."""
        g.lang = request.accept_languages.best_match(i18n.AVAILABLE_LANGUAGES, default=i18n.DEFAULT_LANGUAGE)

    @blueprint.route('/')
    def index():
        """Main page - show gallery, or the capture page when phones may send."""
        # Where a phone that just joined the WiFi arrives: the access point
        # advertises this address as its captive portal, and it is also what the
        # second QR code carries. Where the booth takes photos from phones, that
        # is what the guest came for; the gallery stays one link away.
        if server.remote_enabled and server.remote_store is not None:
            return redirect('/remote')

        collages = server._get_all_collages()

        if not collages:
            return render_template('gallery/empty.html')

        # Redirect to latest collage
        latest = collages[0]
        return redirect(f'/collage/{latest["session"]}')

    @blueprint.route('/gallery')
    def gallery():
        """Gallery view with all collages."""
        if server.stats_store is not None:
            server.stats_store.track_event('gallery_view')
        collages = server._get_all_collages()

        return render_template('gallery/index.html', collages=collages)

    @blueprint.route('/collage/<session>')
    def view_collage(session):
        """View a single collage fullscreen."""
        collage_path = paths.safe_photo_path(server.save_directory, session, 'collage.jpg')

        if collage_path is None:
            return redirect('/')

        if server.stats_store is not None:
            server.stats_store.track_event('collage_view')

        return render_template('gallery/collage.html', session=session)

    @blueprint.route('/thumb/<session>')
    def serve_thumbnail(session):
        """The small copy the grid draws, or the full collage when there is none.

        The fallback is what keeps sessions saved before the booth started
        writing thumbnails visible: a heavy grid is a worse answer than a fast
        one, and a grid of broken images is worse than both.
        """
        image_path = paths.safe_thumbnail_path(server.save_directory, session)

        if image_path is None:
            image_path = paths.safe_photo_path(server.save_directory, session, 'collage.jpg')

        if image_path is None:
            return "Not found", 404

        return send_file(image_path, mimetype='image/jpeg')

    @blueprint.route('/image/<session>/<filename>')
    def serve_image(session, filename):
        """Serve an image file.

        Deliberately uncounted. This used to record an image_view, which took a
        global lock, reread the whole stats file, rewrote it and renamed it —
        per image served, for a counter no page has ever displayed. A gallery of
        eighty tiles cost eighty of those, and the lock is the one the booth
        takes to save a session, so a few phones browsing made the booth stutter
        as a guest pressed print. Gallery and collage views are still counted:
        they are shown, and they arrive once per page rather than per image.
        """
        image_path = paths.safe_photo_path(server.save_directory, session, filename)

        if image_path is None:
            return "Not found", 404

        return send_file(image_path, mimetype='image/jpeg')

    @blueprint.route('/download/<session>/<filename>')
    def download_image(session, filename):
        """Download an image file."""
        image_path = paths.safe_photo_path(server.save_directory, session, filename)

        if image_path is None:
            return "Not found", 404

        if server.stats_store is not None:
            server.stats_store.track_event('download')
        return send_file(
            image_path,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=f'photobooth_{session}.jpg'
        )

    return blueprint
