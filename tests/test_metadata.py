"""Reading the metadata file, and pushing it against an in-memory API."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from appstore_snapshots.errors import ApiError
from appstore_snapshots.metadata import (
    MetadataDocument,
    MetadataError,
    MetadataOptions,
    MetadataPusher,
    resolve_field,
)

# --------------------------------------------------------------------- file


def test_languages_are_normalised_to_app_store_spelling():
    doc = MetadataDocument.from_mapping(
        {"de": {"description": "hallo"}, "German": {"whatsNew": "neu"}}
    )
    # Both spellings are the same App Store locale, so both land on de-DE.
    assert [entry.locale for entry in doc.locales] == ["de-DE", "de-DE"]


def test_field_names_are_forgiving_but_typos_are_not():
    assert resolve_field("What's New").key == "whatsNew"
    assert resolve_field("release_notes").key == "whatsNew"
    assert resolve_field("promo").key == "promotionalText"

    doc = MetadataDocument.from_mapping({"en-US": {"descrption": "x", "description": "y"}})
    assert not doc.ok
    # The suggestion is what makes the error worth reading.
    assert "Did you mean description?" in str(doc.issues[0])


def test_over_long_text_is_reported_with_the_overshoot():
    doc = MetadataDocument.from_mapping({"en-US": {"promotionalText": "x" * 200}})
    assert not doc.ok
    reason = doc.issues[0].reason
    assert "170 is the maximum" in reason
    assert "30 too many" in reason


def test_empty_and_null_values_mean_leave_it_alone():
    doc = MetadataDocument.from_mapping(
        {"en-US": {"description": "keep", "whatsNew": "", "promotionalText": None}}
    )
    assert doc.ok
    assert doc.by_locale()["en-US"].values == {"description": "keep"}


def test_underscore_keys_are_notes_not_data():
    doc = MetadataDocument.from_mapping(
        {"_note": ["a comment"], "en-US": {"_why": "x", "description": "d"}}
    )
    assert doc.ok
    assert [entry.locale for entry in doc.locales] == ["en-US"]
    assert doc.total_fields == 1


def test_unknown_language_is_an_issue_not_a_crash():
    doc = MetadataDocument.from_mapping({"klingon": {"description": "Qapla'"}})
    assert not doc.ok
    assert "not a language" in doc.issues[0].reason


def test_a_file_that_is_not_an_object_is_rejected():
    with pytest.raises(MetadataError):
        MetadataDocument.from_mapping(["en-US"])


def test_load_reports_bad_json_with_the_path(tmp_path: Path):
    bad = tmp_path / "metadata.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(MetadataError, match="not valid JSON"):
        MetadataDocument.load(bad)


def test_fields_are_split_by_the_record_they_are_written_to():
    doc = MetadataDocument.from_mapping(
        {"en-US": {"name": "App", "subtitle": "Sub", "description": "D", "whatsNew": "W"}}
    )
    entry = doc.by_locale()["en-US"]
    assert set(entry.scoped("app-info")) == {"name", "subtitle"}
    assert set(entry.scoped("version")) == {"description", "whatsNew"}


def test_the_shipped_example_file_is_valid():
    """The example is what people copy, so a broken one is a broken tool."""
    example = Path(__file__).resolve().parents[1] / "metadata.example.json"
    doc = MetadataDocument.load(example)
    assert doc.ok, [str(issue) for issue in doc.issues]


# --------------------------------------------------------------------- push


class FakeClient:
    """Stands in for App Store Connect, recording every write."""

    def __init__(self, existing: dict[str, dict[str, str]] | None = None) -> None:
        self._ids = itertools.count(1)
        self.localizations = {locale: f"loc-{locale}" for locale in (existing or {})}
        self.attributes = {f"loc-{k}": dict(v) for k, v in (existing or {}).items()}
        self.patches: list[tuple[str, dict[str, str]]] = []
        self.app_info_localizations: dict[str, str] = {}
        self.app_info_attributes: dict[str, dict[str, str]] = {}
        self.app_info_patches: list[tuple[str, dict[str, str]]] = []
        self.fail_on_locale: set[str] = set()

    def list_localizations(self, version_id):
        return dict(self.localizations)

    def create_localization(self, version_id, locale):
        loc_id = f"loc-{locale}"
        self.localizations[locale] = loc_id
        self.attributes[loc_id] = {}
        return loc_id

    def get_localization(self, localization_id):
        return dict(self.attributes.get(localization_id, {}))

    def update_localization(self, localization_id, attributes):
        if any(localization_id.endswith(loc) for loc in self.fail_on_locale):
            raise ApiError(409, "whatsNew is not allowed for a first version")
        self.patches.append((localization_id, dict(attributes)))
        self.attributes.setdefault(localization_id, {}).update(attributes)

    def editable_app_info_id(self, app_id):
        return "info-1"

    def list_app_info_localizations(self, app_info_id):
        return dict(self.app_info_localizations)

    def create_app_info_localization(self, app_info_id, locale):
        loc_id = f"info-{locale}"
        self.app_info_localizations[locale] = loc_id
        self.app_info_attributes[loc_id] = {}
        return loc_id

    def get_app_info_localization(self, localization_id):
        return dict(self.app_info_attributes.get(localization_id, {}))

    def update_app_info_localization(self, localization_id, attributes):
        self.app_info_patches.append((localization_id, dict(attributes)))
        self.app_info_attributes.setdefault(localization_id, {}).update(attributes)


def make_doc(mapping):
    doc = MetadataDocument.from_mapping(mapping)
    assert doc.ok, [str(i) for i in doc.issues]
    return doc


def test_only_changed_fields_are_sent():
    client = FakeClient({"en-US": {"description": "same", "whatsNew": "old"}})
    doc = make_doc({"en-US": {"description": "same", "whatsNew": "new"}})

    report = MetadataPusher(client).push("v1", doc)

    assert report.unchanged == 1
    assert [c.field for c in report.changes] == ["whatsNew"]
    # "description" is untouched, so a teammate's edit to it survives.
    assert client.patches == [("loc-en-US", {"whatsNew": "new"})]


def test_a_missing_language_is_created_then_written():
    client = FakeClient({"en-US": {}})
    doc = make_doc({"de-DE": {"description": "hallo"}})

    report = MetadataPusher(client).push("v1", doc)

    assert report.locales_created == ["de-DE"]
    assert client.patches == [("loc-de-DE", {"description": "hallo"})]


def test_dry_run_reports_the_same_changes_but_writes_nothing():
    client = FakeClient({"en-US": {"description": "old"}})
    doc = make_doc({"en-US": {"description": "new"}, "fr-FR": {"description": "nouveau"}})

    report = MetadataPusher(client, MetadataOptions(dry_run=True)).push("v1", doc)

    assert {c.field for c in report.changes} == {"description"}
    assert len(report.changes) == 2
    assert client.patches == []
    assert client.localizations.keys() == {"en-US"}


def test_the_app_name_is_held_back_unless_asked_for():
    client = FakeClient({"en-US": {}})
    doc = make_doc({"en-US": {"name": "Renamed", "description": "d"}})

    MetadataPusher(client).push("v1", doc, app_id="app-1")
    assert client.app_info_patches == []
    assert client.patches == [("loc-en-US", {"description": "d"})]

    client2 = FakeClient({"en-US": {}})
    MetadataPusher(client2, MetadataOptions(include_app_info=True)).push("v1", doc, app_id="app-1")
    assert client2.app_info_patches == [("info-en-US", {"name": "Renamed"})]


def test_only_languages_narrows_the_push():
    client = FakeClient({"en-US": {}, "de-DE": {}})
    doc = make_doc({"en-US": {"description": "a"}, "de-DE": {"description": "b"}})

    MetadataPusher(client).push("v1", doc, locales={"de-DE"})

    assert client.patches == [("loc-de-DE", {"description": "b"})]


def test_one_language_failing_does_not_stop_the_others():
    client = FakeClient({"en-US": {}, "de-DE": {}})
    client.fail_on_locale = {"en-US"}
    doc = make_doc({"en-US": {"whatsNew": "x"}, "de-DE": {"whatsNew": "y"}})

    report = MetadataPusher(client).push("v1", doc)

    assert not report.ok
    assert client.patches == [("loc-de-DE", {"whatsNew": "y"})]
    # The first-release case is the one people actually hit; say so plainly.
    assert "first release" in report.errors[0]


def test_rerunning_an_applied_push_writes_nothing():
    client = FakeClient({"en-US": {}})
    doc = make_doc({"en-US": {"description": "d", "whatsNew": "w"}})

    MetadataPusher(client).push("v1", doc)
    client.patches.clear()
    second = MetadataPusher(client).push("v1", doc)

    assert second.written == 0
    assert second.unchanged == 2
    assert client.patches == []


def test_round_trip_through_a_real_file(tmp_path: Path):
    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps({"en-US": {"description": "d"}, "zh-Hans": {"whatsNew": "新"}}),
        encoding="utf-8",
    )
    doc = MetadataDocument.load(path)
    assert doc.ok
    client = FakeClient()
    report = MetadataPusher(client).push("v1", doc)
    assert report.written == 2
    assert sorted(report.locales_created) == ["en-US", "zh-Hans"]


# ---------------------------------------------------------------------- cli


def test_cli_dry_run_reports_without_writing(tmp_path: Path, monkeypatch):
    """Covers the wiring the pusher tests do not: file, app, version, table."""
    from typer.testing import CliRunner

    from appstore_snapshots import cli

    fake = FakeClient({"en-US": {"description": "old"}})

    class Stub(FakeClient):
        def __init__(self, *_args, **_kwargs):
            self.__dict__ = fake.__dict__

        def find_app(self, bundle_id):
            from appstore_snapshots.connect.client import App

            return App(id="app-1", name="Demo", bundle_id=bundle_id)

        def latest_editable_version(self, app_id, platform="IOS"):
            from appstore_snapshots.connect.client import AppStoreVersion

            return AppStoreVersion(
                id="v1", version_string="2.0", platform="IOS", state="PREPARE_FOR_SUBMISSION"
            )

    monkeypatch.setattr(cli, "AppStoreConnectClient", Stub)
    monkeypatch.setattr(cli, "_credentials", lambda *a, **k: object())

    path = tmp_path / "metadata.json"
    path.write_text(
        json.dumps({"en-US": {"description": "new"}, "de-DE": {"whatsNew": "neu"}}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli.app, ["metadata", str(path), "--bundle-id", "com.example.demo", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "2 field(s) would be written" in result.output
    assert fake.patches == []


def test_cli_refuses_an_invalid_file_before_touching_the_network(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from appstore_snapshots import cli

    def explode(*_args, **_kwargs):
        raise AssertionError("the network must not be touched for an invalid file")

    monkeypatch.setattr(cli, "AppStoreConnectClient", explode)

    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"en-US": {"keywords": "k" * 200}}), encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["metadata", str(path), "--bundle-id", "com.example.demo"])

    assert result.exit_code == 1
    assert "100 is the maximum" in result.output
