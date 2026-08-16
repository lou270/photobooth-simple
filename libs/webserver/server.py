import hmac
import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, render_template, redirect, session
from werkzeug.serving import make_server
from kivy.logger import Logger

from libs.login_throttle import LoginThrottle
from libs.webserver import config_form, paths
from libs.template_schema import TemplateValidationError, validate_template



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

    def _delete_all_log_files(self):
        """Delete all direct files from the logs directory."""
        deleted_files = 0

        if not os.path.isdir(self.logs_directory):
            return deleted_files

        for log_file in self._get_log_files():
            log_path = paths.safe_log_path(self.logs_directory, log_file['filename'])
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
                if not os.path.isdir(session_path) or not paths.is_valid_session(session_dir):
                    continue

                for filename in sorted(os.listdir(session_path)):
                    if not paths.is_valid_image_filename(filename):
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
                    if not os.path.isdir(session_path) or not paths.is_valid_session(session_dir):
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
        """Mount the three areas: guests, operator, JSON.

        Imported here rather than at module scope: the blueprints import back
        into this package, whose __init__ imports this module. By the time a
        server is constructed the package is fully loaded, so the cycle only
        exists at import time and this sidesteps it.
        """
        from libs.webserver import admin, api, gallery

        for area in (gallery, admin, api):
            self.app.register_blueprint(area.create_blueprint(self))
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
