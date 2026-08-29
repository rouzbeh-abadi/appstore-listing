"""Value objects shared by the scanner, the uploader and the UI."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Screenshot:
    """One image file destined for one screenshot set."""

    path: Path
    order: int
    size_bytes: int
    resolution: tuple[int, int] | None = None

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(slots=True)
class ScreenshotSet:
    """All screenshots for one (display type, locale) pair."""

    display_type: str
    locale: str
    device_folder: str
    #: Name of the language sub-folder, or ``""`` when the screenshots sat
    #: directly in the device folder and took the default locale.
    locale_folder: str
    screenshots: list[Screenshot] = field(default_factory=list)
    #: The folder these screenshots were actually read from.
    source: Path | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.display_type, self.locale)

    @property
    def from_device_folder(self) -> bool:
        """True when the images were loose in the device folder, with no language folder."""
        return not self.locale_folder

    @property
    def locale_label(self) -> str:
        """How to show the language column: the folder name, or why there isn't one."""
        return self.locale_folder or f"(no language folder → {self.locale})"

    def __len__(self) -> int:
        return len(self.screenshots)


@dataclass(slots=True)
class ScanIssue:
    """A folder or file the scanner had to skip, with the reason why."""

    path: Path
    reason: str


@dataclass(slots=True)
class ScanResult:
    """Everything found in the folder(s) that were scanned."""

    #: Common parent of :attr:`sources`, for display.
    root: Path
    #: The device folders (or the single root) that were actually read.
    sources: list[Path] = field(default_factory=list)
    sets: list[ScreenshotSet] = field(default_factory=list)
    issues: list[ScanIssue] = field(default_factory=list)
    layout: str = "device-folder"

    @property
    def total_screenshots(self) -> int:
        return sum(len(s) for s in self.sets)

    @property
    def device_folders(self) -> list[str]:
        return sorted({s.device_folder for s in self.sets})

    @property
    def display_types(self) -> list[str]:
        return sorted({s.display_type for s in self.sets})

    @property
    def locales(self) -> list[str]:
        return sorted({s.locale for s in self.sets})

    def filtered(
        self,
        *,
        display_types: set[str] | None = None,
        locales: set[str] | None = None,
    ) -> list[ScreenshotSet]:
        """Sets narrowed to the given display types / locales (``None`` = all)."""
        return [
            s
            for s in self.sets
            if (display_types is None or s.display_type in display_types)
            and (locales is None or s.locale in locales)
        ]

    def __iter__(self) -> Iterator[ScreenshotSet]:
        return iter(self.sets)


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Emitted while uploading, so a CLI or Streamlit can render progress."""

    kind: str  # set_start | set_done | file_start | file_done | file_error | info | done
    message: str
    done: int = 0
    total: int = 0
    display_type: str | None = None
    locale: str | None = None
    path: Path | None = None

    @property
    def fraction(self) -> float:
        return (self.done / self.total) if self.total else 0.0


@dataclass(slots=True)
class UploadReport:
    """Outcome of an upload run."""

    uploaded: int = 0
    deleted: int = 0
    skipped: int = 0
    sets_touched: int = 0
    localizations_created: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
