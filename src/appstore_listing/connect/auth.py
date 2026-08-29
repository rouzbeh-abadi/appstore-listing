"""App Store Connect API authentication.

You need three things from App Store Connect → Users and Access → Integrations → Keys:

* the **.p8 private key file** (downloadable exactly once),
* the **Key ID** -- the code in the key's row, also in the filename ``AuthKey_<KeyID>.p8``,
* the **Issuer ID** -- the UUID shown above the key table.

Those are signed into a short-lived ES256 JWT that every API request carries.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import jwt

from ..errors import CredentialsError

AUDIENCE = "appstoreconnect-v1"
#: Apple rejects tokens valid for more than 20 minutes.
MAX_TOKEN_LIFETIME = 20 * 60
_DEFAULT_LIFETIME = 15 * 60
#: Refresh this many seconds before expiry rather than racing the clock.
_REFRESH_MARGIN = 60

_KEY_ID_FROM_FILENAME = re.compile(r"AuthKey_([A-Z0-9]+)\.p8$", re.IGNORECASE)


def key_id_from_filename(p8_path: str | Path) -> str | None:
    """Pull the Key ID out of Apple's default ``AuthKey_XXXXXXXXXX.p8`` filename."""
    match = _KEY_ID_FROM_FILENAME.search(Path(p8_path).name)
    return match.group(1) if match else None


@dataclass(slots=True)
class Credentials:
    """An App Store Connect API key, held in memory only."""

    key_id: str
    issuer_id: str
    private_key: str

    @classmethod
    def from_p8_file(
        cls, path: str | Path, key_id: str | None = None, issuer_id: str = ""
    ) -> Credentials:
        p8 = Path(path).expanduser()
        if not p8.is_file():
            raise CredentialsError(f"Private key file not found: {p8}")
        resolved_key_id = key_id or key_id_from_filename(p8)
        if not resolved_key_id:
            raise CredentialsError(
                f"Key ID not given and not derivable from {p8.name!r}. "
                "Pass it explicitly (it is the code shown next to the key in App Store Connect)."
            )
        return cls(
            key_id=resolved_key_id.strip(),
            issuer_id=issuer_id.strip(),
            private_key=p8.read_text(),
        ).validated()

    @classmethod
    def from_p8_bytes(cls, data: bytes, key_id: str, issuer_id: str) -> Credentials:
        """Build credentials from an uploaded file's bytes (used by the Streamlit UI)."""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CredentialsError("The .p8 file is not valid UTF-8 text.") from exc
        return cls(key_id=key_id.strip(), issuer_id=issuer_id.strip(), private_key=text).validated()

    def validated(self) -> Credentials:
        if "PRIVATE KEY" not in self.private_key:
            raise CredentialsError(
                "That does not look like a .p8 private key "
                "(expected a '-----BEGIN PRIVATE KEY-----' block)."
            )
        if not self.key_id:
            raise CredentialsError("Key ID is required.")
        if not self.issuer_id:
            raise CredentialsError("Issuer ID is required.")
        return self


class TokenProvider:
    """Mints and caches the ES256 bearer token for App Store Connect."""

    def __init__(self, credentials: Credentials, lifetime: int = _DEFAULT_LIFETIME) -> None:
        if lifetime > MAX_TOKEN_LIFETIME:
            raise CredentialsError(
                f"Token lifetime must be at most {MAX_TOKEN_LIFETIME}s; got {lifetime}s."
            )
        self._credentials = credentials
        self._lifetime = lifetime
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self) -> str:
        """A currently-valid bearer token, minting a fresh one when needed."""
        now = time.time()
        if self._token and now < self._expires_at - _REFRESH_MARGIN:
            return self._token

        payload = {
            "iss": self._credentials.issuer_id,
            "iat": int(now),
            "exp": int(now + self._lifetime),
            "aud": AUDIENCE,
        }
        try:
            self._token = jwt.encode(
                payload,
                self._credentials.private_key,
                algorithm="ES256",
                headers={"kid": self._credentials.key_id, "typ": "JWT"},
            )
        except Exception as exc:  # pragma: no cover - depends on the user's key
            raise CredentialsError(f"Could not sign the JWT with this key: {exc}") from exc

        self._expires_at = now + self._lifetime
        return self._token

    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}
