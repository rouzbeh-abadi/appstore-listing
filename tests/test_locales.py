import pytest

from appstore_listing.errors import UnknownLocaleError
from appstore_listing.naming.locales import looks_like_locale, resolve_locale


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("de-DE", "de-DE"),
        ("en-US", "en-US"),
        ("es-ES", "es-ES"),
        ("es-MX", "es-MX"),
        ("fr-FR", "fr-FR"),
        ("pt-BR", "pt-BR"),
        ("pt-PT", "pt-PT"),
        ("zh-Hans", "zh-Hans"),
        # the interesting one: App Store spells Italian without a region
        ("it-IT", "it"),
        ("it", "it"),
        # separator and case insensitivity
        ("pt_br", "pt-BR"),
        ("ZH-HANS", "zh-Hans"),
        ("de_de", "de-DE"),
        # bare language codes and language names
        ("de", "de-DE"),
        ("ja-JP", "ja"),
        ("zh-CN", "zh-Hans"),
        ("zh-TW", "zh-Hant"),
        ("German", "de-DE"),
        ("BrazilianPortuguese", "pt-BR"),
    ],
)
def test_resolve_locale(folder, expected):
    assert resolve_locale(folder) == expected


def test_overrides_win():
    assert resolve_locale("klingon", {"klingon": "en-US"}) == "en-US"
    assert resolve_locale("de-DE", {"de_de": "de-DE"}) == "de-DE"


def test_unknown_locale_raises():
    with pytest.raises(UnknownLocaleError):
        resolve_locale("not-a-language")
    assert not looks_like_locale("iPhone-6.9")
    assert looks_like_locale("fr-FR")
