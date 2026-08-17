"""Interface text, kept out of the screens and templates that display it.

Two JSON dictionaries under locales/ (one per language) map a dotted key to a
string, e.g. 'start.title' -> 'PHOTO BOOTH'. Kivy screens are built once at
startup, so the booth carries one language for the life of the process,
picked from config.ini like any other setting; the web guest pages instead
pick a language per request, from the phone's own Accept-Language.
"""

import json
import logging
from pathlib import Path

Logger = logging.getLogger('kivy.photobooth')

LOCALES_DIR = Path(__file__).resolve().parents[1] / 'locales'

AVAILABLE_LANGUAGES = ('en', 'fr')
DEFAULT_LANGUAGE = 'en'

_catalogs = {}
_missing_keys_logged = set()
_current_language = DEFAULT_LANGUAGE


def _flatten(prefix, node, out):
    for key, value in node.items():
        dotted = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            _flatten(dotted, value, out)
        else:
            out[dotted] = value


def _load_catalog(lang):
    if lang in _catalogs:
        return _catalogs[lang]

    path = LOCALES_DIR / f'{lang}.json'
    flat = {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
        _flatten('', data, flat)
    except FileNotFoundError:
        Logger.error('i18n: locale file not found: %s', path)
    except (json.JSONDecodeError, OSError) as exc:
        Logger.error('i18n: could not load locale %r: %s', lang, exc)

    _catalogs[lang] = flat
    return flat


def set_language(lang):
    """Fix the language used by t() for the rest of this process."""
    global _current_language
    _current_language = lang if lang in AVAILABLE_LANGUAGES else DEFAULT_LANGUAGE


def get_language():
    return _current_language


def translate(lang, key, **kwargs):
    """Resolve one dotted key in the given language, falling back to English.

    A key missing everywhere returns the key itself, so a gap in the
    translation files shows up as an ugly-but-visible string rather than a
    crash, and is logged once rather than once per render.
    """
    catalog = _load_catalog(lang if lang in AVAILABLE_LANGUAGES else DEFAULT_LANGUAGE)
    text = catalog.get(key)

    if text is None and lang != DEFAULT_LANGUAGE:
        text = _load_catalog(DEFAULT_LANGUAGE).get(key)

    if text is None:
        if key not in _missing_keys_logged:
            _missing_keys_logged.add(key)
            Logger.warning('i18n: missing translation key %r', key)
        text = key

    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            Logger.warning('i18n: bad placeholders for key %r', key)
            return text

    return text


def t(key, **kwargs):
    """Translate a key in the booth's current language (Kivy screens)."""
    return translate(_current_language, key, **kwargs)


def bundle(lang, keys):
    """A {name: text} dict for handing strings to JS, e.g. for tojson.

    `keys` is either a list of dotted keys (used as-is for the JS name too),
    or a {js_name: dotted_key} mapping when the script wants a shorter name
    than the translation file's own key.
    """
    if isinstance(keys, dict):
        return {name: translate(lang, key) for name, key in keys.items()}
    return {key: translate(lang, key) for key in keys}
