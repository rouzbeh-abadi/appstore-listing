"""Map device folder names onto App Store Connect ``screenshotDisplayType`` values.

Folder names are written by humans and by tools, so they arrive in every shape:
``iPhone-6.9``, ``iphone_69``, ``iPad 13 Landscape``, ``IPAD_PRO_3GEN_129``,
``Apple Watch Ultra``.  :func:`resolve_display_type` accepts all of those.

Note on sizes: Apple did **not** add new enum values for the 6.9-inch iPhone or
the 13-inch iPad -- those screenshots go into the existing 6.7-inch and 12.9-inch
(3rd gen) display types, whose accepted resolutions were widened instead.  The
alias table below encodes that, and any mapping can be overridden per project.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ..errors import UnknownDeviceError

#: Every ``screenshotDisplayType`` value App Store Connect accepts.
DISPLAY_TYPES: tuple[str, ...] = (
    "APP_IPHONE_67",
    "APP_IPHONE_65",
    "APP_IPHONE_61",
    "APP_IPHONE_58",
    "APP_IPHONE_55",
    "APP_IPHONE_47",
    "APP_IPHONE_40",
    "APP_IPHONE_35",
    "APP_IPAD_PRO_3GEN_129",
    "APP_IPAD_PRO_3GEN_11",
    "APP_IPAD_PRO_129",
    "APP_IPAD_105",
    "APP_IPAD_97",
    "APP_DESKTOP",
    "APP_WATCH_ULTRA",
    "APP_WATCH_SERIES_10",
    "APP_WATCH_SERIES_7",
    "APP_WATCH_SERIES_4",
    "APP_WATCH_SERIES_3",
    "APP_APPLE_TV",
    "APP_APPLE_VISION_PRO",
    "IMESSAGE_APP_IPHONE_67",
    "IMESSAGE_APP_IPHONE_65",
    "IMESSAGE_APP_IPHONE_61",
    "IMESSAGE_APP_IPHONE_58",
    "IMESSAGE_APP_IPHONE_55",
    "IMESSAGE_APP_IPHONE_47",
    "IMESSAGE_APP_IPHONE_40",
    "IMESSAGE_APP_IPAD_PRO_3GEN_129",
    "IMESSAGE_APP_IPAD_PRO_3GEN_11",
    "IMESSAGE_APP_IPAD_PRO_129",
    "IMESSAGE_APP_IPAD_105",
    "IMESSAGE_APP_IPAD_97",
)

#: Human labels, used by the UI and by ``--list-devices``.
DISPLAY_TYPE_LABELS: dict[str, str] = {
    "APP_IPHONE_67": 'iPhone 6.9" / 6.7"',
    "APP_IPHONE_65": 'iPhone 6.5"',
    "APP_IPHONE_61": 'iPhone 6.1"',
    "APP_IPHONE_58": 'iPhone 5.8"',
    "APP_IPHONE_55": 'iPhone 5.5"',
    "APP_IPHONE_47": 'iPhone 4.7"',
    "APP_IPHONE_40": 'iPhone 4"',
    "APP_IPHONE_35": 'iPhone 3.5"',
    "APP_IPAD_PRO_3GEN_129": 'iPad 13" / 12.9" (3rd gen)',
    "APP_IPAD_PRO_3GEN_11": 'iPad 11" (3rd gen)',
    "APP_IPAD_PRO_129": 'iPad Pro 12.9" (2nd gen)',
    "APP_IPAD_105": 'iPad 10.5"',
    "APP_IPAD_97": 'iPad 9.7"',
    "APP_DESKTOP": "Mac",
    "APP_WATCH_ULTRA": "Apple Watch Ultra",
    "APP_WATCH_SERIES_10": "Apple Watch Series 10",
    "APP_WATCH_SERIES_7": "Apple Watch Series 7",
    "APP_WATCH_SERIES_4": "Apple Watch Series 4",
    "APP_WATCH_SERIES_3": "Apple Watch Series 3",
    "APP_APPLE_TV": "Apple TV",
    "APP_APPLE_VISION_PRO": "Apple Vision Pro",
}

#: Tokens that carry no device information and are stripped before matching.
_NOISE = {
    "inch",
    "in",
    "display",
    "displays",
    "screen",
    "screenshots",
    "screenshot",
    "snapshots",
    "snapshot",
    "apple",
    "app",
    "ios",
    "landscape",
    "portrait",
    "land",
    "port",
    "horizontal",
    "vertical",
    "gen",
    "generation",
    "the",
    "new",
    "max",
    "plus",
    "mini",
    "air",
    "se",
}

#: Screen size (in inches, as written by Apple) -> display type, per family.
_IPHONE_SIZES = {
    "6.9": "APP_IPHONE_67",
    "6.7": "APP_IPHONE_67",
    "6.5": "APP_IPHONE_65",
    "6.3": "APP_IPHONE_61",
    "6.1": "APP_IPHONE_61",
    "5.8": "APP_IPHONE_58",
    "5.5": "APP_IPHONE_55",
    "4.7": "APP_IPHONE_47",
    "4.0": "APP_IPHONE_40",
    "3.5": "APP_IPHONE_35",
}

_IPAD_SIZES = {
    "13.0": "APP_IPAD_PRO_3GEN_129",
    "12.9": "APP_IPAD_PRO_3GEN_129",
    "11.0": "APP_IPAD_PRO_3GEN_11",
    "10.9": "APP_IPAD_PRO_3GEN_11",
    "10.5": "APP_IPAD_105",
    "10.2": "APP_IPAD_105",
    "9.7": "APP_IPAD_97",
}

_WATCH_SIZES = {
    "49": "APP_WATCH_ULTRA",
    "46": "APP_WATCH_SERIES_10",
    "45": "APP_WATCH_SERIES_7",
    "44": "APP_WATCH_SERIES_4",
    "42": "APP_WATCH_SERIES_4",
    "41": "APP_WATCH_SERIES_7",
    "40": "APP_WATCH_SERIES_4",
    "38": "APP_WATCH_SERIES_3",
}

#: Pixel dimensions -> display type, used when a folder name says nothing useful.
#: Orientation is irrelevant to App Store Connect, so both are registered.
_RESOLUTIONS: dict[tuple[int, int], str] = {}


def _register_resolutions(pairs: dict[tuple[int, int], str]) -> None:
    for (width, height), display_type in pairs.items():
        _RESOLUTIONS.setdefault((width, height), display_type)
        _RESOLUTIONS.setdefault((height, width), display_type)


_register_resolutions(
    {
        # iPhone -- 6.9" and 6.7" share APP_IPHONE_67, so the overlaps are harmless.
        (1320, 2868): "APP_IPHONE_67",
        (1290, 2796): "APP_IPHONE_67",
        (1284, 2778): "APP_IPHONE_67",
        (1242, 2688): "APP_IPHONE_65",
        (1206, 2622): "APP_IPHONE_61",
        (1179, 2556): "APP_IPHONE_61",
        (1170, 2532): "APP_IPHONE_61",
        (1125, 2436): "APP_IPHONE_58",
        (1242, 2208): "APP_IPHONE_55",
        (750, 1334): "APP_IPHONE_47",
        (640, 1136): "APP_IPHONE_40",
        (640, 960): "APP_IPHONE_35",
        # iPad
        (2064, 2752): "APP_IPAD_PRO_3GEN_129",
        (2048, 2732): "APP_IPAD_PRO_3GEN_129",
        (1668, 2388): "APP_IPAD_PRO_3GEN_11",
        (1640, 2360): "APP_IPAD_PRO_3GEN_11",
        (1668, 2224): "APP_IPAD_105",
        (1536, 2048): "APP_IPAD_97",
        # Watch
        (410, 502): "APP_WATCH_ULTRA",
        (416, 496): "APP_WATCH_SERIES_10",
        (396, 484): "APP_WATCH_SERIES_7",
        (368, 448): "APP_WATCH_SERIES_4",
        (312, 390): "APP_WATCH_SERIES_3",
    }
)

#: Whole-name aliases, checked before the token parser.
_NAME_ALIASES: dict[str, str] = {
    "mac": "APP_DESKTOP",
    "macos": "APP_DESKTOP",
    "desktop": "APP_DESKTOP",
    "appletv": "APP_APPLE_TV",
    "tvos": "APP_APPLE_TV",
    "tv": "APP_APPLE_TV",
    "visionpro": "APP_APPLE_VISION_PRO",
    "vision": "APP_APPLE_VISION_PRO",
    "visionos": "APP_APPLE_VISION_PRO",
    "watchultra": "APP_WATCH_ULTRA",
    "ultra": "APP_WATCH_ULTRA",
}

_ENUM_BY_KEY = {re.sub(r"[^a-z0-9]", "", name.lower()): name for name in DISPLAY_TYPES}

_SIZE_RE = re.compile(r"^(\d{1,3})(?:[.,](\d))?$")


def _tokens(name: str) -> list[str]:
    """Split a folder name into lowercase word/number tokens."""
    spaced = re.sub(r"(?<=[a-zA-Z])(?=\d)|(?<=\d)(?=[a-zA-Z])", " ", name)
    return [t for t in re.split(r"[^a-zA-Z0-9.,]+", spaced.lower()) if t]


def _canonical_size(token: str, *, decimal: bool) -> str | None:
    """Turn ``69`` / ``6.9`` / ``129`` into the canonical ``6.9`` / ``12.9`` form."""
    match = _SIZE_RE.match(token)
    if not match:
        return None
    whole, frac = match.groups()
    if frac is not None:
        return f"{int(whole)}.{frac}"
    if not decimal:
        return whole
    if len(whole) >= 2 and whole not in {"11", "13", "10", "12"}:
        # "69" -> 6.9, "129" -> 12.9
        return f"{int(whole[:-1])}.{whole[-1]}"
    return f"{int(whole)}.0"


def resolve_display_type(
    name: str,
    overrides: Mapping[str, str] | None = None,
    *,
    resolution: tuple[int, int] | None = None,
) -> str:
    """Return the ``screenshotDisplayType`` for a device folder name.

    Resolution order: explicit ``overrides``, then a literal enum value, then a
    whole-name alias, then family + size parsed out of the tokens, and finally
    ``resolution`` (the pixel size of a screenshot inside the folder) as a
    fallback for names like ``Set 1``.

    Raises :class:`UnknownDeviceError` when nothing matches.
    """
    key = re.sub(r"[^a-z0-9]", "", name.strip().lower())
    if not key:
        raise UnknownDeviceError(f"Empty device folder name: {name!r}")

    if overrides:
        for raw_key, value in overrides.items():
            if re.sub(r"[^a-z0-9]", "", raw_key.strip().lower()) == key:
                return value

    if key in _ENUM_BY_KEY:
        return _ENUM_BY_KEY[key]
    if key in _NAME_ALIASES:
        return _NAME_ALIASES[key]

    parsed = _parse_family_and_size(name)
    if parsed:
        return parsed

    if resolution and resolution in _RESOLUTIONS:
        return _RESOLUTIONS[resolution]

    raise UnknownDeviceError(
        f"Cannot map device folder {name!r} to a screenshotDisplayType. "
        f"Rename it (e.g. 'iPhone-6.9', 'iPad-13-Landscape') or add an override."
    )


def _parse_family_and_size(name: str) -> str | None:
    tokens = [t for t in _tokens(name) if t not in _NOISE]
    if not tokens:
        return None

    joined = "".join(tokens)
    is_imessage = "imessage" in joined
    family: str | None = None
    if "iphone" in joined:
        family = "iphone"
    elif "ipad" in joined:
        family = "ipad"
    elif "watch" in joined:
        family = "watch"
    elif "mac" in joined or "desktop" in joined:
        return "APP_DESKTOP"
    elif "vision" in joined:
        return "APP_APPLE_VISION_PRO"
    elif "tv" in joined:
        return "APP_APPLE_TV"

    if family is None:
        return None

    if family == "watch":
        if "ultra" in joined:
            return "APP_WATCH_ULTRA"
        for token in tokens:
            if token.startswith("series") or token.isdigit():
                digits = re.sub(r"\D", "", token)
                if digits in {"10", "7", "4", "3"} and "series" in joined:
                    return f"APP_WATCH_SERIES_{digits}"
                if digits in _WATCH_SIZES:
                    return _WATCH_SIZES[digits]
        return None

    sizes = _IPHONE_SIZES if family == "iphone" else _IPAD_SIZES
    for token in tokens:
        size = _canonical_size(token, decimal=True)
        if size and size in sizes:
            display_type = sizes[size]
            return f"IMESSAGE_{display_type}" if is_imessage else display_type
        # "iPad 13" -> "13.0"
        if size and family == "ipad" and f"{size.split('.')[0]}.0" in sizes:
            display_type = sizes[f"{size.split('.')[0]}.0"]
            return f"IMESSAGE_{display_type}" if is_imessage else display_type
    return None


def looks_like_device(name: str, overrides: Mapping[str, str] | None = None) -> bool:
    """True when :func:`resolve_display_type` would succeed from the name alone."""
    try:
        resolve_display_type(name, overrides)
    except UnknownDeviceError:
        return False
    return True


def display_type_from_resolution(resolution: tuple[int, int]) -> str | None:
    """Best-effort display type for a pixel size, or ``None`` if unrecognised."""
    return _RESOLUTIONS.get(resolution)
