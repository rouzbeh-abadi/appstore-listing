"""A thin App Store Connect API client covering apps, versions and screenshots."""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..errors import ApiError, UploadError
from .auth import Credentials, TokenProvider

BASE_URL = "https://api.appstoreconnect.apple.com"

#: App Store version states whose metadata (and therefore screenshots) can be edited.
EDITABLE_VERSION_STATES = frozenset(
    {
        "PREPARE_FOR_SUBMISSION",
        "DEVELOPER_REJECTED",
        "REJECTED",
        "METADATA_REJECTED",
        "INVALID_BINARY",
        "WAITING_FOR_REVIEW",
        "WAITING_FOR_EXPORT_COMPLIANCE",
        "READY_FOR_REVIEW",
    }
)

#: Of the editable states, the ones a version you are still preparing is in.
PREFERRED_VERSION_STATES = frozenset({"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED"})

_RETRY_STATUSES = {429, 500, 502, 503, 504}

_VERSION_PART = re.compile(r"\d+")


def version_sort_key(version_string: str) -> tuple[int, ...]:
    """Order ``1.10.0`` after ``1.9.0`` — string order would get that backwards."""
    return tuple(int(part) for part in _VERSION_PART.findall(version_string)) or (0,)


@dataclass(frozen=True, slots=True)
class App:
    id: str
    name: str
    bundle_id: str
    sku: str | None = None

    def __str__(self) -> str:
        return f"{self.name} ({self.bundle_id})"


@dataclass(frozen=True, slots=True)
class AppStoreVersion:
    id: str
    version_string: str
    platform: str
    state: str

    @property
    def editable(self) -> bool:
        return self.state in EDITABLE_VERSION_STATES

    def __str__(self) -> str:
        return f"{self.version_string} — {self.platform} — {self.state}"


def md5_of(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AppStoreConnectClient:
    """Authenticated wrapper over the parts of the API this tool needs."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout: float = 60.0,
        max_retries: int = 4,
        session: requests.Session | None = None,
    ) -> None:
        self._tokens = TokenProvider(credentials)
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = session or requests.Session()
        # Upload URLs are pre-signed for Apple's blob store and must not carry our JWT.
        self._upload_session = requests.Session()

    # ---------------------------------------------------------------- transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        headers = {**self._tokens.authorization_header(), "Content-Type": "application/json"}

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise ApiError(0, f"Network error talking to App Store Connect: {exc}") from exc
                time.sleep(self._backoff(attempt))
                continue

            if response.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                time.sleep(self._retry_after(response, attempt))
                continue

            if response.status_code == 204 or not response.content:
                if response.ok:
                    return None
                raise ApiError(response.status_code, response.reason or "request failed")

            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text}

            if not response.ok:
                raise ApiError(response.status_code, _describe_errors(payload), payload)
            return payload

        raise ApiError(0, f"Request failed after retries: {last_error}")  # pragma: no cover

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2.0**attempt, 16.0)

    def _retry_after(self, response: requests.Response, attempt: int) -> float:
        header = response.headers.get("Retry-After")
        if header:
            try:
                return min(float(header), 60.0)
            except ValueError:
                pass
        return self._backoff(attempt)

    def _paged(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        page_params = {"limit": 200, **(params or {})}
        next_url: str | None = path
        while next_url:
            payload = self._request("GET", next_url, params=page_params) or {}
            yield from payload.get("data", [])
            next_url = (payload.get("links") or {}).get("next")
            page_params = None  # the `next` link already carries the query string

    # -------------------------------------------------------------------- apps

    def list_apps(self) -> list[App]:
        return [
            App(
                id=item["id"],
                name=item["attributes"].get("name", "(unnamed)"),
                bundle_id=item["attributes"].get("bundleId", ""),
                sku=item["attributes"].get("sku"),
            )
            for item in self._paged("/v1/apps", {"sort": "name"})
        ]

    def find_app(self, bundle_id: str) -> App | None:
        for item in self._paged("/v1/apps", {"filter[bundleId]": bundle_id}):
            if item["attributes"].get("bundleId") == bundle_id:
                return App(
                    id=item["id"],
                    name=item["attributes"].get("name", "(unnamed)"),
                    bundle_id=bundle_id,
                    sku=item["attributes"].get("sku"),
                )
        return None

    def list_versions(self, app_id: str, platform: str = "IOS") -> list[AppStoreVersion]:
        """Every version for the platform, newest version string first.

        The API gives no ordering guarantee, so sort here rather than trusting
        the order the response happened to arrive in.
        """
        params = {"filter[platform]": platform} if platform else None
        versions = []
        for item in self._paged(f"/v1/apps/{app_id}/appStoreVersions", params):
            attrs = item["attributes"]
            versions.append(
                AppStoreVersion(
                    id=item["id"],
                    version_string=attrs.get("versionString", "?"),
                    platform=attrs.get("platform", platform),
                    # appStoreState is deprecated in favour of appVersionState.
                    state=attrs.get("appVersionState") or attrs.get("appStoreState") or "UNKNOWN",
                )
            )
        versions.sort(key=lambda v: version_sort_key(v.version_string), reverse=True)
        return versions

    def latest_editable_version(self, app_id: str, platform: str = "IOS") -> AppStoreVersion | None:
        """The newest version whose screenshots can be changed.

        Prefers ``PREPARE_FOR_SUBMISSION`` — the state a version you are still
        working on is in — over the other editable states, so a version already
        sitting in review is never picked while a draft exists.
        """
        editable = [v for v in self.list_versions(app_id, platform) if v.editable]
        if not editable:
            return None
        drafts = [v for v in editable if v.state in PREFERRED_VERSION_STATES]
        # max() rather than [0], so this is right whatever order it was handed.
        return max(drafts or editable, key=lambda v: version_sort_key(v.version_string))

    # ----------------------------------------------------------- localizations

    def list_localizations(self, version_id: str) -> dict[str, str]:
        """``{locale: localizationId}`` for an App Store version."""
        return {
            item["attributes"]["locale"]: item["id"]
            for item in self._paged(
                f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations"
            )
        }

    def create_localization(self, version_id: str, locale: str) -> str:
        payload = {
            "data": {
                "type": "appStoreVersionLocalizations",
                "attributes": {"locale": locale},
                "relationships": {
                    "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version_id}}
                },
            }
        }
        response = self._request("POST", "/v1/appStoreVersionLocalizations", json=payload)
        return response["data"]["id"]  # type: ignore[index]

    def get_localization(self, localization_id: str) -> dict[str, Any]:
        """Current attribute values for one App Store version localization."""
        payload = self._request("GET", f"/v1/appStoreVersionLocalizations/{localization_id}") or {}
        return (payload.get("data") or {}).get("attributes") or {}

    def update_localization(self, localization_id: str, attributes: dict[str, Any]) -> None:
        """PATCH description, keywords, promotional text, what's new and the URLs."""
        if not attributes:
            return
        self._request(
            "PATCH",
            f"/v1/appStoreVersionLocalizations/{localization_id}",
            json={
                "data": {
                    "type": "appStoreVersionLocalizations",
                    "id": localization_id,
                    "attributes": attributes,
                }
            },
        )

    # -------------------------------------------------------------- app info

    def editable_app_info_id(self, app_id: str) -> str | None:
        """The ``appInfo`` whose name and subtitle can still be changed.

        An app has several: one per review state. Only the one that is not yet
        approved accepts edits, so picking the first would usually write to a
        frozen record and fail.
        """
        infos = list(self._paged(f"/v1/apps/{app_id}/appInfos"))
        for item in infos:
            state = (item.get("attributes") or {}).get("appStoreState") or (
                item.get("attributes") or {}
            ).get("state")
            if state in EDITABLE_VERSION_STATES:
                return item["id"]
        return infos[0]["id"] if infos else None

    def list_app_info_localizations(self, app_info_id: str) -> dict[str, str]:
        """``{locale: appInfoLocalizationId}``."""
        return {
            item["attributes"]["locale"]: item["id"]
            for item in self._paged(f"/v1/appInfos/{app_info_id}/appInfoLocalizations")
        }

    def create_app_info_localization(self, app_info_id: str, locale: str) -> str:
        payload = {
            "data": {
                "type": "appInfoLocalizations",
                "attributes": {"locale": locale},
                "relationships": {"appInfo": {"data": {"type": "appInfos", "id": app_info_id}}},
            }
        }
        response = self._request("POST", "/v1/appInfoLocalizations", json=payload)
        return response["data"]["id"]  # type: ignore[index]

    def get_app_info_localization(self, localization_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/v1/appInfoLocalizations/{localization_id}") or {}
        return (payload.get("data") or {}).get("attributes") or {}

    def update_app_info_localization(
        self, localization_id: str, attributes: dict[str, Any]
    ) -> None:
        """PATCH the app name, subtitle and privacy links."""
        if not attributes:
            return
        self._request(
            "PATCH",
            f"/v1/appInfoLocalizations/{localization_id}",
            json={
                "data": {
                    "type": "appInfoLocalizations",
                    "id": localization_id,
                    "attributes": attributes,
                }
            },
        )

    # ------------------------------------------------------------ screenshots

    def list_screenshot_sets(self, localization_id: str) -> dict[str, str]:
        """``{screenshotDisplayType: setId}`` for a localization."""
        return {
            item["attributes"]["screenshotDisplayType"]: item["id"]
            for item in self._paged(
                f"/v1/appStoreVersionLocalizations/{localization_id}/appScreenshotSets"
            )
        }

    def create_screenshot_set(self, localization_id: str, display_type: str) -> str:
        payload = {
            "data": {
                "type": "appScreenshotSets",
                "attributes": {"screenshotDisplayType": display_type},
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {
                            "type": "appStoreVersionLocalizations",
                            "id": localization_id,
                        }
                    }
                },
            }
        }
        response = self._request("POST", "/v1/appScreenshotSets", json=payload)
        return response["data"]["id"]  # type: ignore[index]

    def list_screenshots(self, set_id: str) -> list[dict[str, Any]]:
        return list(self._paged(f"/v1/appScreenshotSets/{set_id}/appScreenshots"))

    def delete_screenshot(self, screenshot_id: str) -> None:
        self._request("DELETE", f"/v1/appScreenshots/{screenshot_id}")

    def reorder_screenshots(self, set_id: str, screenshot_ids: Sequence[str]) -> None:
        payload = {"data": [{"type": "appScreenshots", "id": sid} for sid in screenshot_ids]}
        self._request(
            "PATCH", f"/v1/appScreenshotSets/{set_id}/relationships/appScreenshots", json=payload
        )

    # ------------------------------------------------------------ file upload

    def upload_screenshot(self, set_id: str, path: Path) -> str:
        """Reserve, upload and commit one image. Returns the appScreenshot id."""
        size = path.stat().st_size
        if size == 0:
            raise UploadError(f"{path} is empty")

        reservation = self._request(
            "POST",
            "/v1/appScreenshots",
            json={
                "data": {
                    "type": "appScreenshots",
                    "attributes": {"fileSize": size, "fileName": path.name},
                    "relationships": {
                        "appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": set_id}}
                    },
                }
            },
        )
        assert reservation is not None
        screenshot_id = reservation["data"]["id"]
        operations = reservation["data"]["attributes"].get("uploadOperations") or []
        if not operations:
            raise UploadError(f"App Store Connect returned no upload operations for {path.name}")

        try:
            data = path.read_bytes()
            for operation in operations:
                self._run_upload_operation(operation, data, path)
            self._commit_screenshot(screenshot_id, md5_of(path))
        except Exception:
            # A reserved-but-unfinished screenshot lingers in the set; drop it.
            with contextlib.suppress(Exception):  # best-effort cleanup
                self.delete_screenshot(screenshot_id)
            raise
        return screenshot_id

    def _run_upload_operation(self, operation: dict[str, Any], data: bytes, path: Path) -> None:
        offset = operation.get("offset", 0)
        length = operation.get("length", len(data))
        headers = {h["name"]: h["value"] for h in operation.get("requestHeaders") or []}
        chunk = data[offset : offset + length]

        for attempt in range(self._max_retries + 1):
            try:
                response = self._upload_session.request(
                    operation.get("method", "PUT"),
                    operation["url"],
                    data=chunk,
                    headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if attempt == self._max_retries:
                    raise UploadError(f"Network error uploading {path.name}: {exc}") from exc
                time.sleep(self._backoff(attempt))
                continue

            if response.ok:
                return
            if response.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                time.sleep(self._retry_after(response, attempt))
                continue
            raise UploadError(
                f"Uploading {path.name} failed with HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

    def _commit_screenshot(self, screenshot_id: str, checksum: str) -> None:
        self._request(
            "PATCH",
            f"/v1/appScreenshots/{screenshot_id}",
            json={
                "data": {
                    "type": "appScreenshots",
                    "id": screenshot_id,
                    "attributes": {"uploaded": True, "sourceFileChecksum": checksum},
                }
            },
        )


def _describe_errors(payload: dict[str, Any]) -> str:
    errors = payload.get("errors")
    if not errors:
        return str(payload)[:400]
    parts = []
    for err in errors:
        title = err.get("title", "Error")
        detail = err.get("detail", "")
        pointer = (err.get("source") or {}).get("pointer", "")
        parts.append(f"{title}: {detail}{f' ({pointer})' if pointer else ''}")
    return " | ".join(parts)
