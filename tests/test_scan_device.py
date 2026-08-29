"""Scanning a single device folder — the unit the UI hands to the uploader."""

from pathlib import Path

import pytest

from appstore_listing.errors import ScanError
from appstore_listing.scanning.scanner import DEFAULT_LOCALE, scan_device, scan_devices

from .conftest import write_png


def test_loose_images_become_english_us(tmp_path: Path):
    device = tmp_path / "iPad-13-Landscape"
    for index in (1, 2, 3):
        write_png(device / f"{index}.png", (2752, 2064))

    result = scan_device(device)

    assert len(result.sets) == 1
    only = result.sets[0]
    assert only.locale == DEFAULT_LOCALE == "en-US"
    assert only.display_type == "APP_IPAD_PRO_3GEN_129"
    assert only.locale_folder == ""
    assert only.from_device_folder
    assert only.locale_label == "(no language folder → en-US)"
    assert len(only) == 3
    assert not result.issues


def test_language_folders_are_used_when_present(tmp_path: Path):
    device = tmp_path / "iPhone-6.9"
    for language in ("de-DE", "it-IT", "zh-Hans"):
        write_png(device / language / "01.png")

    result = scan_device(device)

    assert {s.locale for s in result.sets} == {"de-DE", "it", "zh-Hans"}
    assert all(s.display_type == "APP_IPHONE_67" for s in result.sets)
    assert all(not s.from_device_folder for s in result.sets)


def test_loose_images_and_language_folders_coexist(tmp_path: Path):
    device = tmp_path / "iPhone-6.9"
    write_png(device / "01.png")  # -> en-US
    write_png(device / "de-DE" / "01.png")

    result = scan_device(device)

    assert {s.locale: s.locale_folder for s in result.sets} == {"en-US": "", "de-DE": "de-DE"}
    assert not result.issues


def test_loose_images_lose_to_an_explicit_default_locale_folder(tmp_path: Path):
    device = tmp_path / "iPhone-6.9"
    write_png(device / "loose.png")
    write_png(device / "en-US" / "01.png")

    result = scan_device(device)

    assert len(result.sets) == 1
    assert result.sets[0].locale_folder == "en-US"
    assert "ignored" in result.issues[0].reason


def test_default_locale_is_configurable(tmp_path: Path):
    device = tmp_path / "iPhone-6.9"
    write_png(device / "01.png")
    assert scan_device(device, default_locale="de-DE").sets[0].locale == "de-DE"


def test_display_type_can_be_pinned_for_an_unguessable_name(tmp_path: Path):
    device = tmp_path / "Marketing Shots"
    write_png(device / "en-US" / "01.png", (999, 1777))  # unknown resolution too

    assert scan_device(device).issues  # cannot tell what device this is
    pinned = scan_device(device, display_type="APP_IPHONE_65")
    assert pinned.sets[0].display_type == "APP_IPHONE_65"
    assert not pinned.issues


def test_unguessable_name_falls_back_to_image_resolution(tmp_path: Path):
    device = tmp_path / "Set 1"
    write_png(device / "de-DE" / "01.png", (1320, 2868))
    assert scan_device(device).sets[0].display_type == "APP_IPHONE_67"


def test_empty_device_folder_is_an_issue_not_a_crash(tmp_path: Path):
    device = tmp_path / "iPhone-6.9"
    device.mkdir()
    result = scan_device(device)
    assert not result.sets
    assert "no screenshots" in result.issues[0].reason


def test_missing_folder_raises(tmp_path: Path):
    with pytest.raises(ScanError):
        scan_device(tmp_path / "nope")


# ------------------------------------------------------- several device folders


def test_scan_devices_combines_folders(tmp_path: Path):
    phone = tmp_path / "iPhone-6.9"
    tablet = tmp_path / "iPad-13-Landscape"
    for language in ("en-US", "de-DE"):
        write_png(phone / language / "01.png")
    write_png(tablet / "01.png", (2752, 2064))
    write_png(tablet / "02.png", (2752, 2064))

    result = scan_devices([phone, tablet])

    assert result.display_types == ["APP_IPAD_PRO_3GEN_129", "APP_IPHONE_67"]
    assert result.total_screenshots == 4
    assert result.root == tmp_path
    assert result.sources == [phone, tablet]
    tablet_set = next(s for s in result.sets if s.display_type == "APP_IPAD_PRO_3GEN_129")
    assert tablet_set.locale == "en-US" and tablet_set.from_device_folder


def test_scan_devices_pins_by_path(tmp_path: Path):
    odd = tmp_path / "Hero"
    write_png(odd / "01.png", (800, 600))
    result = scan_devices([odd], display_types={str(odd): "APP_IPHONE_61"})
    assert result.sets[0].display_type == "APP_IPHONE_61"


def test_two_folders_claiming_the_same_set_are_flagged(tmp_path: Path):
    first = tmp_path / "a" / "iPhone-6.9"
    second = tmp_path / "b" / "iPhone-6.7"
    write_png(first / "01.png")
    write_png(second / "01.png")

    result = scan_devices([first, second])

    assert len(result.sets) == 2  # both kept, so the user can drop one
    assert "already claimed by" in result.issues[0].reason


def test_scan_devices_reports_a_missing_folder(tmp_path: Path):
    good = tmp_path / "iPhone-6.9"
    write_png(good / "01.png")
    result = scan_devices([good, tmp_path / "gone"])
    assert len(result.sets) == 1
    assert result.issues[0].reason == "not a directory"


def test_scan_devices_needs_at_least_one_folder():
    with pytest.raises(ScanError):
        scan_devices([])


def test_listing_json_is_found_and_snapshots_json_still_works(tmp_path):
    """The config file follows the tool's name, without breaking old checkouts.

    The file lives in the user's project, not in this repo, so renaming
    the tool is no reason to make someone rename their file.
    """
    from appstore_listing.scanning.config import DEFAULT_CONFIG_NAMES, SnapshotConfig

    assert DEFAULT_CONFIG_NAMES[0] == "listing.json"
    assert "snapshots.json" in DEFAULT_CONFIG_NAMES

    for name in ("listing.json", "snapshots.json"):
        root = tmp_path / name.replace(".", "_")
        root.mkdir()
        (root / name).write_text('{"languages": {"brazil": "pt-BR"}}', encoding="utf-8")
        config = SnapshotConfig.discover(root)
        assert config.languages["brazil"] == "pt-BR", name
