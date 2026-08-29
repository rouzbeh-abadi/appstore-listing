"""Localized App Store text — description, what's new, promotional text.

The screenshot half of this tool reads folders; this half reads one JSON file
keyed by language. `fields` says what App Store Connect accepts and where each
field is written, `document` parses and checks the file offline, and `pusher`
sends only what differs from what is already live.
"""

from .document import (
    LocaleMetadata,
    MetadataDocument,
    MetadataError,
    MetadataIssue,
)
from .fields import APP_INFO_FIELDS, FIELDS, VERSION_FIELDS, Field, resolve_field
from .pusher import FieldChange, MetadataOptions, MetadataPusher, MetadataReport

__all__ = [
    "APP_INFO_FIELDS",
    "FIELDS",
    "VERSION_FIELDS",
    "Field",
    "FieldChange",
    "LocaleMetadata",
    "MetadataDocument",
    "MetadataError",
    "MetadataIssue",
    "MetadataOptions",
    "MetadataPusher",
    "MetadataReport",
    "resolve_field",
]
