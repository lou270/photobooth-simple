import hmac
import json
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file, render_template, redirect, session
from werkzeug.serving import make_server
from kivy.logger import Logger

from libs.login_throttle import LoginThrottle
from libs.webserver import config_form
from libs.template_schema import TemplateValidationError, validate_template


class _ArchiveStream:
    """Write target for ZipFile that hands each chunk straight to the response.

    Only tell() is provided, no seek: zipfile then writes a streamable archive
    with data descriptors instead of rewinding to patch headers.
    """

    def __init__(self):
        self._chunks = []
        self._offset = 0

    def write(self, data):
        self._chunks.append(data)
        self._offset += len(data)
        return len(data)

    def tell(self):
        return self._offset

    def flush(self):
        pass

    def drain(self):
        chunks, self._chunks = self._chunks, []
        return b''.join(chunks)

class WebServer:
    """Flask web server for photo gallery with captive portal."""

    # The admin password is the only application-level gate on a booth that is
    # reachable from whatever network it sits on, so refuse the obvious ones
    # outright rather than trusting the operator to have changed the default.
    # Poll interval, then the delay before each successive restart attempt.
    WATCHDOG_BACKOFF_SECONDS = (5, 5, 15, 60, 300)

    MIN_ADMIN_PASSWORD_LENGTH = 10
    FORBIDDEN_ADMIN_PASSWORDS = frozenset({
        'admin', 'password', 'photobooth', 'motdepasse', 'changeme', '0000',
        '1234', '12345678', '123456789', '1234567890', 'azertyuiop', 'qwertyuiop',
    })

    SESSION_PATTERN = re.compile(r'^\d{8}_\d{6}$')
    IMAGE_FILENAME_PATTERN = re.compile(r'^(?:collage|capture-\d+)\.jpg$', re.IGNORECASE)
    LOG_FILENAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')
    def __init__(self, save_directory, host='0.0.0.0', port=5000, admin_password=None, stats_store=None, restart_callback=None):
        self.save_directory = save_directory
        self.host = host
        self.port = port
        self.admin_password = self._accept_admin_password(admin_password)
        self.login_throttle = LoginThrottle()
        self.stats_store = stats_store
        self.restart_callback = restart_callback
        # libs/webserver/server.py -> the project root is three levels up.
        self.project_root = str(Path(__file__).resolve().parents[2])
        self.web_directory = os.path.join(self.project_root, 'web')
        self.web_assets_directory = os.path.join(self.web_directory, 'assets')
        self.app = Flask(
            __name__,
            template_folder=self.web_directory,
            static_folder=self.web_assets_directory,
            static_url_path='/web-assets',
        )
        self.app.secret_key = os.urandom(32)
        self.app.config.update(
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            # Templates carry embedded images, so uploads are legitimately large;
            # the cap keeps a single request from exhausting memory on a Pi.
            MAX_CONTENT_LENGTH=32 * 1024 * 1024,
        )
        self.server_thread = None
        self.server = None
        self._server_lock = threading.Lock()
        self._watchdog_thread = None
        self._watchdog_stop = threading.Event()
        self.config_file = os.path.join(self.project_root, 'config.ini')
        self.logs_directory = os.path.join(self.project_root, 'logs')
        self.templates_directory = os.path.join(self.project_root, 'templates')
        self.template_editor_path = os.path.join(self.web_directory, 'editor', 'template_editor.html')
        self._setup_routes()

    def _watchdog_loop(self):
        """Restart the server when its thread dies, backing off between tries.

        A bind that fails once usually fails again: a port held by a leftover
        process does not free itself. Retrying every five seconds forever only
        fills the log with the same error until the disk notices.
        """
        consecutive_failures = 0

        while not self._watchdog_stop.wait(timeout=self.WATCHDOG_BACKOFF_SECONDS[consecutive_failures]):
            if self.server_thread is None or self.server_thread.is_alive():
                consecutive_failures = 0
                continue

            Logger.error('WebServer: watchdog detected stopped server thread, attempting restart')
            restarted = False
            try:
                restarted = self.start(force_restart=True)
            except Exception as e:
                Logger.error(f'WebServer: watchdog restart exception: {e}')

            if restarted:
                consecutive_failures = 0
                continue

            consecutive_failures += 1
            if consecutive_failures >= len(self.WATCHDOG_BACKOFF_SECONDS):
                Logger.error(
                    'WebServer: giving up after %s restart attempts, gallery and admin stay '
                    'unavailable until the application is restarted',
                    consecutive_failures,
                )
                return

            Logger.error(
                'WebServer: watchdog restart failed, next attempt in %ss',
                self.WATCHDOG_BACKOFF_SECONDS[consecutive_failures],
            )

    def _ensure_watchdog(self):
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, name='webserver-watchdog', daemon=True)
        self._watchdog_thread.start()

    def _sanitize_template_filename(self, filename=None, template_name='template'):
        """Return a safe JSON filename for template storage."""
        source = filename or template_name or 'template'
        safe_name = os.path.basename(source).strip()

        if safe_name.lower().endswith('.json'):
            safe_name = safe_name[:-5]

        safe_name = safe_name.replace(' ', '_')
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '', safe_name)
        safe_name = safe_name.strip('._-') or 'template'

        return f'{safe_name}.json'

    def _get_unique_template_filename(self, filename):
        """Return a non-conflicting filename in the templates directory."""
        base_name, extension = os.path.splitext(filename)
        candidate = filename
        counter = 1

        while os.path.exists(os.path.join(self.templates_directory, candidate)):
            candidate = f'{base_name}_{counter}{extension}'
            counter += 1

        return candidate

    def _load_template_definitions(self):
        """Load all template JSON files from the templates directory."""
        templates = []

        if not os.path.isdir(self.templates_directory):
            return templates

        for filename in sorted(os.listdir(self.templates_directory)):
            if not filename.lower().endswith('.json'):
                continue

            template_path = os.path.join(self.templates_directory, filename)
            if not os.path.isfile(template_path):
                continue

            try:
                with open(template_path, 'r', encoding='utf-8') as handle:
                    template_data = json.load(handle)

                if isinstance(template_data, dict):
                    templates.append({
                        'filename': filename,
                        'template': template_data,
                    })
            except Exception as e:
                Logger.error(f'WebServer: Error loading template {filename}: {e}')

        return templates

    def _is_valid_session(self, session):
        """Return True when session matches expected timestamp format."""
        if not isinstance(session, str):
            return False

        return bool(self.SESSION_PATTERN.fullmatch(session))

    def _is_valid_image_filename(self, filename):
        """Return True when filename matches expected JPEG photo names."""
        if not isinstance(filename, str):
            return False

        return bool(self.IMAGE_FILENAME_PATTERN.fullmatch(filename))

    def _get_safe_photo_path(self, session, filename):
        """Return canonical photo path when request targets allowed JPEG file."""
        if not self._is_valid_session(session) or not self._is_valid_image_filename(filename):
            return None

        base_path = os.path.realpath(self.save_directory)
        requested_path = os.path.realpath(os.path.join(base_path, session, filename))

        if not requested_path.startswith(base_path + os.sep):
            return None

        if not os.path.isfile(requested_path):
            return None

        return requested_path

    def _get_log_files(self):
        """Return log files sorted by modification time, newest first."""
        log_files = []

        try:
            if not os.path.isdir(self.logs_directory):
                return log_files

            for filename in os.listdir(self.logs_directory):
                log_path = os.path.join(self.logs_directory, filename)
                if not os.path.isfile(log_path):
                    continue

                stat = os.stat(log_path)
                log_files.append({
                    'filename': filename,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds'),
                    'size': stat.st_size,
                })
        except Exception as e:
            Logger.error(f'WebServer: Error listing log files: {e}')

        return sorted(log_files, key=lambda item: item['modified'], reverse=True)

    def _get_safe_log_path(self, filename):
        """Return canonical log path for a direct child of the logs directory."""
        if not isinstance(filename, str) or not self.LOG_FILENAME_PATTERN.fullmatch(filename):
            return None

        base_path = os.path.realpath(self.logs_directory)
        requested_path = os.path.realpath(os.path.join(base_path, filename))

        if os.path.dirname(requested_path) != base_path:
            return None

        if not os.path.isfile(requested_path):
            return None

        return requested_path

    def _delete_all_log_files(self):
        """Delete all direct files from the logs directory."""
        deleted_files = 0

        if not os.path.isdir(self.logs_directory):
            return deleted_files

        for log_file in self._get_log_files():
            log_path = self._get_safe_log_path(log_file['filename'])
            if log_path is None:
                continue

            os.remove(log_path)
            deleted_files += 1

        return deleted_files

    def _format_bytes(self, value):
        """Return a compact human-readable byte size."""
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        size = float(value)

        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f'{size:.1f} {unit}' if unit != 'B' else f'{int(size)} {unit}'
            size /= 1024

    def _get_disk_usage_info(self):
        """Return disk usage for the photo save directory mount point."""
        usage_path = self.save_directory if os.path.exists(self.save_directory) else self.project_root
        usage = shutil.disk_usage(usage_path)
        used = usage.total - usage.free
        used_percent = 0 if usage.total == 0 else round((used / usage.total) * 100, 1)

        return {
            'path': usage_path,
            'total': self._format_bytes(usage.total),
            'used': self._format_bytes(used),
            'free': self._format_bytes(usage.free),
            'used_percent': used_percent,
        }

    def _get_all_collages(self):
        """Get all collage files sorted by date (newest first)."""
        collages = []
        try:
            if not os.path.exists(self.save_directory):
                return collages
            
            # List all subdirectories (sessions)
            for session_dir in sorted(os.listdir(self.save_directory), reverse=True):
                session_path = os.path.join(self.save_directory, session_dir)
                if not os.path.isdir(session_path):
                    continue
                
                # Find collage in this session
                for filename in os.listdir(session_path):
                    if filename == 'collage.jpg':
                        collages.append({
                            'session': session_dir,
                            'path': os.path.join(session_path, filename),
                            'filename': filename
                        })
                        break
        except Exception as e:
            Logger.error(f'WebServer: Error getting collages: {e}')
        
        return collages

    def _get_all_downloadable_photos(self):
        """Get all downloadable photos sorted by session and filename."""
        photos = []

        try:
            if not os.path.exists(self.save_directory):
                return photos

            for session_dir in sorted(os.listdir(self.save_directory), reverse=True):
                session_path = os.path.join(self.save_directory, session_dir)
                if not os.path.isdir(session_path) or not self._is_valid_session(session_dir):
                    continue

                for filename in sorted(os.listdir(session_path)):
                    if not self._is_valid_image_filename(filename):
                        continue

                    photo_path = os.path.join(session_path, filename)
                    if not os.path.isfile(photo_path):
                        continue

                    photos.append({
                        'session': session_dir,
                        'filename': filename,
                        'path': photo_path,
                        'archive_name': os.path.join(session_dir, filename),
                    })
        except Exception as e:
            Logger.error(f'WebServer: Error getting downloadable photos: {e}')

        return photos

    def _delete_all_sessions(self):
        """Delete all valid session directories and reset photo-related stats."""
        deleted_sessions = 0

        try:
            if os.path.isdir(self.save_directory):
                for session_dir in os.listdir(self.save_directory):
                    session_path = os.path.join(self.save_directory, session_dir)
                    if not os.path.isdir(session_path) or not self._is_valid_session(session_dir):
                        continue

                    shutil.rmtree(session_path)
                    deleted_sessions += 1

            if self.stats_store is not None:
                self.stats_store.reset()
        except Exception as e:
            Logger.error(f'WebServer: Error deleting sessions: {e}')
            raise

        return deleted_sessions

    def _load_config_text(self):
        """Return config.ini content as text."""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as handle:
                return handle.read()
        except Exception as e:
            Logger.error(f'WebServer: Error loading config file: {e}')
            raise

    def _save_config_text(self, content):
        """Persist config.ini content to disk."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as handle:
                handle.write(content)
        except Exception as e:
            Logger.error(f'WebServer: Error saving config file: {e}')
            raise

    @classmethod
    def _accept_admin_password(cls, admin_password):
        """Return the password to use, or None to keep admin access disabled.

        Refusing a weak password fails closed: the booth keeps taking photos,
        only the web admin stays shut until a real password is configured.
        """
        if not isinstance(admin_password, str):
            return None

        password = admin_password.strip()
        if not password:
            return None

        if password.lower() in cls.FORBIDDEN_ADMIN_PASSWORDS:
            Logger.error(
                'WebServer: ADMIN_PASSWORD is a well-known value, admin access stays disabled. '
                'Set a different password in config.ini.'
            )
            return None

        if len(password) < cls.MIN_ADMIN_PASSWORD_LENGTH:
            Logger.error(
                'WebServer: ADMIN_PASSWORD is shorter than %s characters, admin access stays '
                'disabled. Set a longer password in config.ini.',
                cls.MIN_ADMIN_PASSWORD_LENGTH,
            )
            return None

        return password

    def _client_key(self):
        """Identify the caller for throttling purposes."""
        return request.remote_addr or 'unknown'

    def _is_admin_password_valid(self, password):
        """Validate provided admin password."""
        if self.admin_password is None:
            return False

        return hmac.compare_digest((password or '').strip(), self.admin_password)

    def _is_admin_authenticated(self):
        """Return True when current session is authenticated."""
        return bool(session.get('is_admin_authenticated'))

    def _require_admin_auth(self):
        """Redirect unauthenticated users to admin login page."""
        if self._is_admin_authenticated():
            return None

        return redirect('/admin/login')

    def _require_admin_api_auth(self):
        """Reject unauthenticated API calls with 401.

        Redirecting to the HTML login page instead would hand a fetch() caller a
        200 full of HTML, which it then fails to parse as JSON.
        """
        if self._is_admin_authenticated():
            return None

        return jsonify({'error': 'Authentication required'}), 401

    def _refresh_admin_password_from_config(self, content):
        """Refresh in-memory admin password from config text."""
        self.admin_password = None
        password_match = re.search(r'^\s*ADMIN_PASSWORD\s*=\s*(.*?)\s*$', content, re.MULTILINE)
        if not password_match:
            return

        configured_password = password_match.group(1).strip()
        if configured_password.upper() == 'NONE':
            return

        # Same policy as at startup: saving a weak password from the admin form
        # must not be a way around it.
        self.admin_password = self._accept_admin_password(configured_password)

    def _render_admin_login_page(self, error_message=None, success_message=None):
        """Render admin login page."""
        return render_template(
            'admin/login.html',
            admin_enabled=self.admin_password is not None,
            error_message=error_message,
            success_message=success_message,
        )

    def _render_admin_page(self, error_message=None, success_message=None, form_values=None):
        """Render admin page with typed configuration fields."""
        admin_enabled = self.admin_password is not None
        config_error_message = None

        try:
            parser = config_form.load_parser(self._load_config_text())
            config_sections = config_form.render_sections(parser, form_values=form_values)
        except Exception as exc:
            Logger.error(f'WebServer: Error building admin config form: {exc}')
            config_sections = []
            config_error_message = 'Unable to load config.ini into the admin form.'

        if error_message and config_error_message:
            error_message = f'{error_message} {config_error_message}'
        elif config_error_message:
            error_message = config_error_message

        return render_template(
            'admin/index.html',
            admin_enabled=admin_enabled,
            config_sections=config_sections,
            disk_usage=self._get_disk_usage_info(),
            error_message=error_message,
            success_message=success_message,
        )

    def _setup_routes(self):
        """Setup Flask routes."""

        @self.app.route('/admin/editor')
        def admin_template_editor():
            """Expose the browser-based template editor inside the admin area."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            if not os.path.exists(self.template_editor_path):
                return 'Template editor not found', 404

            return render_template('editor/template_editor.html')

        @self.app.route('/admin/logs')
        def admin_logs():
            """Expose application logs inside the admin area."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            return render_template('admin/logs.html')

        @self.app.route('/api/admin/logs', methods=['GET'])
        def list_admin_logs():
            """List available log files for authenticated admins."""
            auth_error = self._require_admin_api_auth()
            if auth_error is not None:
                return auth_error

            return jsonify({'logs': self._get_log_files()})

        @self.app.route('/api/admin/logs/<path:filename>', methods=['GET'])
        def read_admin_log(filename):
            """Read one log file for authenticated admins."""
            auth_error = self._require_admin_api_auth()
            if auth_error is not None:
                return auth_error

            log_path = self._get_safe_log_path(filename)
            if log_path is None:
                return jsonify({'error': 'Log file not found'}), 404

            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as handle:
                    content = handle.read()
            except Exception as e:
                Logger.error(f'WebServer: Error reading log file {filename}: {e}')
                return jsonify({'error': 'Unable to read log file'}), 500

            return jsonify({'filename': os.path.basename(log_path), 'content': content})

        @self.app.route('/api/admin/logs', methods=['DELETE'])
        def delete_admin_logs():
            """Delete all log files for authenticated admins."""
            auth_error = self._require_admin_api_auth()
            if auth_error is not None:
                return auth_error

            try:
                deleted_files = self._delete_all_log_files()
            except Exception as e:
                Logger.error(f'WebServer: Error deleting log files: {e}')
                return jsonify({'error': 'Unable to delete log files'}), 500

            return jsonify({'deleted': deleted_files})

        @self.app.route('/api/templates', methods=['GET'])
        def list_templates():
            """List templates stored on disk."""
            auth_error = self._require_admin_api_auth()
            if auth_error is not None:
                return auth_error

            return jsonify({'templates': self._load_template_definitions()})

        @self.app.route('/api/templates', methods=['POST'])
        def save_template():
            """Save a template into the templates directory."""
            auth_error = self._require_admin_api_auth()
            if auth_error is not None:
                return auth_error

            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({'error': 'Invalid JSON payload'}), 400

            try:
                template_data = validate_template(payload.get('template'))
            except TemplateValidationError as exc:
                return jsonify({'error': str(exc)}), 400

            requested_filename = payload.get('filename')
            filename = self._sanitize_template_filename(
                requested_filename,
                template_data.get('name', 'template')
            )

            try:
                os.makedirs(self.templates_directory, exist_ok=True)

                if not requested_filename:
                    filename = self._get_unique_template_filename(filename)

                template_path = os.path.join(self.templates_directory, filename)
                with open(template_path, 'w', encoding='utf-8') as handle:
                    json.dump(template_data, handle, indent=2, ensure_ascii=False)
                    handle.write('\n')
            except Exception as e:
                Logger.error(f'WebServer: Error saving template {filename}: {e}')
                return jsonify({'error': 'Unable to save template'}), 500

            return jsonify({'saved': True, 'filename': filename})

        @self.app.route('/api/templates/<path:filename>', methods=['DELETE'])
        def delete_template(filename):
            """Delete a stored template from the templates directory."""
            auth_error = self._require_admin_api_auth()
            if auth_error is not None:
                return auth_error

            safe_filename = self._sanitize_template_filename(filename)
            template_path = os.path.join(self.templates_directory, safe_filename)

            if not os.path.isfile(template_path):
                return jsonify({'error': 'Template not found'}), 404

            try:
                os.remove(template_path)
            except Exception as e:
                Logger.error(f'WebServer: Error deleting template {safe_filename}: {e}')
                return jsonify({'error': 'Unable to delete template'}), 500

            return jsonify({'deleted': True, 'filename': safe_filename})
        
        @self.app.route('/')
        def index():
            """Main page - show gallery."""
            collages = self._get_all_collages()
            
            if not collages:
                return render_template('gallery/empty.html')
            
            # Redirect to latest collage
            latest = collages[0]
            return redirect(f'/collage/{latest["session"]}')
        
        @self.app.route('/gallery')
        def gallery():
            """Gallery view with all collages."""
            if self.stats_store is not None:
                self.stats_store.track_event('gallery_view')
            collages = self._get_all_collages()

            return render_template('gallery/index.html', collages=collages)
        
        @self.app.route('/collage/<session>')
        def view_collage(session):
            """View a single collage fullscreen."""
            collage_path = self._get_safe_photo_path(session, 'collage.jpg')
            
            if collage_path is None:
                return redirect('/')
            
            if self.stats_store is not None:
                self.stats_store.track_event('collage_view')

            return render_template('gallery/collage.html', session=session)
        
        @self.app.route('/image/<session>/<filename>')
        def serve_image(session, filename):
            """Serve an image file."""
            image_path = self._get_safe_photo_path(session, filename)
            
            if image_path is None:
                return "Not found", 404
            
            if self.stats_store is not None:
                self.stats_store.track_event('image_view')
            return send_file(image_path, mimetype='image/jpeg')
        
        @self.app.route('/download/<session>/<filename>')
        def download_image(session, filename):
            """Download an image file."""
            image_path = self._get_safe_photo_path(session, filename)
            
            if image_path is None:
                return "Not found", 404
            
            if self.stats_store is not None:
                self.stats_store.track_event('download')
            return send_file(
                image_path,
                mimetype='image/jpeg',
                as_attachment=True,
                download_name=f'photobooth_{session}.jpg'
            )

        @self.app.route('/download/all-photos')
        def download_all_photos():
            """Stream every photo as a ZIP archive.

            Admin only: this hands over every session of the evening at once,
            which is an operator action, not something a guest should be able
            to do from the gallery.
            """
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            photos = self._get_all_downloadable_photos()
            if not photos:
                return 'No photos found', 404

            if self.stats_store is not None:
                self.stats_store.track_event('download')

            def generate():
                # Built incrementally rather than in a BytesIO: after an evening
                # the whole archive does not fit in a Pi's memory. ZIP_STORED
                # because JPEGs do not compress, so deflating only burns CPU.
                buffer = _ArchiveStream()
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

        @self.app.route('/admin')
        def admin_page():
            """Protected admin page."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            return self._render_admin_page()

        @self.app.route('/admin/login')
        def admin_login_page():
            """Admin login page."""
            if self._is_admin_authenticated():
                return redirect('/admin')

            logout_flag = request.args.get('logout') == '1'
            return self._render_admin_login_page(success_message='Logged out successfully.' if logout_flag else None)

        @self.app.route('/admin/login', methods=['POST'])
        def admin_login():
            """Authenticate admin user."""
            if self.admin_password is None:
                return self._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

            client_key = self._client_key()
            retry_after = self.login_throttle.retry_after(client_key)
            if retry_after:
                session.clear()
                return self._render_admin_login_page(
                    error_message=f'Too many failed attempts. Try again in {retry_after} seconds.',
                ), 429

            provided_password = request.form.get('password') or ''
            if not self._is_admin_password_valid(provided_password):
                session.clear()
                locked_for = self.login_throttle.record_failure(client_key)
                Logger.warning('WebServer: failed admin login from %s', client_key)
                if locked_for:
                    return self._render_admin_login_page(
                        error_message=f'Too many failed attempts. Try again in {locked_for} seconds.',
                    ), 429
                return self._render_admin_login_page(error_message='Invalid password.'), 403

            self.login_throttle.record_success(client_key)
            session.clear()
            session['is_admin_authenticated'] = True
            return redirect('/admin')

        @self.app.route('/admin/logout')
        def admin_logout():
            """Log out admin user."""
            session.clear()
            return redirect('/admin/login?logout=1')

        @self.app.route('/admin/delete-all', methods=['POST'])
        def delete_all_sessions():
            """Delete all saved sessions after password validation."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            if self.admin_password is None:
                session.clear()
                return self._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

            try:
                deleted_sessions = self._delete_all_sessions()
            except Exception:
                return self._render_admin_page(error_message='Error while deleting files.'), 500

            return self._render_admin_page(success_message=f'{deleted_sessions} session(s) deleted.')

        @self.app.route('/admin/config', methods=['POST'])
        def save_admin_config():
            """Save config.ini after password validation."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            if self.admin_password is None:
                session.clear()
                return self._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

            submitted_form_values = {}

            try:
                current_config = self._load_config_text()
                parser = config_form.load_parser(current_config)
                updates, submitted_form_values = config_form.collect_updates(request.form, parser)
                updated_config = config_form.apply_updates(current_config, updates)
            except ValueError as exc:
                return self._render_admin_page(error_message=str(exc), form_values=submitted_form_values), 400
            except Exception as exc:
                Logger.error(f'WebServer: Error while preparing config.ini update: {exc}')
                return self._render_admin_page(error_message='Error while preparing config.ini.', form_values=request.form), 500

            try:
                self._save_config_text(updated_config)
            except Exception:
                return self._render_admin_page(error_message='Error while saving config.ini.', form_values=submitted_form_values), 500

            try:
                updated_config = self._load_config_text()
                self._refresh_admin_password_from_config(updated_config)
            except Exception:
                return self._render_admin_page(success_message='config.ini saved. Restart app to apply all changes.')

            if self.admin_password is None:
                session.clear()
                return self._render_admin_login_page(success_message='config.ini saved. Admin password disabled. Sign in is now disabled.')

            return self._render_admin_page(success_message='config.ini saved. Restart app to apply all changes.')

        @self.app.route('/admin/restart', methods=['POST'])
        def restart_app():
            """Restart application after password validation."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            if self.admin_password is None:
                session.clear()
                return self._render_admin_login_page(error_message='Admin access is disabled. Configure ADMIN_PASSWORD in config.ini.'), 403

            if not callable(self.restart_callback):
                return self._render_admin_page(error_message='Restart callback is unavailable.'), 500

            try:
                self.restart_callback()
            except Exception as e:
                Logger.error(f'WebServer: Error restarting app: {e}')
                return self._render_admin_page(error_message='Error while restarting app.'), 500

            return self._render_admin_page(success_message='Application restart requested. Page may become unavailable for a few seconds.')
        
        @self.app.route('/stats')
        def statistics():
            """Usage analytics: lists every session, so admin only."""
            auth_redirect = self._require_admin_auth()
            if auth_redirect is not None:
                return auth_redirect

            stats = self.stats_store.load() if self.stats_store is not None else {
                'photos_taken': 0,
                'prints': 0,
                'downloads': 0,
                'gallery_views': 0,
                'collage_views': 0,
                'image_views': 0,
                'first_photo_date': None,
                'last_photo_date': None,
                'last_print_date': None,
                'last_download_date': None,
                'sessions': [],
            }
            collages = self._get_all_collages()
            downloadable_photos = self._get_all_downloadable_photos()

            return render_template(
                'stats.html',
                collages=collages,
                downloadable_photos=downloadable_photos,
                print_limit=self.stats_store.get_print_limit_info() if self.stats_store is not None else {
                    'enabled': False,
                    'max_prints': None,
                    'prints': 0,
                    'remaining': None,
                    'reached': False,
                },
                stats=stats,
            )
        
        # Captive portal detection URLs
        @self.app.route('/generate_204')
        @self.app.route('/gen_204')
        @self.app.route('/hotspot-detect.html')
        @self.app.route('/library/test/success.html')
        @self.app.route('/canonical.html')
        @self.app.route('/connecttest.txt')
        @self.app.route('/ncsi.txt')
        @self.app.route('/redirect')
        @self.app.route('/fwlink')
        @self.app.route('/check_network_status.txt')
        @self.app.route('/mobile/status.php')
        def captive():
            return redirect('/')
    
    def start(self, force_restart=False):
        """Start the web server in a separate thread."""
        with self._server_lock:
            if self.server_thread and self.server_thread.is_alive() and not force_restart:
                Logger.warning('WebServer: Server already running')
                return True

            if force_restart and self.server is not None:
                try:
                    self.server.shutdown()
                except Exception as e:
                    Logger.warning(f'WebServer: shutdown before restart failed: {e}')
                self.server = None

            startup_event = threading.Event()
            startup_state = {'error': None}

            def run_server():
                try:
                    Logger.info(f'WebServer: Starting on {self.host}:{self.port}')
                    self.server = make_server(self.host, self.port, self.app, threaded=True)
                    startup_event.set()
                    self.server.serve_forever()
                except BaseException as e:
                    startup_state['error'] = e
                    if not startup_event.is_set():
                        startup_event.set()

                    # werkzeug can abort startup with SystemExit on bind errors
                    # (for example "Address already in use"). Catch it here so
                    # the Kivy app does not block for the full timeout.
                    if isinstance(e, SystemExit):
                        Logger.error(
                            f'WebServer: Failed to start on {self.host}:{self.port}: '
                            f'process exited during startup (likely port already in use)'
                        )
                    else:
                        Logger.error(f'WebServer: Failed to start on {self.host}:{self.port}: {e}')
                finally:
                    self.server = None

            self.server_thread = threading.Thread(target=run_server, name='webserver-main', daemon=True)
            self.server_thread.start()
            startup_event.wait(timeout=5)

            if not startup_event.is_set():
                Logger.error('WebServer: Server startup timed out')
                return False

            if startup_state['error'] is not None:
                return False

            self._ensure_watchdog()
            Logger.info('WebServer: Server started successfully')
            return True
    
    def stop(self):
        """Stop the web server."""
        self._watchdog_stop.set()
        if self.server is not None:
            self.server.shutdown()
            Logger.info('WebServer: Server stopped')
        else:
            Logger.info('WebServer: Stop requested but server is not running')

        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=5)
        self.server_thread = None

        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=5)
        self._watchdog_thread = None
