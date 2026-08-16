"""What the operator can reach: configuration, logs, deletion, bulk download."""

import os
import zipfile

from flask import Blueprint, Response, redirect, render_template, request, session
from kivy.logger import Logger

from libs.webserver import config_form
from libs.webserver.archive import ArchiveStream


def create_blueprint(server):
    """Build the admin routes, closing over the running WebServer."""
    blueprint = Blueprint('admin', __name__)

    @blueprint.route('/admin/editor')
    def admin_template_editor():
        """Expose the browser-based template editor inside the admin area."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        if not os.path.exists(server.template_editor_path):
            return 'Template editor not found', 404

        return render_template('editor/template_editor.html')

    @blueprint.route('/admin/logs')
    def admin_logs():
        """Expose application logs inside the admin area."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        return render_template('admin/logs.html')

    @blueprint.route('/download/all-photos')
    def download_all_photos():
        """Stream every photo as a ZIP archive.

        Admin only: this hands over every session of the evening at once,
        which is an operator action, not something a guest should be able
        to do from the gallery.
        """
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        photos = server._get_all_downloadable_photos()
        if not photos:
            return 'No photos found', 404

        if server.stats_store is not None:
            server.stats_store.track_event('download')

        def generate():
            # Built incrementally rather than in a BytesIO: after an evening
            # the whole archive does not fit in a Pi's memory. ZIP_STORED
            # because JPEGs do not compress, so deflating only burns CPU.
            buffer = ArchiveStream()
            try:
                with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:
                    for photo in photos:
                        archive.write(photo['path'], arcname=photo['archive_name'])
                        chunk = buffer.drain()
                        if chunk:
                            yield chunk
            except Exception as e:
                # The response has already started, so the client sees a
                # truncated archive; the log is the only place left to say why.
                Logger.error(f'WebServer: Error while streaming photo archive: {e}')
                return
            yield buffer.drain()

        return Response(
            generate(),
            mimetype='application/zip',
            headers={'Content-Disposition': 'attachment; filename=photobooth_photos.zip'},
        )

    @blueprint.route('/admin')
    def admin_page():
        """Protected admin page."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        return server._render_admin_page()

    @blueprint.route('/admin/login')
    def admin_login_page():
        """Admin login page."""
        if server._is_admin_authenticated():
            return redirect('/admin')

        logout_flag = request.args.get('logout') == '1'
        return server._render_admin_login_page(success_message='Logged out successfully.' if logout_flag else None)

    @blueprint.route('/admin/login', methods=['POST'])
    def admin_login():
        """Authenticate admin user."""
        if server.admin_password is None:
            return server._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

        client_key = server._client_key()
        retry_after = server.login_throttle.retry_after(client_key)
        if retry_after:
            session.clear()
            return server._render_admin_login_page(
                error_message=f'Too many failed attempts. Try again in {retry_after} seconds.',
            ), 429

        provided_password = request.form.get('password') or ''
        if not server._is_admin_password_valid(provided_password):
            session.clear()
            locked_for = server.login_throttle.record_failure(client_key)
            Logger.warning('WebServer: failed admin login from %s', client_key)
            if locked_for:
                return server._render_admin_login_page(
                    error_message=f'Too many failed attempts. Try again in {locked_for} seconds.',
                ), 429
            return server._render_admin_login_page(error_message='Invalid password.'), 403

        server.login_throttle.record_success(client_key)
        session.clear()
        session['is_admin_authenticated'] = True
        return redirect('/admin')

    @blueprint.route('/admin/logout')
    def admin_logout():
        """Log out admin user."""
        session.clear()
        return redirect('/admin/login?logout=1')

    @blueprint.route('/admin/delete-all', methods=['POST'])
    def delete_all_sessions():
        """Delete all saved sessions after password validation."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        if server.admin_password is None:
            session.clear()
            return server._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

        try:
            deleted_sessions = server._delete_all_sessions()
        except Exception:
            return server._render_admin_page(error_message='Error while deleting files.'), 500

        return server._render_admin_page(success_message=f'{deleted_sessions} session(s) deleted.')

    @blueprint.route('/admin/config', methods=['POST'])
    def save_admin_config():
        """Save config.ini after password validation."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        if server.admin_password is None:
            session.clear()
            return server._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

        submitted_form_values = {}

        try:
            current_config = server._load_config_text()
            parser = config_form.load_parser(current_config)
            updates, submitted_form_values = config_form.collect_updates(request.form, parser)
            updated_config = config_form.apply_updates(current_config, updates)
        except ValueError as exc:
            return server._render_admin_page(error_message=str(exc), form_values=submitted_form_values), 400
        except Exception as exc:
            Logger.error(f'WebServer: Error while preparing config.ini update: {exc}')
            return server._render_admin_page(error_message='Error while preparing config.ini.', form_values=request.form), 500

        try:
            server._save_config_text(updated_config)
        except Exception:
            return server._render_admin_page(error_message='Error while saving config.ini.', form_values=submitted_form_values), 500

        try:
            updated_config = server._load_config_text()
            server._refresh_admin_password_from_config(updated_config)
        except Exception:
            return server._render_admin_page(success_message='config.ini saved. Restart app to apply all changes.')

        if server.admin_password is None:
            session.clear()
            return server._render_admin_login_page(success_message='config.ini saved. Admin password disabled. Sign in is now disabled.')

        return server._render_admin_page(success_message='config.ini saved. Restart app to apply all changes.')

    @blueprint.route('/admin/restart', methods=['POST'])
    def restart_app():
        """Restart application after password validation."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        if server.admin_password is None:
            session.clear()
            return server._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

        if not callable(server.restart_callback):
            return server._render_admin_page(error_message='Restart callback is unavailable.'), 500

        try:
            server.restart_callback()
        except Exception as e:
            Logger.error(f'WebServer: Error restarting app: {e}')
            return server._render_admin_page(error_message='Error while restarting app.'), 500

        return server._render_admin_page(success_message='Application restart requested. Page may become unavailable for a few seconds.')

    @blueprint.route('/stats')
    def statistics():
        """Usage analytics: lists every session, so admin only."""
        auth_redirect = server._require_admin_auth()
        if auth_redirect is not None:
            return auth_redirect

        stats = server.stats_store.load() if server.stats_store is not None else {
            'photos_taken': 0,
            'prints': 0,
            'downloads': 0,
            'gallery_views': 0,
            'collage_views': 0,
            'image_views': 0,
            'remote_uploads': 0,
            'first_photo_date': None,
            'last_photo_date': None,
            'last_print_date': None,
            'last_download_date': None,
            'sessions': [],
        }
        collages = server._get_all_collages()
        downloadable_photos = server._get_all_downloadable_photos()

        return render_template(
            'stats.html',
            collages=collages,
            downloadable_photos=downloadable_photos,
            print_limit=server.stats_store.get_print_limit_info() if server.stats_store is not None else {
                'enabled': False,
                'max_prints': None,
                'prints': 0,
                'remaining': None,
                'reached': False,
            },
            stats=stats,
        )

    # Captive portal detection URLs

    return blueprint
