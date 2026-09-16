"""JSON endpoints, every one of them behind the admin session."""

import hashlib
import io
import os
import json
import re
import time

import cv2
import numpy as np
from flask import Blueprint, g, jsonify, request, send_file
from kivy.logger import Logger
from PIL import Image

from libs import i18n
from libs.template_collage import TemplateCollage
from libs.webserver import paths
from libs.template_schema import (
    MAX_EMBEDDED_IMAGE_BYTES,
    MAX_PAGE_PIXELS,
    MAX_PAGE_SIDE,
    TemplateValidationError,
    validate_template,
)

# Images the template editor stores: the pictures an operator adds to a design
# and the layers it flattens them into. A flattened layer is drawn at 600 dpi,
# twice the template's own resolution on each side.
ASSET_FORMATS = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}
ASSET_MIMETYPES = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp'}
MAX_ASSET_SIDE = 2 * MAX_PAGE_SIDE
MAX_ASSET_PIXELS = MAX_PAGE_PIXELS
# An unused image is kept this long before a clean-up removes it: the editor
# uploads a picture as soon as it is added, well before the template that uses
# it is saved, possibly from another browser than the one cleaning up.
ASSET_GRACE_SECONDS = 24 * 60 * 60
ASSET_REFERENCE_PATTERN = re.compile(r'assets/([0-9a-f]{32}\.(?:png|jpg|webp))')


def read_asset(data):
    """Check uploaded bytes are an image the booth can draw; return (extension, width, height).

    The header is read before anything is decoded, so a small file claiming
    an enormous picture is refused without the memory it would take. OpenCV
    then decodes it, since OpenCV is what draws it on the booth.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format, (width, height) = image.format, image.size
    except Exception:
        raise ValueError('not an image') from None

    if image_format not in ASSET_FORMATS:
        raise ValueError('only PNG, JPEG and WebP images are accepted')
    if width > MAX_ASSET_SIDE or height > MAX_ASSET_SIDE or width * height > MAX_ASSET_PIXELS:
        raise ValueError(f'image is {width}x{height} pixels, too large for the booth')
    if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED) is None:
        raise ValueError('image could not be decoded')

    return ASSET_FORMATS[image_format], width, height


def referenced_assets(templates_directory):
    """Names of the asset images some template file mentions, in any field."""
    names = set()
    if not os.path.isdir(templates_directory):
        return names
    for filename in os.listdir(templates_directory):
        if not filename.lower().endswith('.json'):
            continue
        try:
            with open(os.path.join(templates_directory, filename), 'r', encoding='utf-8') as handle:
                names.update(ASSET_REFERENCE_PATTERN.findall(handle.read()))
        except OSError as exc:
            # Unreadable now is not unused: better an image too many than a
            # template that lost its frame.
            Logger.error(f'WebServer: Error reading template {filename} for assets: {exc}')
            raise
    return names


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
            return jsonify({'error': i18n.translate(g.lang, 'web.admin.log_not_found')}), 404

        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as handle:
                content = handle.read()
        except Exception as e:
            Logger.error(f'WebServer: Error reading log file {filename}: {e}')
            return jsonify({'error': i18n.translate(g.lang, 'web.admin.read_log_failed')}), 500

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
            return jsonify({'error': i18n.translate(g.lang, 'web.admin.delete_logs_failed')}), 500

        return jsonify({'deleted': deleted_files})

    @blueprint.route('/api/templates', methods=['GET'])
    def list_templates():
        """List templates stored on disk."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        return jsonify({
            'templates': server._load_template_definitions(),
            # What {event}, {date} and {time} print as today, so the editor
            # previews a text the way the booth will print it.
            'text_values': server._event_text_values(),
        })

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

    @blueprint.route('/api/templates/preview', methods=['POST'])
    def preview_template():
        """Assemble a template the way the booth will, with the sample photos.

        The editor draws a design itself, in the browser; this is the booth's
        own drawing of the same template, to check the two agree before an
        evening depends on it.
        """
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({'error': 'Invalid JSON payload'}), 400

        try:
            text_values = server._event_text_values()
            collage = TemplateCollage(template=payload.get('template'), text_values=lambda: text_values,
                                      template_dir=server.templates_directory)
            canvas = collage.assemble_with_dummies()
        except TemplateValidationError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            Logger.error(f'WebServer: Error previewing a template: {exc}')
            return jsonify({'error': 'Unable to preview template'}), 500

        encoded = cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])[1]
        return send_file(io.BytesIO(encoded.tobytes()), mimetype='image/jpeg')

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

    def assets_directory():
        return os.path.join(server.templates_directory, 'assets')

    @blueprint.route('/api/template-assets', methods=['POST'])
    def upload_template_asset():
        """Store an image for a designed template, named after its content.

        Kept as sent rather than re-encoded, so a PNG keeps its transparency
        exactly. The same picture uploaded twice is one file.
        """
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        uploaded = request.files.get('image')
        data = uploaded.read(MAX_EMBEDDED_IMAGE_BYTES + 1) if uploaded is not None else b''
        if not data:
            return jsonify({'error': 'No image received'}), 400
        if len(data) > MAX_EMBEDDED_IMAGE_BYTES:
            return jsonify({'error': f'image is above the {MAX_EMBEDDED_IMAGE_BYTES} byte limit'}), 400

        try:
            extension, width, height = read_asset(data)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        name = f'{hashlib.sha256(data).hexdigest()[:32]}.{extension}'
        path = os.path.join(assets_directory(), name)
        try:
            os.makedirs(assets_directory(), exist_ok=True)
            if os.path.isfile(path):
                # Touched, so a clean-up does not take an image just reused.
                os.utime(path)
            else:
                partial = path + '.part'
                with open(partial, 'wb') as handle:
                    handle.write(data)
                os.replace(partial, path)
        except OSError as exc:
            Logger.error(f'WebServer: Error saving template asset {name}: {exc}')
            return jsonify({'error': 'Unable to save image'}), 500

        return jsonify({'filename': f'assets/{name}', 'width': width, 'height': height})

    @blueprint.route('/api/template-assets/<name>', methods=['GET'])
    def read_template_asset(name):
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        path = paths.safe_template_asset_path(assets_directory(), name)
        if path is None:
            return jsonify({'error': 'Image not found'}), 404

        response = send_file(path, mimetype=ASSET_MIMETYPES[name.rsplit('.', 1)[1]])
        # Named after its content: the same name is always the same picture.
        response.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
        return response

    @blueprint.route('/api/template-files/<path:name>', methods=['GET'])
    def read_template_file(name):
        """An image a template names as a plain file, put beside the templates by hand.

        The same names a template may use for its layers, and only those, so
        the editor can show and flatten a template made before assets existed.
        """
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        path = paths.safe_template_image_path(server.templates_directory, name)
        if path is None:
            return jsonify({'error': 'Image not found'}), 404

        extension = name.rsplit('.', 1)[1].lower()
        return send_file(path, mimetype=ASSET_MIMETYPES['jpg' if extension == 'jpeg' else extension])

    @blueprint.route('/api/template-assets/cleanup', methods=['POST'])
    def clean_up_template_assets():
        """Remove images no template mentions any more, once they are old enough."""
        auth_error = server._require_admin_api_auth()
        if auth_error is not None:
            return auth_error

        directory = assets_directory()
        if not os.path.isdir(directory):
            return jsonify({'deleted': []})

        try:
            used = referenced_assets(server.templates_directory)
        except OSError:
            return jsonify({'error': 'Unable to read the templates'}), 500

        deleted = []
        cutoff = time.time() - ASSET_GRACE_SECONDS
        for name in sorted(os.listdir(directory)):
            path = paths.safe_template_asset_path(directory, name)
            if path is None or name in used or os.path.getmtime(path) > cutoff:
                continue
            try:
                os.remove(path)
                deleted.append(name)
            except OSError as exc:
                Logger.error(f'WebServer: Error removing template asset {name}: {exc}')

        return jsonify({'deleted': deleted})

    return blueprint
