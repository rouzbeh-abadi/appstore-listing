"""Send the metadata JSON to App Store Connect, one language at a time.

Every field is compared against what is already live and only the differences
are sent. That keeps a re-run cheap, makes ``--dry-run`` genuinely useful — it
prints the same diff it would have written — and avoids touching a field a
teammate changed in the web UI when your file simply repeats the old value.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field

from ..connect.client import AppStoreConnectClient
from ..errors import ApiError
from ..models import ProgressEvent
from .document import LocaleMetadata, MetadataDocument

Progress = Callable[[ProgressEvent], None]


@dataclass(frozen=True, slots=True)
class MetadataOptions:
    dry_run: bool = False
    #: Write the app name and subtitle too. Off by default: they are the app's
    #: identity, they persist across versions, and a stale value in the file
    #: would quietly rename the app.
    include_app_info: bool = False


@dataclass(frozen=True, slots=True)
class FieldChange:
    locale: str
    field: str
    before: str
    after: str

    @property
    def is_new(self) -> bool:
        return not self.before

    def summary(self, width: int = 60) -> str:
        shown = self.after.replace("\n", " ⏎ ")
        if len(shown) > width:
            shown = shown[: width - 1] + "…"
        return f"{self.locale}  {self.field}: {shown}"


@dataclass(slots=True)
class MetadataReport:
    changes: list[FieldChange] = dataclass_field(default_factory=list)
    unchanged: int = 0
    locales_created: list[str] = dataclass_field(default_factory=list)
    errors: list[str] = dataclass_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def written(self) -> int:
        return len(self.changes)

    def locales_touched(self) -> list[str]:
        return sorted({c.locale for c in self.changes})


class MetadataPusher:
    """Applies a :class:`MetadataDocument` to one App Store version."""

    def __init__(
        self,
        client: AppStoreConnectClient,
        options: MetadataOptions | None = None,
        *,
        on_progress: Progress | None = None,
    ) -> None:
        self._client = client
        self._options = options or MetadataOptions()
        self._progress = on_progress or (lambda _event: None)

    def push(
        self,
        version_id: str,
        document: MetadataDocument,
        *,
        app_id: str | None = None,
        locales: set[str] | None = None,
    ) -> MetadataReport:
        report = MetadataReport()
        entries = document.filtered(locales)
        if not entries:
            return report

        existing = self._client.list_localizations(version_id)
        app_info_id = None
        app_info_existing: dict[str, str] = {}
        if self._options.include_app_info and app_id:
            app_info_id = self._client.editable_app_info_id(app_id)
            if app_info_id:
                app_info_existing = self._client.list_app_info_localizations(app_info_id)

        for index, entry in enumerate(entries, start=1):
            self._progress(
                ProgressEvent(
                    kind="set_start",
                    message=f"{entry.locale} ({index}/{len(entries)})",
                    done=index - 1,
                    total=len(entries),
                    locale=entry.locale,
                )
            )
            try:
                self._push_version_fields(version_id, entry, existing, report)
                if self._options.include_app_info:
                    self._push_app_info_fields(app_info_id, entry, app_info_existing, report)
            except ApiError as exc:
                report.errors.append(f"{entry.locale}: {_explain(exc, entry)}")
                self._progress(
                    ProgressEvent(
                        kind="file_error",
                        message=f"{entry.locale}: {exc}",
                        locale=entry.locale,
                    )
                )

        self._progress(
            ProgressEvent(
                kind="done",
                message=(
                    f"{report.written} field(s) written across "
                    f"{len(report.locales_touched())} language(s)"
                ),
                done=len(entries),
                total=len(entries),
            )
        )
        return report

    # ------------------------------------------------------------- internals

    def _push_version_fields(
        self,
        version_id: str,
        entry: LocaleMetadata,
        existing: dict[str, str],
        report: MetadataReport,
    ) -> None:
        wanted = entry.scoped("version")
        if not wanted:
            return

        localization_id = existing.get(entry.locale)
        if localization_id is None:
            if self._options.dry_run:
                report.locales_created.append(entry.locale)
                for key, value in wanted.items():
                    report.changes.append(FieldChange(entry.locale, key, "", value))
                return
            localization_id = self._client.create_localization(version_id, entry.locale)
            existing[entry.locale] = localization_id
            report.locales_created.append(entry.locale)
            current: dict[str, str] = {}
        else:
            current = self._client.get_localization(localization_id)

        changed = _diff(entry.locale, wanted, current, report)
        if changed and not self._options.dry_run:
            self._client.update_localization(localization_id, changed)

    def _push_app_info_fields(
        self,
        app_info_id: str | None,
        entry: LocaleMetadata,
        existing: dict[str, str],
        report: MetadataReport,
    ) -> None:
        wanted = entry.scoped("app-info")
        if not wanted:
            return
        if app_info_id is None:
            report.errors.append(
                f"{entry.locale}: cannot write the app name or subtitle — no editable app "
                "info record was found. Pass --app-id, or drop those fields."
            )
            return

        localization_id = existing.get(entry.locale)
        if localization_id is None:
            if self._options.dry_run:
                for key, value in wanted.items():
                    report.changes.append(FieldChange(entry.locale, key, "", value))
                return
            # A new language needs its name in the creation call itself —
            # Apple 409s an appInfoLocalization POSTed without one. Send
            # every field at once; there is nothing left to PATCH after.
            localization_id = self._client.create_app_info_localization(
                app_info_id, entry.locale, wanted
            )
            existing[entry.locale] = localization_id
            for key, value in wanted.items():
                report.changes.append(FieldChange(entry.locale, key, "", value))
            return

        current = self._client.get_app_info_localization(localization_id)
        changed = _diff(entry.locale, wanted, current, report)
        if changed and not self._options.dry_run:
            self._client.update_app_info_localization(localization_id, changed)


def _diff(
    locale: str,
    wanted: dict[str, str],
    current: dict[str, object],
    report: MetadataReport,
) -> dict[str, str]:
    """Fields whose value differs from what App Store Connect already holds."""
    changed: dict[str, str] = {}
    for key, value in wanted.items():
        before = current.get(key)
        before_text = before if isinstance(before, str) else ""
        if before_text == value:
            report.unchanged += 1
            continue
        changed[key] = value
        report.changes.append(FieldChange(locale, key, before_text, value))
    return changed


def _explain(exc: ApiError, entry: LocaleMetadata) -> str:
    """Turn the two API errors that actually happen into something actionable."""
    text = str(exc)
    if "whatsNew" in text and "whatsNew" in entry.values:
        return (
            f"{text} — What's New cannot be set on an app's first release, only on an "
            "update. Remove whatsNew, or target a version that follows a released one."
        )
    if exc.status == 409:
        return f"{text} — the version may no longer be editable."
    return text
