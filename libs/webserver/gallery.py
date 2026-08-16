"""What a guest can reach: the collages, and the captive portal that leads here."""

from flask import Blueprint, redirect, render_template, send_file, session

from libs.webserver import paths


def create_blueprint(server):
    """Build the gallery routes, closing over the running WebServer."""
    blueprint = Blueprint('gallery', __name__)

    @blueprint.route('/')
    def index():
        """Main page - show gallery."""
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

    @blueprint.route('/image/<session>/<filename>')
    def serve_image(session, filename):
        """Serve an image file."""
        image_path = paths.safe_photo_path(server.save_directory, session, filename)

        if image_path is None:
            return "Not found", 404

        if server.stats_store is not None:
            server.stats_store.track_event('image_view')
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

    @blueprint.route('/generate_204')
    @blueprint.route('/gen_204')
    @blueprint.route('/hotspot-detect.html')
    @blueprint.route('/library/test/success.html')
    @blueprint.route('/canonical.html')
    @blueprint.route('/connecttest.txt')
    @blueprint.route('/ncsi.txt')
    @blueprint.route('/redirect')
    @blueprint.route('/fwlink')
    @blueprint.route('/check_network_status.txt')
    @blueprint.route('/mobile/status.php')
    def captive():
        # A phone joining the booth's access point opens one of these by itself.
        # Where a booth takes photos from phones, that is the page worth landing
        # on: it is the reason the guest was asked to join the network at all.
        if server.remote_enabled and server.remote_store is not None:
            return redirect('/remote')
        return redirect('/')

    return blueprint
