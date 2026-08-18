"""Screen identifiers.

Separate from the manager on purpose: a screen has to name where it is going,
and the manager has to build every screen. Keeping the names here is what stops
that from being a circular import.
"""


class ScreenNames:
    START = 'start'
    SELECT_FORMAT = 'select_format'
    ERROR = 'error'
    COUNTDOWN = 'countdown'
    CONFIRM_CAPTURE = 'confirm_capture'
    PROCESSING = 'processing'
    REVIEW = 'review'
    COLLECT = 'collect'
    COPYING = 'copying'
    REMOTE_GALLERY = 'remote_gallery'
