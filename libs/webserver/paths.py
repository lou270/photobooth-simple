"""Turning a request path into a file on disk, or refusing to.

Every function here stands between the network and the filesystem. They accept
only the shapes the booth itself produces, and resolve the result before
comparing it to the directory it must stay inside, so a name that climbs out
with `..` or a symlink is rejected rather than served.
"""

import os
import re

# Session directories are named by the booth: 20260816_120000.
SESSION_PATTERN = re.compile(r'^\d{8}_\d{6}$')
# The only photos a session holds: the collage and the captures it came from.
IMAGE_FILENAME_PATTERN = re.compile(r'^(?:collage|capture-\d+)\.jpg$', re.IGNORECASE)
# A log file name carries no separator, so it cannot name another directory.
LOG_FILENAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')


def is_valid_session(session):
    """True when the name matches a session directory the booth would create."""
    return isinstance(session, str) and bool(SESSION_PATTERN.fullmatch(session))


def is_valid_image_filename(filename):
    """True when the name matches a photo the booth would have saved."""
    return isinstance(filename, str) and bool(IMAGE_FILENAME_PATTERN.fullmatch(filename))


def safe_photo_path(save_directory, session, filename):
    """Resolve a photo inside a session, or None when the request is not one."""
    if not is_valid_session(session) or not is_valid_image_filename(filename):
        return None

    base_path = os.path.realpath(save_directory)
    requested_path = os.path.realpath(os.path.join(base_path, session, filename))

    # realpath first, then compare: a symlink pointing out of the gallery must
    # not be served just because its name looked right.
    if not requested_path.startswith(base_path + os.sep):
        return None

    if not os.path.isfile(requested_path):
        return None

    return requested_path


def safe_log_path(logs_directory, filename):
    """Resolve a log file that is a direct child of the logs directory."""
    if not isinstance(filename, str) or not LOG_FILENAME_PATTERN.fullmatch(filename):
        return None

    base_path = os.path.realpath(logs_directory)
    requested_path = os.path.realpath(os.path.join(base_path, filename))

    if os.path.dirname(requested_path) != base_path:
        return None

    if not os.path.isfile(requested_path):
        return None

    return requested_path


def sanitize_template_filename(filename=None, template_name='template'):
    """Return a safe JSON file name for template storage.

    Strips any directory part and anything that is not a plain name character,
    so a template can only ever be written next to the others.
    """
    source = filename or template_name or 'template'
    safe_name = os.path.basename(source).strip()

    if safe_name.lower().endswith('.json'):
        safe_name = safe_name[:-5]

    safe_name = safe_name.replace(' ', '_')
    safe_name = re.sub(r'[^A-Za-z0-9._-]', '', safe_name)
    safe_name = safe_name.strip('._-') or 'template'

    return f'{safe_name}.json'


def unique_template_filename(templates_directory, filename):
    """Return a name that does not overwrite an existing template."""
    base_name, extension = os.path.splitext(filename)
    candidate = filename
    counter = 1

    while os.path.exists(os.path.join(templates_directory, candidate)):
        candidate = f'{base_name}_{counter}{extension}'
        counter += 1

    return candidate
