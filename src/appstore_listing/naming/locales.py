"""Map language folder names onto App Store Connect locale codes.

App Store Connect accepts a fixed, slightly irregular set of locale codes: some
carry a region (``de-DE``, ``pt-BR``), some do not (``it``, ``ja``, ``ru``), and
Chinese uses script subtags (``zh-Hans``).  Folder names in the wild come in every
shape -- ``it-IT``, ``it_IT``, ``Italian``, ``zh-hans``.  This module normalises
all of them onto the canonical code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..errors import UnknownLocaleError

#: Every locale App Store Connect accepts for app metadata, in canonical spelling.
APP_STORE_LOCALES: tuple[str, ...] = (
    "ar-SA",
    "ca",
    "cs",
    "da",
    "de-DE",
    "el",
    "en-AU",
    "en-CA",
    "en-GB",
    "en-US",
    "es-ES",
    "es-MX",
    "fi",
    "fr-CA",
    "fr-FR",
    "he",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "ms",
    "nl-NL",
    "no",
    "pl",
    "pt-BR",
    "pt-PT",
    "ro",
    "ru",
    "sk",
    "sv",
    "th",
    "tr",
    "uk",
    "vi",
    "zh-Hans",
    "zh-Hant",
)

#: Extra spellings that resolve to a canonical locale.  Keys are matched after
#: :func:`_normalise_key` (lowercase, separators stripped).
_ALIASES: dict[str, str] = {
    # region-tagged folders for locales App Store spells without a region
    "itit": "it",
    "jajp": "ja",
    "kokr": "ko",
    "ruru": "ru",
    "nlbe": "nl-NL",
    "nlnl": "nl-NL",
    "svse": "sv",
    "dadk": "da",
    "fifi": "fi",
    "nbno": "no",
    "nno": "no",
    "nono": "no",
    "plpl": "pl",
    "trtr": "tr",
    "thth": "th",
    "vivn": "vi",
    "ukua": "uk",
    "cscz": "cs",
    "sksk": "sk",
    "huhu": "hu",
    "rrro": "ro",
    "roro": "ro",
    "hrhr": "hr",
    "elgr": "el",
    "heil": "he",
    "iwil": "he",
    "iw": "he",
    "hiin": "hi",
    "idid": "id",
    "inid": "id",
    "in": "id",
    "msmy": "ms",
    "caes": "ca",
    "arae": "ar-SA",
    "ar": "ar-SA",
    # Chinese
    "zhcn": "zh-Hans",
    "zhsg": "zh-Hans",
    "zhhans": "zh-Hans",
    "zhhanscn": "zh-Hans",
    "zhtw": "zh-Hant",
    "zhhk": "zh-Hant",
    "zhhant": "zh-Hant",
    "zhhanttw": "zh-Hant",
    "zh": "zh-Hans",
    # bare language codes for locales App Store spells with a region
    "de": "de-DE",
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "pt": "pt-PT",
    "nl": "nl-NL",
    # regional variants App Store folds into a parent locale
    "deat": "de-DE",
    "dech": "de-DE",
    "enin": "en-GB",
    "enie": "en-GB",
    "ennz": "en-AU",
    "enza": "en-GB",
    "esar": "es-MX",
    "escl": "es-MX",
    "esco": "es-MX",
    "es419": "es-MX",
    "frbe": "fr-FR",
    "frch": "fr-FR",
    "itch": "it",
    # English language names, handy for hand-made folders
    "english": "en-US",
    "german": "de-DE",
    "french": "fr-FR",
    "italian": "it",
    "spanish": "es-ES",
    "portuguese": "pt-PT",
    "brazilianportuguese": "pt-BR",
    "japanese": "ja",
    "korean": "ko",
    "russian": "ru",
    "dutch": "nl-NL",
    "swedish": "sv",
    "danish": "da",
    "finnish": "fi",
    "norwegian": "no",
    "polish": "pl",
    "turkish": "tr",
    "thai": "th",
    "vietnamese": "vi",
    "ukrainian": "uk",
    "czech": "cs",
    "slovak": "sk",
    "hungarian": "hu",
    "romanian": "ro",
    "croatian": "hr",
    "greek": "el",
    "hebrew": "he",
    "hindi": "hi",
    "indonesian": "id",
    "malay": "ms",
    "catalan": "ca",
    "arabic": "ar-SA",
    "simplifiedchinese": "zh-Hans",
    "chinesesimplified": "zh-Hans",
    "traditionalchinese": "zh-Hant",
    "chinesetraditional": "zh-Hant",
}

_CANONICAL_BY_KEY: dict[str, str] = {}


def _normalise_key(name: str) -> str:
    """Lowercase ``name`` and drop every separator, so ``pt_BR`` == ``pt-br``."""
    return re.sub(r"[^a-z0-9]", "", name.strip().lower())


for _locale in APP_STORE_LOCALES:
    _CANONICAL_BY_KEY[_normalise_key(_locale)] = _locale


def resolve_locale(name: str, overrides: Mapping[str, str] | None = None) -> str:
    """Return the App Store Connect locale code for a language folder name.

    ``overrides`` lets a caller pin a folder name that this module would guess
    wrong (or not at all); its keys are matched case- and separator-insensitively.

    Raises :class:`UnknownLocaleError` when the name cannot be resolved.
    """
    key = _normalise_key(name)
    if not key:
        raise UnknownLocaleError(f"Empty language folder name: {name!r}")

    if overrides:
        for raw_key, value in overrides.items():
            if _normalise_key(raw_key) == key:
                return value

    if key in _CANONICAL_BY_KEY:
        return _CANONICAL_BY_KEY[key]
    if key in _ALIASES:
        return _ALIASES[key]

    raise UnknownLocaleError(
        f"Cannot map language folder {name!r} to an App Store Connect locale. "
        f"Add an override, or rename the folder to one of: "
        f"{', '.join(APP_STORE_LOCALES[:6])}, ..."
    )


def looks_like_locale(name: str, overrides: Mapping[str, str] | None = None) -> bool:
    """True when :func:`resolve_locale` would succeed for ``name``."""
    try:
        resolve_locale(name, overrides)
    except UnknownLocaleError:
        return False
    return True
