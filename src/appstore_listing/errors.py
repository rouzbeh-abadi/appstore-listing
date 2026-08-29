"""Exception types raised across the package."""

from __future__ import annotations


class SnapshotError(Exception):
    """Base class for every error this package raises."""


class ScanError(SnapshotError):
    """The screenshot folder tree could not be interpreted."""


class UnknownDeviceError(ScanError):
    """A device folder name could not be mapped to a screenshotDisplayType."""


class UnknownLocaleError(ScanError):
    """A language folder name could not be mapped to an App Store locale."""


class CredentialsError(SnapshotError):
    """The App Store Connect API key material is missing or unusable."""


class ApiError(SnapshotError):
    """App Store Connect returned an error response."""

    def __init__(self, status: int, message: str, payload: object | None = None) -> None:
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.message = message
        self.payload = payload


class UploadError(SnapshotError):
    """A screenshot could not be uploaded or committed."""
