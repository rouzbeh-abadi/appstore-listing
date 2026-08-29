"""Turn screenshot folders into :class:`ScreenshotSet` objects.

The unit of work is a **device folder** -- one folder holding the screenshots for
one device size. Inside it, either arrangement works::

    iPhone-6.9/              iPad-13-Landscape/
      de-DE/                   01.png            <- no language folders, so these
        01_home.png            02.png               are the default locale (en-US)
        02_detail.png
      en-US/
        ...

:func:`scan_device` reads one such folder and :func:`scan_devices` reads several,
which is what the UI hands you when the user picks an iPhone folder and an iPad
folder. :func:`scan` is the convenience wrapper for a parent folder that holds
device folders (and it still recognises the reversed ``<language>/<device>/`` and
flat ``<language>/*.png`` layouts).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..errors import ScanError, UnknownDeviceError, UnknownLocaleError
from ..models import ScanIssue, ScanResult, Screenshot, ScreenshotSet
from ..naming.display_types import (
    display_type_from_resolution,
    looks_like_device,
    resolve_display_type,
)
from ..naming.locales import looks_like_locale, resolve_locale

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

#: Locale used for screenshots that sit directly in a device folder, with no
#: language folder to say otherwise.
DEFAULT_LOCALE = "en-US"

#: ``ScreenshotSet.locale_folder`` marker for those loose screenshots.
NO_LOCALE_FOLDER = ""

#: Files macOS and editors sprinkle around that must never be uploaded.
_IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".gitkeep"}

_LEADING_NUMBER = re.compile(r"^\s*(\d+)")


def _is_image(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in IMAGE_SUFFIXES
        and path.name.lower() not in _IGNORED_NAMES
        and not path.name.startswith("._")
    )


def listdir(path: Path) -> list[Path]:
    """``path.iterdir()`` that yields nothing for folders we may not read.

    macOS guards plenty of directories (``~/Library/Accounts``, ``~/Documents``
    without Full Disk Access); a browsable UI walks into them sooner or later and
    an unreadable folder is a thing to skip, not a crash.
    """
    try:
        return list(path.iterdir())
    except (PermissionError, OSError):
        return []


def subdirs(path: Path) -> list[Path]:
    """Readable, non-hidden sub-directories of ``path``, sorted by name."""
    result = []
    for child in listdir(path):
        if child.name.startswith("."):
            continue
        try:
            if child.is_dir():
                result.append(child)
        except OSError:  # broken symlink, or a mount that went away
            continue
    return sorted(result, key=lambda p: p.name.lower())


def _sort_key(path: Path) -> tuple[int, str]:
    """Order screenshots the way a human numbers them: 1, 2, 10 -- not 1, 10, 2."""
    match = _LEADING_NUMBER.match(path.stem)
    return (int(match.group(1)) if match else 1 << 30, path.name.lower())


def _read_resolution(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image  # imported lazily so the core stays dependency-light
    except ImportError:  # pragma: no cover - Pillow is a declared dependency
        return None
    try:
        with Image.open(path) as img:
            return (img.width, img.height)
    except Exception:
        return None


def _collect_images(folder: Path, *, read_resolution: bool) -> list[Screenshot]:
    files = sorted((p for p in listdir(folder) if _is_image(p)), key=_sort_key)
    shots = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        shots.append(
            Screenshot(
                path=path,
                order=len(shots),
                size_bytes=size,
                resolution=_read_resolution(path) if read_resolution else None,
            )
        )
    return shots


def device_display_type(
    folder: Path,
    device_overrides: Mapping[str, str] | None = None,
    *,
    sample: Screenshot | None = None,
) -> str:
    """Work out which display type a device folder is for.

    Raises :class:`UnknownDeviceError` when neither the folder name nor a sample
    screenshot's pixel size identifies a device.
    """
    return resolve_display_type(
        folder.name,
        device_overrides,
        resolution=sample.resolution if sample else None,
    )


def scan_device(
    folder: str | Path,
    *,
    display_type: str | None = None,
    default_locale: str = DEFAULT_LOCALE,
    device_overrides: Mapping[str, str] | None = None,
    locale_overrides: Mapping[str, str] | None = None,
    read_resolutions: bool = True,
) -> ScanResult:
    """Read one device folder.

    Screenshots sitting directly in ``folder`` become one set in
    ``default_locale``; every language sub-folder becomes a set of its own. A
    folder may contain both, as long as they do not claim the same locale.

    ``display_type`` pins the device explicitly; without it the folder name (and,
    failing that, the first screenshot's pixel size) decides.
    """
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise ScanError(f"Not a directory: {folder}")

    result = ScanResult(root=folder, sources=[folder], layout="device-folder")
    _scan_device_into(
        folder,
        result,
        display_type=display_type,
        default_locale=default_locale,
        device_overrides=device_overrides,
        locale_overrides=locale_overrides,
        read_resolutions=read_resolutions,
    )
    result.sets.sort(key=lambda s: (s.display_type, s.locale))
    return result


def scan_devices(
    folders: Sequence[str | Path],
    *,
    display_types: Mapping[str, str] | None = None,
    default_locale: str = DEFAULT_LOCALE,
    device_overrides: Mapping[str, str] | None = None,
    locale_overrides: Mapping[str, str] | None = None,
    read_resolutions: bool = True,
) -> ScanResult:
    """Read several device folders into one plan.

    ``display_types`` pins individual folders by path (``{str(path): "APP_..."}``)
    for the ones whose names cannot be guessed.
    """
    paths = [Path(f).expanduser() for f in folders]
    if not paths:
        raise ScanError("No device folders given.")

    result = ScanResult(root=_common_parent(paths), sources=paths, layout="device-folder")
    for path in paths:
        if not path.is_dir():
            result.issues.append(ScanIssue(path, "not a directory"))
            continue
        _scan_device_into(
            path,
            result,
            display_type=(display_types or {}).get(str(path)),
            default_locale=default_locale,
            device_overrides=device_overrides,
            locale_overrides=locale_overrides,
            read_resolutions=read_resolutions,
        )

    _flag_duplicate_sets(result)
    result.sets.sort(key=lambda s: (s.display_type, s.locale))
    return result


def _common_parent(paths: Sequence[Path]) -> Path:
    parents = {p.parent for p in paths}
    return parents.pop() if len(parents) == 1 else Path(os.path.commonpath([str(p) for p in paths]))


def _flag_duplicate_sets(result: ScanResult) -> None:
    """Two folders mapped to the same (display type, locale) would overwrite each other."""
    seen: dict[tuple[str, str], ScreenshotSet] = {}
    for screenshot_set in result.sets:
        first = seen.setdefault(screenshot_set.key, screenshot_set)
        if first is not screenshot_set:
            result.issues.append(
                ScanIssue(
                    screenshot_set.source,
                    f"also maps to {screenshot_set.display_type} / {screenshot_set.locale}, "
                    f"already claimed by {first.source}",
                )
            )


def _scan_device_into(
    folder: Path,
    result: ScanResult,
    *,
    display_type: str | None,
    default_locale: str,
    device_overrides: Mapping[str, str] | None,
    locale_overrides: Mapping[str, str] | None,
    read_resolutions: bool,
) -> None:
    loose = _collect_images(folder, read_resolution=read_resolutions)
    language_dirs = subdirs(folder)

    if not loose and not language_dirs:
        result.issues.append(ScanIssue(folder, "no screenshots and no language sub-folders"))
        return

    # Resolve the device once for the whole folder, falling back to any image we
    # can find so that a folder called "Set 1" still works.
    if not display_type:
        sample = loose[0] if loose else _first_image(language_dirs, read_resolutions)
        try:
            display_type = device_display_type(folder, device_overrides, sample=sample)
        except UnknownDeviceError as exc:
            result.issues.append(ScanIssue(folder, str(exc)))
            return

    claimed: dict[str, Path] = {}
    for language_dir in language_dirs:
        screenshots = _collect_images(language_dir, read_resolution=read_resolutions)
        if not screenshots:
            result.issues.append(ScanIssue(language_dir, "no .png/.jpg files"))
            continue
        try:
            locale = resolve_locale(language_dir.name, locale_overrides)
        except UnknownLocaleError as exc:
            result.issues.append(ScanIssue(language_dir, str(exc)))
            continue
        if locale in claimed:
            result.issues.append(
                ScanIssue(language_dir, f"{locale} already taken by {claimed[locale].name}")
            )
            continue
        claimed[locale] = language_dir
        result.sets.append(
            ScreenshotSet(
                display_type=display_type,
                locale=locale,
                device_folder=folder.name,
                locale_folder=language_dir.name,
                screenshots=screenshots,
                source=language_dir,
            )
        )

    if not loose:
        return
    if default_locale in claimed:
        result.issues.append(
            ScanIssue(
                folder,
                f"{len(loose)} screenshot(s) sit directly in this folder, but a "
                f"{default_locale} sub-folder ({claimed[default_locale].name}) already "
                f"covers that locale — the loose files were ignored",
            )
        )
        return
    result.sets.append(
        ScreenshotSet(
            display_type=display_type,
            locale=default_locale,
            device_folder=folder.name,
            locale_folder=NO_LOCALE_FOLDER,
            screenshots=loose,
            source=folder,
        )
    )


def _first_image(folders: Sequence[Path], read_resolution: bool) -> Screenshot | None:
    for folder in folders:
        images = _collect_images(folder, read_resolution=read_resolution)
        if images:
            return images[0]
    return None


def detect_layout(
    root: Path,
    device_overrides: Mapping[str, str] | None = None,
    locale_overrides: Mapping[str, str] | None = None,
) -> str:
    """Return ``"device-first"``, ``"locale-first"`` or ``"flat"`` for ``root``.

    Decided by majority vote on the first level of folder names: whichever of
    "these look like devices" / "these look like languages" wins.
    """
    top = subdirs(root)
    if not top:
        raise ScanError(f"No sub-folders found in {root}")

    devicey = sum(looks_like_device(p.name, device_overrides) for p in top)
    localey = sum(looks_like_locale(p.name, locale_overrides) for p in top)

    if localey > devicey:
        # root/<language>/... -- either <language>/<device>/ or a flat <language>/*.png
        has_nested_dirs = any(subdirs(p) for p in top)
        return "locale-first" if has_nested_dirs else "flat"
    return "device-first"


def scan(
    root: str | Path,
    *,
    device_overrides: Mapping[str, str] | None = None,
    locale_overrides: Mapping[str, str] | None = None,
    layout: str | None = None,
    default_display_type: str | None = None,
    default_locale: str = DEFAULT_LOCALE,
    read_resolutions: bool = True,
) -> ScanResult:
    """Scan a folder that *contains* device folders.

    A convenience wrapper: in the usual layout every sub-folder of ``root`` is a
    device folder and is handed to :func:`scan_device`. The reversed
    ``<language>/<device>/`` layout and a flat ``<language>/*.png`` tree are
    recognised too.

    Folders that cannot be mapped are recorded in :attr:`ScanResult.issues`
    rather than raising, so the UI can show a partial plan plus the problems.
    """
    root = Path(root).expanduser()
    if not root.is_dir():
        raise ScanError(f"Not a directory: {root}")

    resolved_layout = layout or detect_layout(root, device_overrides, locale_overrides)

    if resolved_layout == "device-first":
        result = scan_devices(
            subdirs(root),
            default_locale=default_locale,
            device_overrides=device_overrides,
            locale_overrides=locale_overrides,
            read_resolutions=read_resolutions,
        )
        result.root = root
        result.layout = resolved_layout
        return result

    result = ScanResult(root=root, sources=[root], layout=resolved_layout)
    if resolved_layout == "flat":
        _scan_flat(root, result, locale_overrides, default_display_type, read_resolutions)
    else:
        _scan_locale_first(
            root,
            result,
            device_overrides=device_overrides,
            locale_overrides=locale_overrides,
            read_resolutions=read_resolutions,
        )
    result.sets.sort(key=lambda s: (s.display_type, s.locale))
    return result


def _scan_locale_first(
    root: Path,
    result: ScanResult,
    *,
    device_overrides: Mapping[str, str] | None,
    locale_overrides: Mapping[str, str] | None,
    read_resolutions: bool,
) -> None:
    for locale_dir in subdirs(root):
        device_dirs = subdirs(locale_dir)
        if not device_dirs:
            result.issues.append(ScanIssue(locale_dir, "no device sub-folders"))
            continue

        try:
            locale = resolve_locale(locale_dir.name, locale_overrides)
        except UnknownLocaleError as exc:
            result.issues.append(ScanIssue(locale_dir, str(exc)))
            continue

        for device_dir in device_dirs:
            screenshots = _collect_images(device_dir, read_resolution=read_resolutions)
            if not screenshots:
                result.issues.append(ScanIssue(device_dir, "no .png/.jpg files"))
                continue
            try:
                display_type = device_display_type(
                    device_dir, device_overrides, sample=screenshots[0]
                )
            except UnknownDeviceError as exc:
                result.issues.append(ScanIssue(device_dir, str(exc)))
                continue

            result.sets.append(
                ScreenshotSet(
                    display_type=display_type,
                    locale=locale,
                    device_folder=device_dir.name,
                    locale_folder=locale_dir.name,
                    screenshots=screenshots,
                    source=device_dir,
                )
            )


def _scan_flat(
    root: Path,
    result: ScanResult,
    locale_overrides: Mapping[str, str] | None,
    default_display_type: str | None,
    read_resolutions: bool,
) -> None:
    for locale_dir in subdirs(root):
        screenshots = _collect_images(locale_dir, read_resolution=True)
        if not screenshots:
            result.issues.append(ScanIssue(locale_dir, "no .png/.jpg files"))
            continue
        try:
            locale = resolve_locale(locale_dir.name, locale_overrides)
        except UnknownLocaleError as exc:
            result.issues.append(ScanIssue(locale_dir, str(exc)))
            continue

        # A flat tree has no device folder, so group by the images' own pixel size.
        by_display_type: dict[str, list[Screenshot]] = {}
        for shot in screenshots:
            display_type = (
                display_type_from_resolution(shot.resolution) if shot.resolution else None
            ) or default_display_type
            if not display_type:
                result.issues.append(
                    ScanIssue(shot.path, f"unrecognised resolution {shot.resolution}")
                )
                continue
            by_display_type.setdefault(display_type, []).append(shot)

        for display_type, shots in by_display_type.items():
            result.sets.append(
                ScreenshotSet(
                    display_type=display_type,
                    locale=locale,
                    device_folder="(from resolution)",
                    locale_folder=locale_dir.name,
                    screenshots=[
                        Screenshot(s.path, index, s.size_bytes, s.resolution)
                        for index, s in enumerate(shots)
                    ],
                    source=locale_dir,
                )
            )

    if not read_resolutions:  # pragma: no cover - flat layout always needs resolutions
        result.issues.append(ScanIssue(root, "flat layout requires reading image sizes"))
