"""Image processing, independent of any UI framework.

Nothing here imports Kivy: these are the transforms applied to photos, and they
have to be testable without a window.
"""

from libs.imaging.filters import DEFAULT_FILTER, FILTERS, apply_filter, filter_keys

__all__ = ['DEFAULT_FILTER', 'FILTERS', 'apply_filter', 'filter_keys']
