"""Read App Store Connect settings from a ``.env`` file.

The Key ID and the Issuer ID never change between runs, so they live in a
``.env`` at the project root rather than being retyped into the UI every time.
``.env`` is gitignored; ``.env.example`` shows the shape.

Real environment variables win over the file, so CI can set them directly.

The file is read into a dict rather than pushed into ``os.environ``: a long-lived
Streamlit process re-reads it on every run, and a value already copied into the
environment could never be *removed* by editing the file.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

from ..errors import CredentialsError

#: Every setting the .env file may carry.
KEY_ID = "ASC_KEY_ID"
ISSUER_ID = "ASC_ISSUER_ID"
KEY_PATH = "ASC_KEY_PATH"
BUNDLE_ID = "ASC_BUNDLE_ID"

#: Fallback location, so the installed CLI finds the project's .env from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_file_values: dict[str, str] = {}
_loaded_from: Path | None = None


def load() -> Path | None:
    """(Re-)read the nearest ``.env`` and return where it came from, if anywhere.

    Searches upward from the working directory, then falls back to the project
    root inferred from this file's location, so it works whether you run
    ``streamlit run streamlit_app.py`` from the repo or the installed CLI from
    somewhere else.

    Safe to call on every run: the file is re-read each time, so deleting a line
    from ``.env`` takes effect on the next page refresh.
    """
    global _file_values, _loaded_from

    found = find_dotenv(usecwd=True)
    if not found:
        candidate = PROJECT_ROOT / ".env"
        found = str(candidate) if candidate.is_file() else ""

    if found:
        _file_values = {k: v for k, v in dotenv_values(found).items() if v is not None}
        _loaded_from = Path(found)
    else:
        _file_values = {}
        _loaded_from = None
    return _loaded_from


def source() -> Path | None:
    """The ``.env`` that :func:`load` used, for showing in the UI."""
    return _loaded_from


def get(name: str, default: str = "") -> str:
    """A setting from the real environment, else the ``.env``, else ``default``."""
    value = os.environ.get(name) or _file_values.get(name) or default
    return value.strip()


def require_key_and_issuer() -> tuple[str, str]:
    """Return ``(key_id, issuer_id)`` or explain exactly what to put where."""
    key_id, issuer_id = get(KEY_ID), get(ISSUER_ID)
    missing = [name for name, value in ((KEY_ID, key_id), (ISSUER_ID, issuer_id)) if not value]
    if missing:
        where = source() or Path.cwd() / ".env"
        it_or_them = "them" if len(missing) > 1 else "it"
        raise CredentialsError(
            f"{' and '.join(missing)} not set. Add {it_or_them} to {where}. "
            "Copy .env.example and fill in the codes from App Store Connect, "
            "under Users and Access, Integrations, Keys."
        )
    return key_id, issuer_id
