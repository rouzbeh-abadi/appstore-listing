"""Turn folder names into the values App Store Connect expects.

Both tables are irregular in ways worth knowing about: Apple folds 6.9-inch
iPhones into ``APP_IPHONE_67`` and 13-inch iPads into ``APP_IPAD_PRO_3GEN_129``,
and App Store locales spell Italian ``it`` but German ``de-DE``.
"""

from .display_types import (
    DISPLAY_TYPE_LABELS,
    DISPLAY_TYPES,
    display_type_from_resolution,
    looks_like_device,
    resolve_display_type,
)
from .locales import APP_STORE_LOCALES, looks_like_locale, resolve_locale

__all__ = [
    "APP_STORE_LOCALES",
    "DISPLAY_TYPES",
    "DISPLAY_TYPE_LABELS",
    "display_type_from_resolution",
    "looks_like_device",
    "looks_like_locale",
    "resolve_display_type",
    "resolve_locale",
]
