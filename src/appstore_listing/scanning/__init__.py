"""Read screenshot folders into the sets that will be uploaded."""

from .config import DEFAULT_CONFIG_NAMES, SnapshotConfig
from .scanner import (
    DEFAULT_LOCALE,
    IMAGE_SUFFIXES,
    detect_layout,
    device_display_type,
    scan,
    scan_device,
    scan_devices,
    subdirs,
)

__all__ = [
    "DEFAULT_CONFIG_NAMES",
    "DEFAULT_LOCALE",
    "IMAGE_SUFFIXES",
    "SnapshotConfig",
    "detect_layout",
    "device_display_type",
    "scan",
    "scan_device",
    "scan_devices",
    "subdirs",
]
