"""JSON endpoints, every one of them behind the admin session."""

import os
import json

from flask import Blueprint, jsonify, request
from kivy.logger import Logger

from libs.webserver import paths
from libs.template_schema import TemplateValidationError, validate_template


def create_blueprint(server):
    """Build the api routes, closing over the running WebServer."""
    blueprint = Blueprint('api', __name__)

    @blueprint.route('/api/admin/logs', methods=['GET'])
    def list_admin_logs():
        """List available log files for authenticated admins."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        return jsonify({'logs': server._get_log_files()})

    @blueprint.route('/api/admin/logs/<path:filename>', methods=['GET'])
    def read_admin_log(filename):
        """Read one log file for authenticated admins."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        log_path = paths.safe_log_path(server.logs_directory, filename)
        if log_path is None:
            return jsonify({'error': 'Log file not found'}), 404

        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as handle:
                content = handle.read()
        except Exception as e:
            Logger.error(f'WebServer: Error reading log file {filename}: {e}')
            return jsonify({'error': 'Unable to read log file'}), 500

        return jsonify({'filename': os.path.basename(log_path), 'content': content})

    @blueprint.route('/api/admin/logs', methods=['DELETE'])
    def delete_admin_logs():
        """Delete all log files for authenticated admins."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        try:
            deleted_files = server._delete_all_log_files()
        except Exception as e:
            Logger.error(f'WebServer: Error deleting log files: {e}')
            return jsonify({'error': 'Unable to delete log files'}), 500

        return jsonify({'deleted': deleted_files})

    @blueprint.route('/api/templates', methods=['GET'])
    def list_templates():
        """List templates stored on disk."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        return jsonify({'templates': server._load_template_definitions()})

    @blueprint.route('/api/templates', methods=['POST'])
    def save_template():
        """Save a template into the templates directory."""
        auth_error = server._require_admin_api_auth()
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
        filename = paths.sanitize_template_filename(
            requested_filename,
            template_data.get('name', 'template')
        )

        try:
            os.makedirs(server.templates_directory, exist_ok=True)

            if not requested_filename:
                filename = paths.unique_template_filename(server.templates_directory, filename)

            template_path = os.path.join(server.templates_directory, filename)
            with open(template_path, 'w', encoding='utf-8') as handle:
                json.dump(template_data, handle, indent=2, ensure_ascii=False)
                handle.write('\n')
        except Exception as e:
            Logger.error(f'WebServer: Error saving template {filename}: {e}')
            return jsonify({'error': 'Unable to save template'}), 500

        return jsonify({'saved': True, 'filename': filename})

    @blueprint.route('/api/templates/<path:filename>', methods=['DELETE'])
    def delete_template(filename):
        """Delete a stored template from the templates directory."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        safe_filename = paths.sanitize_template_filename(filename)
        template_path = os.path.join(server.templates_directory, safe_filename)

        if not os.path.isfile(template_path):
            return jsonify({'error': 'Template not found'}), 404

        try:
            os.remove(template_path)
        except Exception as e:
            Logger.error(f'WebServer: Error deleting template {safe_filename}: {e}')
            return jsonify({'error': 'Unable to delete template'}), 500

        return jsonify({'deleted': True, 'filename': safe_filename})

    return blueprint
