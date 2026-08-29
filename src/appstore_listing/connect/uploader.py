"""Push a scanned screenshot tree to an App Store Connect version."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..errors import SnapshotError
from ..models import ProgressEvent, ScreenshotSet, UploadReport
from .client import AppStoreConnectClient

ProgressCallback = Callable[[ProgressEvent], None]


@dataclass(slots=True)
class UploadOptions:
    """Knobs for a run."""

    #: Delete the screenshots already in a set before uploading (the usual choice --
    #: App Store Connect caps a set at 10 images, so appending overflows quickly).
    replace_existing: bool = True
    #: Create ``appStoreVersionLocalization`` records for languages the version lacks.
    create_missing_localizations: bool = True
    #: Plan and report without touching anything.
    dry_run: bool = False
    #: Concurrent image uploads. Order is restored afterwards, so >1 is safe.
    max_workers: int = 4
    #: Keep going after a set fails instead of aborting the whole run.
    continue_on_error: bool = True
    #: App Store Connect rejects sets larger than this.
    max_per_set: int = 10


class SnapshotUploader:
    """Turns :class:`ScreenshotSet` objects into App Store Connect uploads."""

    def __init__(
        self,
        client: AppStoreConnectClient,
        options: UploadOptions | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._client = client
        self._options = options or UploadOptions()
        self._on_progress = on_progress or (lambda event: None)
        self._lock = threading.Lock()

    def _emit(self, event: ProgressEvent) -> None:
        with self._lock:
            self._on_progress(event)

    def upload(self, version_id: str, sets: Sequence[ScreenshotSet]) -> UploadReport:
        """Upload every set to ``version_id`` and return what happened."""
        report = UploadReport()
        options = self._options
        total_files = sum(len(s) for s in sets)
        done_files = 0

        localizations = self._client.list_localizations(version_id)
        self._emit(
            ProgressEvent(
                "info",
                f"Version has {len(localizations)} localization(s): "
                f"{', '.join(sorted(localizations)) or 'none'}",
                total=total_files,
            )
        )

        # Cache set lookups so we hit the API once per localization, not once per set.
        set_cache: dict[str, dict[str, str]] = {}

        for screenshot_set in sets:
            label = f"{screenshot_set.display_type} / {screenshot_set.locale}"
            self._emit(
                ProgressEvent(
                    "set_start",
                    f"{label} — {len(screenshot_set)} screenshot(s)",
                    done=done_files,
                    total=total_files,
                    display_type=screenshot_set.display_type,
                    locale=screenshot_set.locale,
                )
            )

            try:
                if len(screenshot_set) > options.max_per_set:
                    raise SnapshotError(
                        f"{label} has {len(screenshot_set)} screenshots; "
                        f"App Store Connect allows at most {options.max_per_set} per set."
                    )

                localization_id = self._localization_id(
                    version_id, screenshot_set.locale, localizations, report
                )
                set_id = self._screenshot_set_id(
                    localization_id, screenshot_set.display_type, set_cache, report
                )

                if options.replace_existing and set_id:
                    report.deleted += self._clear_set(set_id)

                uploaded_ids = self._upload_files(
                    set_id, screenshot_set, report, done_files, total_files
                )
                if set_id and uploaded_ids and not options.dry_run:
                    self._client.reorder_screenshots(set_id, uploaded_ids)

                report.sets_touched += 1
            except Exception as exc:
                message = f"{label}: {exc}"
                report.errors.append(message)
                self._emit(
                    ProgressEvent(
                        "file_error",
                        message,
                        done=done_files,
                        total=total_files,
                        display_type=screenshot_set.display_type,
                        locale=screenshot_set.locale,
                    )
                )
                if not options.continue_on_error:
                    raise
                report.skipped += len(screenshot_set)

            done_files += len(screenshot_set)
            self._emit(
                ProgressEvent(
                    "set_done",
                    f"{label} done",
                    done=done_files,
                    total=total_files,
                    display_type=screenshot_set.display_type,
                    locale=screenshot_set.locale,
                )
            )

        self._emit(
            ProgressEvent(
                "done",
                f"{report.uploaded} uploaded, {report.deleted} removed, "
                f"{len(report.errors)} error(s)",
                done=total_files,
                total=total_files,
            )
        )
        return report

    # ------------------------------------------------------------------ steps

    def _localization_id(
        self,
        version_id: str,
        locale: str,
        localizations: dict[str, str],
        report: UploadReport,
    ) -> str | None:
        if locale in localizations:
            return localizations[locale]
        if not self._options.create_missing_localizations:
            raise SnapshotError(
                f"The version has no {locale} localization. "
                "Enable 'create missing localizations' or add it in App Store Connect."
            )
        if self._options.dry_run:
            report.localizations_created.append(locale)
            self._emit(ProgressEvent("info", f"[dry run] would create {locale} localization"))
            return None
        localization_id = self._client.create_localization(version_id, locale)
        localizations[locale] = localization_id
        report.localizations_created.append(locale)
        self._emit(ProgressEvent("info", f"Created {locale} localization"))
        return localization_id

    def _screenshot_set_id(
        self,
        localization_id: str | None,
        display_type: str,
        cache: dict[str, dict[str, str]],
        report: UploadReport,
    ) -> str | None:
        if localization_id is None:  # dry run, localization does not exist yet
            return None
        if localization_id not in cache:
            cache[localization_id] = self._client.list_screenshot_sets(localization_id)
        sets = cache[localization_id]
        if display_type in sets:
            return sets[display_type]
        if self._options.dry_run:
            self._emit(ProgressEvent("info", f"[dry run] would create {display_type} set"))
            return None
        set_id = self._client.create_screenshot_set(localization_id, display_type)
        sets[display_type] = set_id
        return set_id

    def _clear_set(self, set_id: str) -> int:
        existing = self._client.list_screenshots(set_id)
        if not existing:
            self._emit(ProgressEvent("info", "nothing to replace — the set was already empty"))
            return 0
        if self._options.dry_run:
            self._emit(
                ProgressEvent(
                    "info", f"[dry run] would delete {len(existing)} existing screenshot(s)"
                )
            )
            return len(existing)
        self._emit(ProgressEvent("info", f"replacing {len(existing)} existing screenshot(s)"))
        for item in existing:
            self._client.delete_screenshot(item["id"])
        return len(existing)

    def _upload_files(
        self,
        set_id: str | None,
        screenshot_set: ScreenshotSet,
        report: UploadReport,
        base_done: int,
        total_files: int,
    ) -> list[str]:
        shots = sorted(screenshot_set.screenshots, key=lambda s: s.order)
        results: list[str | None] = [None] * len(shots)
        progress = {"done": 0}

        def do_one(index: int) -> None:
            shot = shots[index]
            self._emit(
                ProgressEvent(
                    "file_start",
                    f"Uploading {shot.name}",
                    done=base_done + progress["done"],
                    total=total_files,
                    display_type=screenshot_set.display_type,
                    locale=screenshot_set.locale,
                    path=shot.path,
                )
            )
            if self._options.dry_run or set_id is None:
                results[index] = None
            else:
                results[index] = self._client.upload_screenshot(set_id, shot.path)
            with self._lock:
                progress["done"] += 1
                report.uploaded += 1
            self._emit(
                ProgressEvent(
                    "file_done",
                    f"{shot.name} ✓",
                    done=base_done + progress["done"],
                    total=total_files,
                    display_type=screenshot_set.display_type,
                    locale=screenshot_set.locale,
                    path=shot.path,
                )
            )

        if self._options.max_workers > 1 and not self._options.dry_run:
            with ThreadPoolExecutor(max_workers=self._options.max_workers) as pool:
                # list() forces every future to be consumed so exceptions propagate.
                list(pool.map(do_one, range(len(shots))))
        else:
            for index in range(len(shots)):
                do_one(index)

        return [rid for rid in results if rid]
