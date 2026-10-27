import pytest

from appstore_listing.errors import UnknownDeviceError
from appstore_listing.naming.display_types import (
    display_type_from_resolution,
    looks_like_device,
    resolve_display_type,
)


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        # the two names from the brief
        ("iPad-13-Landscape", "APP_IPAD_PRO_3GEN_129"),
        ("iPhone-6.9", "APP_IPHONE_67"),
        # separator / case / spelling variety
        ("iphone_69", "APP_IPHONE_67"),
        ("iPhone 6.9 inch", "APP_IPHONE_67"),
        ("IPHONE69", "APP_IPHONE_67"),
        ("iPhone-6.5", "APP_IPHONE_65"),
        ("iphone 5.5", "APP_IPHONE_55"),
        ("iPhone-4.7", "APP_IPHONE_47"),
        ("iPad 12.9", "APP_IPAD_PRO_3GEN_129"),
        ("iPad-11", "APP_IPAD_PRO_3GEN_11"),
        ("iPad 9.7 Portrait", "APP_IPAD_97"),
        # literal enum values pass straight through
        ("APP_IPHONE_67", "APP_IPHONE_67"),
        ("app_ipad_pro_3gen_129", "APP_IPAD_PRO_3GEN_129"),
        # non-phone families
        ("Mac", "APP_DESKTOP"),
        ("Apple-TV", "APP_APPLE_TV"),
        ("Vision-Pro", "APP_APPLE_VISION_PRO"),
        ("Apple Watch Ultra", "APP_WATCH_ULTRA"),
        ("Watch Series 7", "APP_WATCH_SERIES_7"),
        # iPhone Duo: both displays share one set
        ("iPhone-Duo-Inner", "APP_IPHONE_DUO"),
        ("iPhone-Duo-Outer", "APP_IPHONE_DUO"),
        ("iPhoneDuo", "APP_IPHONE_DUO"),
        ("Duo", "APP_IPHONE_DUO"),
        ("APP_IPHONE_DUO", "APP_IPHONE_DUO"),
    ],
)
def test_resolve_display_type(folder, expected):
    assert resolve_display_type(folder) == expected


def test_orientation_is_ignored():
    assert resolve_display_type("iPad-13-Landscape") == resolve_display_type("iPad-13-Portrait")


def test_custom_name_via_override():
    overrides = {"Hero Shots Big Phone": "APP_IPHONE_67"}
    assert resolve_display_type("Hero-Shots-Big-Phone", overrides) == "APP_IPHONE_67"
    # an override also beats a name the parser would otherwise resolve
    assert resolve_display_type("iPhone-6.9", {"iPhone 6.9": "APP_IPHONE_65"}) == "APP_IPHONE_65"


def test_resolution_fallback():
    assert resolve_display_type("Set 1", resolution=(1320, 2868)) == "APP_IPHONE_67"
    # landscape images resolve to the same display type
    assert display_type_from_resolution((2752, 2064)) == "APP_IPAD_PRO_3GEN_129"
    # iPhone Duo's outer and inner displays, either way up
    for size in [(1398, 2034), (2034, 1398), (2853, 2007), (2007, 2853)]:
        assert display_type_from_resolution(size) == "APP_IPHONE_DUO"


def test_unknown_device_raises():
    with pytest.raises(UnknownDeviceError):
        resolve_display_type("Set 1")
    assert not looks_like_device("en-US")
