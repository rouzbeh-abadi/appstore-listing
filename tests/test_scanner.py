from pathlib import Path

import pytest

from appstore_listing.errors import ScanError
from appstore_listing.scanning.scanner import detect_layout, scan

from .conftest import LANGUAGES, write_png


def test_scans_device_first_tree(tree: Path):
    result = scan(tree)

    assert result.layout == "device-first"
    assert len(result.sets) == len(LANGUAGES) + 2
    assert result.display_types == ["APP_IPAD_PRO_3GEN_129", "APP_IPHONE_67"]
    assert "it" in result.locales and "zh-Hans" in result.locales
    assert result.total_screenshots == len(LANGUAGES) * 3 + 2
    assert not result.issues


def test_numeric_prefixes_sort_naturally(tree: Path):
    phone_en = next(
        s for s in scan(tree) if s.display_type == "APP_IPHONE_67" and s.locale == "en-US"
    )
    names = [s.path.name for s in phone_en.screenshots]
    assert names == ["1_home.png", "2_home.png", "10_home.png"]
    assert [s.order for s in phone_en.screenshots] == [0, 1, 2]


def test_ignores_junk_files(tree: Path):
    folder = tree / "iPhone-6.9" / "en-US"
    (folder / ".DS_Store").write_bytes(b"junk")
    (folder / "notes.txt").write_text("hello")
    phone_en = next(
        s for s in scan(tree) if s.display_type == "APP_IPHONE_67" and s.locale == "en-US"
    )
    assert len(phone_en) == 3


def test_unmappable_folders_become_issues(tree: Path):
    write_png(tree / "Mystery-Device" / "en-US" / "01.png", (123, 456))
    write_png(tree / "iPhone-6.9" / "xx-YY" / "01.png")
    result = scan(tree)
    reasons = {issue.path.name for issue in result.issues}
    assert reasons == {"Mystery-Device", "xx-YY"}
    assert result.total_screenshots == len(LANGUAGES) * 3 + 2  # good sets still scanned


def test_overrides_rescue_custom_names(tree: Path):
    write_png(tree / "Big-Phone-Hero" / "brazil" / "01.png")
    result = scan(
        tree,
        device_overrides={"Big-Phone-Hero": "APP_IPHONE_65"},
        locale_overrides={"brazil": "pt-BR"},
    )
    assert not result.issues
    assert ("APP_IPHONE_65", "pt-BR") in {s.key for s in result.sets}


def test_locale_first_layout(tmp_path: Path):
    for language in ("en-US", "de-DE"):
        write_png(tmp_path / language / "iPhone-6.9" / "01.png")
    assert detect_layout(tmp_path) == "locale-first"
    result = scan(tmp_path)
    assert {s.key for s in result.sets} == {
        ("APP_IPHONE_67", "en-US"),
        ("APP_IPHONE_67", "de-DE"),
    }


def test_flat_layout_groups_by_resolution(tmp_path: Path):
    write_png(tmp_path / "en-US" / "01.png", (1320, 2868))
    write_png(tmp_path / "en-US" / "02.png", (2048, 2732))
    assert detect_layout(tmp_path) == "flat"
    result = scan(tmp_path)
    assert {s.display_type for s in result.sets} == {
        "APP_IPHONE_67",
        "APP_IPAD_PRO_3GEN_129",
    }


def test_filtering(tree: Path):
    result = scan(tree)
    only_ipad = result.filtered(display_types={"APP_IPAD_PRO_3GEN_129"})
    assert {s.locale for s in only_ipad} == {"en-US", "de-DE"}
    assert result.filtered(locales={"it"}) and len(result.filtered(locales={"it"})) == 1


def test_missing_root(tmp_path: Path):
    with pytest.raises(ScanError):
        scan(tmp_path / "nope")


def test_unreadable_folders_are_skipped_not_fatal(tmp_path: Path):
    write_png(tmp_path / "iPhone-6.9" / "en-US" / "01.png")
    locked = tmp_path / "iPhone-6.5"
    (locked / "en-US").mkdir(parents=True)
    locked.chmod(0o000)
    try:
        result = scan(tmp_path)
        assert [s.display_type for s in result.sets] == ["APP_IPHONE_67"]
    finally:
        locked.chmod(0o755)


def test_root_scan_picks_up_loose_images_in_a_device_folder(tree: Path):
    """A device folder may hold images directly; they become the default locale."""
    write_png(tree / "iPhone-6.5" / "01.png")
    write_png(tree / "iPhone-6.5" / "de-DE" / "01.png")

    result = scan(tree)
    phone65 = [s for s in result.sets if s.display_type == "APP_IPHONE_65"]
    assert {(s.locale, s.locale_folder) for s in phone65} == {("en-US", ""), ("de-DE", "de-DE")}


def test_root_scan_honours_default_locale(tree: Path):
    write_png(tree / "iPhone-6.5" / "01.png")
    result = scan(tree, default_locale="fr-FR")
    assert any(s.locale == "fr-FR" and s.from_device_folder for s in result.sets)
