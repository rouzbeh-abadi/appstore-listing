"""The 'text for each language' half of the page.

Screenshots come from folders; the words come from one JSON file. The panel
checks the file the moment it is pointed at one — before any credentials are
needed — because almost every problem (a language Apple does not take, a
description over 4000 characters) is visible without the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from appstore_listing.connect import AppStoreConnectClient, Credentials
from appstore_listing.errors import SnapshotError
from appstore_listing.metadata import (
    MetadataDocument,
    MetadataError,
    MetadataOptions,
    MetadataPusher,
)


def metadata_panel(credentials: Credentials | None, bundle_id: str) -> None:
    st.divider()
    st.subheader("Text for each language")
    st.caption(
        "One JSON file, one object per language: description, what's new, "
        "promotional text and keywords."
    )

    document = _load_document()
    if document is None:
        return

    _show_summary(document)

    if not document.ok:
        for issue in document.issues:
            st.error(str(issue), icon="⚠️")
        st.caption("Nothing is sent while any field is invalid.")
        return

    include_app_info = st.checkbox(
        "Also send the app name and subtitle",
        value=False,
        help="Off by default. These carry across versions, so a stale file would "
        "quietly rename the app.",
    )

    preview, send = st.columns(2)
    if preview.button("Preview changes", width="stretch"):
        _run(document, credentials, bundle_id, include_app_info, dry_run=True)
    if send.button("Send text", type="primary", width="stretch"):
        _run(document, credentials, bundle_id, include_app_info, dry_run=False)

    _render_last()


# ------------------------------------------------------------------ the file


def _load_document() -> MetadataDocument | None:
    path_text = st.text_input(
        "Metadata file",
        value=st.session_state.get("metadata_path", ""),
        placeholder="…/metadata.json",
    )
    uploaded = st.file_uploader("or drop it here", type=["json"], label_visibility="collapsed")

    if uploaded is not None:
        try:
            raw = json.loads(uploaded.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            st.error(f"{uploaded.name} is not valid JSON: {exc}", icon="⚠️")
            return None
        try:
            return MetadataDocument.from_mapping(raw, path=Path(uploaded.name))
        except MetadataError as exc:
            st.error(str(exc), icon="⚠️")
            return None

    if not path_text.strip():
        return None

    st.session_state["metadata_path"] = path_text
    try:
        return MetadataDocument.load(Path(path_text).expanduser())
    except MetadataError as exc:
        st.error(str(exc), icon="⚠️")
        return None


def _show_summary(document: MetadataDocument) -> None:
    rows = []
    for entry in document.locales:
        for key, value in sorted(entry.values.items()):
            rows.append({"Language": entry.locale, "Field": key, "Characters": len(value)})
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(f"{len(document.locales)} language(s), {document.total_fields} field(s)")


# ------------------------------------------------------------------ the push


def _run(
    document: MetadataDocument,
    credentials: Credentials | None,
    bundle_id: str,
    include_app_info: bool,
    *,
    dry_run: bool,
) -> None:
    if credentials is None:
        st.error("Fill in the App Store Connect key above first.", icon="⚠️")
        return
    if not bundle_id.strip():
        st.error("Enter the bundle ID above first.", icon="⚠️")
        return

    try:
        outcome = _push(document, credentials, bundle_id, include_app_info, dry_run)
    except Exception as exc:  # report anything rather than leaving the page stuck
        outcome = {"error": str(exc)}
    st.session_state["metadata_last_run"] = outcome
    st.rerun()


def _push(
    document: MetadataDocument,
    credentials: Credentials,
    bundle_id: str,
    include_app_info: bool,
    dry_run: bool,
) -> dict:
    client = AppStoreConnectClient(credentials)

    app = client.find_app(bundle_id.strip())
    if app is None:
        raise SnapshotError(f"No app with bundle id {bundle_id.strip()!r} is visible to this key.")

    version = client.latest_editable_version(app.id)
    if version is None:
        raise SnapshotError(
            "No editable App Store version found. Create the next version in "
            "App Store Connect first."
        )

    pusher = MetadataPusher(
        client, MetadataOptions(dry_run=dry_run, include_app_info=include_app_info)
    )
    report = pusher.push(version.id, document, app_id=app.id)

    verb = "would change" if dry_run else "written"
    return {
        "version": f"{app.name} — version {version.version_string} ({version.state})",
        "rows": [
            {
                "Language": change.locale,
                "Field": change.field,
                "New value": change.summary(width=70).split(": ", 1)[-1],
                "Was": "empty" if change.is_new else f"{len(change.before)} chars",
            }
            for change in report.changes
        ],
        "summary": (
            f"{report.written} field(s) {verb}, {report.unchanged} already up to date"
            + (
                f", {len(report.locales_created)} language(s) added"
                if report.locales_created
                else ""
            )
        ),
        "dry_run": dry_run,
        "errors": report.errors,
    }


def _render_last() -> None:
    outcome = st.session_state.get("metadata_last_run")
    if not outcome:
        return

    if outcome.get("error"):
        st.error(outcome["error"])
        return
    if outcome.get("version"):
        st.info(outcome["version"], icon="🏷️")
    if outcome.get("rows"):
        st.dataframe(outcome["rows"], width="stretch", hide_index=True)
    elif not outcome.get("errors"):
        st.success("Everything already matches what is in App Store Connect.")
    if outcome.get("summary"):
        (st.info if outcome.get("dry_run") else st.success)(outcome["summary"])
    for message in outcome.get("errors", []):
        st.error(message)
