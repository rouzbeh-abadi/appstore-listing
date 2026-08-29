"""Optional per-project mapping file for custom folder names.

Drop a ``listing.json`` (or ``.toml``) next to your screenshots root, or point
``--config`` at one, to teach the tool folder names it cannot guess::

    {
      "devices": {
        "iPad-13-Landscape": "APP_IPAD_PRO_3GEN_129",
        "Hero-Shots-Big-Phone": "APP_IPHONE_67"
      },
      "languages": {
        "brazil": "pt-BR",
        "chinese": "zh-Hans"
      }
    }
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import SnapshotError
from ..naming.display_types import DISPLAY_TYPES
from ..naming.locales import APP_STORE_LOCALES

# `listing.*` first, matching the tool's name. The `snapshots.*` names
# are what it was called before and keep working, because the file sits
# in the user's project rather than in this repo and renaming a tool is
# no reason to break someone's checkout.
DEFAULT_CONFIG_NAMES = (
    "listing.json",
    "listing.toml",
    ".listing.json",
    "snapshots.json",
    "snapshots.toml",
    ".snapshots.json",
)


@dataclass(slots=True)
class SnapshotConfig:
    """Folder-name overrides plus optional defaults for a project."""

    devices: dict[str, str] = field(default_factory=dict)
    languages: dict[str, str] = field(default_factory=dict)
    bundle_id: str | None = None
    platform: str = "IOS"
    source: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> SnapshotConfig:
        file = Path(path).expanduser()
        if not file.is_file():
            raise SnapshotError(f"Config file not found: {file}")
        if file.suffix == ".toml":
            data = tomllib.loads(file.read_text())
        else:
            data = json.loads(file.read_text())
        return cls.from_dict(data, source=file).validated()

    @classmethod
    def discover(cls, root: str | Path) -> SnapshotConfig:
        """Load the first known config file in ``root`` or its parent, else empty."""
        root = Path(root).expanduser()
        for folder in (root, root.parent):
            for name in DEFAULT_CONFIG_NAMES:
                candidate = folder / name
                if candidate.is_file():
                    return cls.load(candidate)
        return cls()

    @classmethod
    def from_dict(cls, data: dict, source: Path | None = None) -> SnapshotConfig:
        return cls(
            devices={str(k): str(v) for k, v in (data.get("devices") or {}).items()},
            languages={str(k): str(v) for k, v in (data.get("languages") or {}).items()},
            bundle_id=data.get("bundle_id") or data.get("bundleId"),
            platform=(data.get("platform") or "IOS").upper(),
            source=source,
        )

    def validated(self) -> SnapshotConfig:
        unknown_devices = sorted(set(self.devices.values()) - set(DISPLAY_TYPES))
        if unknown_devices:
            raise SnapshotError(
                f"Unknown screenshotDisplayType(s) in {self.source}: {', '.join(unknown_devices)}"
            )
        unknown_locales = sorted(set(self.languages.values()) - set(APP_STORE_LOCALES))
        if unknown_locales:
            raise SnapshotError(
                f"Unknown App Store locale(s) in {self.source}: {', '.join(unknown_locales)}"
            )
        return self
