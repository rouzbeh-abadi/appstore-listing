"""Uploader behaviour, exercised against an in-memory stand-in for the API."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from appstore_listing.connect.uploader import SnapshotUploader, UploadOptions
from appstore_listing.scanning.scanner import scan


class FakeClient:
    """Records every call the uploader makes, and behaves like the real API."""

    def __init__(self, existing_locales: tuple[str, ...] = ("en-US",)) -> None:
        self._ids = itertools.count(1)
        self.localizations = {locale: f"loc-{locale}" for locale in existing_locales}
        self.sets: dict[str, dict[str, str]] = {}
        self.screenshots: dict[str, list[str]] = {}
        self.uploaded: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.reorders: list[tuple[str, list[str]]] = []
        self.fail_on: set[str] = set()

    def list_localizations(self, version_id):
        return dict(self.localizations)

    def create_localization(self, version_id, locale):
        self.localizations[locale] = f"loc-{locale}"
        return self.localizations[locale]

    def list_screenshot_sets(self, localization_id):
        return dict(self.sets.get(localization_id, {}))

    def create_screenshot_set(self, localization_id, display_type):
        set_id = f"set-{next(self._ids)}"
        self.sets.setdefault(localization_id, {})[display_type] = set_id
        self.screenshots[set_id] = []
        return set_id

    def list_screenshots(self, set_id):
        return [{"id": sid} for sid in self.screenshots.get(set_id, [])]

    def delete_screenshot(self, screenshot_id):
        self.deleted.append(screenshot_id)
        for ids in self.screenshots.values():
            if screenshot_id in ids:
                ids.remove(screenshot_id)

    def upload_screenshot(self, set_id, path: Path):
        if path.name in self.fail_on:
            raise RuntimeError(f"boom: {path.name}")
        screenshot_id = f"shot-{next(self._ids)}"
        self.screenshots.setdefault(set_id, []).append(screenshot_id)
        self.uploaded.append((set_id, path.name))
        return screenshot_id

    def reorder_screenshots(self, set_id, ids):
        self.reorders.append((set_id, list(ids)))


@pytest.fixture
def small_tree(tmp_path: Path) -> Path:
    from .conftest import write_png

    for language in ("en-US", "it-IT"):
        for index in (1, 2):
            write_png(tmp_path / "iPhone-6.9" / language / f"{index}.png")
    return tmp_path


def test_uploads_every_set(small_tree: Path):
    client = FakeClient()
    sets = scan(small_tree).sets
    report = SnapshotUploader(client, UploadOptions(max_workers=1)).upload("v1", sets)

    assert report.ok
    assert report.uploaded == 4
    assert report.sets_touched == 2
    assert {name for _, name in client.uploaded} == {"1.png", "2.png"}
    # the Italian localization did not exist and was created
    assert report.localizations_created == ["it"]
    assert "it" in client.localizations


def test_replaces_existing_screenshots(small_tree: Path):
    client = FakeClient(existing_locales=("en-US", "it"))
    client.sets["loc-en-US"] = {"APP_IPHONE_67": "set-old"}
    client.screenshots["set-old"] = ["old-1", "old-2", "old-3"]

    report = SnapshotUploader(client, UploadOptions(max_workers=1)).upload(
        "v1", scan(small_tree).sets
    )

    assert client.deleted == ["old-1", "old-2", "old-3"]
    assert report.deleted == 3


def test_keep_existing_leaves_them_alone(small_tree: Path):
    client = FakeClient(existing_locales=("en-US", "it"))
    client.sets["loc-en-US"] = {"APP_IPHONE_67": "set-old"}
    client.screenshots["set-old"] = ["old-1"]

    SnapshotUploader(client, UploadOptions(replace_existing=False, max_workers=1)).upload(
        "v1", scan(small_tree).sets
    )
    assert client.deleted == []


def test_order_is_restored_after_parallel_upload(small_tree: Path):
    client = FakeClient()
    sets = [s for s in scan(small_tree).sets if s.locale == "en-US"]
    SnapshotUploader(client, UploadOptions(max_workers=4)).upload("v1", sets)

    set_id, ordered_ids = client.reorders[0]
    uploaded_names = [name for sid, name in client.uploaded if sid == set_id]
    assert sorted(uploaded_names) == ["1.png", "2.png"]
    assert len(ordered_ids) == 2


def test_dry_run_changes_nothing(small_tree: Path):
    client = FakeClient()
    report = SnapshotUploader(client, UploadOptions(dry_run=True)).upload(
        "v1", scan(small_tree).sets
    )
    assert report.uploaded == 4  # counted as planned
    assert client.uploaded == []
    assert client.deleted == []
    assert client.reorders == []
    assert "it" not in client.localizations


def test_set_over_ten_screenshots_is_rejected(tmp_path: Path):
    from .conftest import write_png

    for index in range(11):
        write_png(tmp_path / "iPhone-6.9" / "en-US" / f"{index:02d}.png")
    report = SnapshotUploader(FakeClient(), UploadOptions(max_workers=1)).upload(
        "v1", scan(tmp_path).sets
    )
    assert not report.ok
    assert "at most 10" in report.errors[0]


def test_one_bad_set_does_not_stop_the_rest(small_tree: Path):
    client = FakeClient()
    client.fail_on = {"1.png"}
    report = SnapshotUploader(client, UploadOptions(max_workers=1)).upload(
        "v1", scan(small_tree).sets
    )
    assert not report.ok
    assert len(report.errors) == 2  # both locales contain 1.png
    assert report.sets_touched == 0


def test_progress_events_are_emitted(small_tree: Path):
    events = []
    SnapshotUploader(FakeClient(), UploadOptions(max_workers=1), on_progress=events.append).upload(
        "v1", scan(small_tree).sets
    )

    kinds = [e.kind for e in events]
    assert kinds[-1] == "done"
    assert kinds.count("set_start") == 2
    assert kinds.count("file_done") == 4
    assert events[-1].fraction == 1.0


def test_version_ordering_picks_the_newest_editable(monkeypatch):
    """`latest_editable_version` must sort — the API returns versions unordered."""
    from appstore_listing.connect.client import AppStoreConnectClient, AppStoreVersion

    unordered = [
        AppStoreVersion("id-19", "1.9.0", "IOS", "PREPARE_FOR_SUBMISSION"),
        AppStoreVersion("id-2", "2.0.0", "IOS", "READY_FOR_SALE"),
        AppStoreVersion("id-110", "1.10.0", "IOS", "PREPARE_FOR_SUBMISSION"),
    ]
    monkeypatch.setattr(AppStoreConnectClient, "list_versions", lambda self, *a, **k: unordered)
    client = AppStoreConnectClient.__new__(AppStoreConnectClient)

    # 1.10.0 > 1.9.0 numerically, and 2.0.0 is not editable
    assert client.latest_editable_version("app").id == "id-110"


def test_a_draft_beats_a_version_already_in_review(monkeypatch):
    from appstore_listing.connect.client import AppStoreConnectClient, AppStoreVersion

    versions = [
        AppStoreVersion("id-review", "3.0.0", "IOS", "WAITING_FOR_REVIEW"),
        AppStoreVersion("id-draft", "2.0.0", "IOS", "PREPARE_FOR_SUBMISSION"),
    ]
    monkeypatch.setattr(AppStoreConnectClient, "list_versions", lambda self, *a, **k: versions)
    client = AppStoreConnectClient.__new__(AppStoreConnectClient)
    assert client.latest_editable_version("app").id == "id-draft"


def test_replace_reports_what_it_removed(small_tree: Path):
    client = FakeClient(existing_locales=("en-US", "it"))
    client.sets["loc-en-US"] = {"APP_IPHONE_67": "set-old"}
    client.screenshots["set-old"] = ["old-1", "old-2"]

    events = []
    report = SnapshotUploader(
        client, UploadOptions(max_workers=1), on_progress=events.append
    ).upload("v1", scan(small_tree).sets)

    assert report.deleted == 2
    messages = [e.message for e in events]
    assert any("replacing 2 existing" in m for m in messages)
    assert any("already empty" in m for m in messages)  # the Italian set had none


def test_list_versions_sorts_newest_first(monkeypatch):
    """The API response order is arbitrary, so list_versions must sort it."""
    from appstore_listing.connect.client import AppStoreConnectClient

    raw = [
        {"id": "a", "attributes": {"versionString": "1.9.0", "appVersionState": "READY_FOR_SALE"}},
        {"id": "b", "attributes": {"versionString": "1.10.0", "appVersionState": "READY_FOR_SALE"}},
        {"id": "c", "attributes": {"versionString": "2.0", "appVersionState": "READY_FOR_SALE"}},
    ]
    monkeypatch.setattr(AppStoreConnectClient, "_paged", lambda self, *a, **k: iter(raw))
    client = AppStoreConnectClient.__new__(AppStoreConnectClient)

    assert [v.version_string for v in client.list_versions("app")] == ["2.0", "1.10.0", "1.9.0"]
