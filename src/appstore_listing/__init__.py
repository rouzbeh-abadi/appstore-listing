"""Upload App Store screenshots laid out as ``<device>/<language>/*.png``.

The package is split by role:

* :mod:`~appstore_listing.naming` — folder names to App Store Connect values
* :mod:`~appstore_listing.scanning` — folders to :class:`ScreenshotSet` objects
* :mod:`~appstore_listing.connect` — credentials, the REST client, uploading
* :mod:`~appstore_listing.ui` — the Streamlit page

:mod:`~appstore_listing.errors` and :mod:`~appstore_listing.models` stay at the
top because every one of those imports them.
"""

from __future__ import annotations

from . import connect, naming, scanning
from .connect import (
    App,
    AppStoreConnectClient,
    AppStoreVersion,
    Credentials,
    SnapshotUploader,
    TokenProvider,
    UploadOptions,
    env,
)
from .errors import (
    ApiError,
    CredentialsError,
    ScanError,
    SnapshotError,
    UnknownDeviceError,
    UnknownLocaleError,
    UploadError,
)
from .models import ProgressEvent, ScanResult, Screenshot, ScreenshotSet, UploadReport
from .naming import (
    APP_STORE_LOCALES,
    DISPLAY_TYPE_LABELS,
    DISPLAY_TYPES,
    resolve_display_type,
    resolve_locale,
)
from .scanning import (
    DEFAULT_LOCALE,
    SnapshotConfig,
    device_display_type,
    scan,
    scan_device,
    scan_devices,
)

__version__ = "0.1.0"

__all__ = [
    "APP_STORE_LOCALES",
    "DEFAULT_LOCALE",
    "DISPLAY_TYPES",
    "DISPLAY_TYPE_LABELS",
    "ApiError",
    "App",
    "AppStoreConnectClient",
    "AppStoreVersion",
    "Credentials",
    "CredentialsError",
    "ProgressEvent",
    "ScanError",
    "ScanResult",
    "Screenshot",
    "ScreenshotSet",
    "SnapshotConfig",
    "SnapshotError",
    "SnapshotUploader",
    "TokenProvider",
    "UnknownDeviceError",
    "UnknownLocaleError",
    "UploadError",
    "UploadOptions",
    "UploadReport",
    "__version__",
    "connect",
    "device_display_type",
    "env",
    "naming",
    "resolve_display_type",
    "resolve_locale",
    "scan",
    "scan_device",
    "scan_devices",
    "scanning",
]
