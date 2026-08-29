"""One-line folder input for Streamlit, which has no native folder widget.

Type or paste a path, or press *Choose…* for the real Finder dialog. The dialog
opens on the machine running the Streamlit server, so it is for local use — the
text field is always there as the fallback.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

import streamlit as st


def _native_folder_dialog(prompt: str) -> str | None:
    """Open Finder's folder chooser via AppleScript. macOS + local server only."""
    if platform.system() != "Darwin":
        return None
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() or None


def folder_input(label: str, key: str, placeholder: str = "") -> Path | None:
    """Render the input and return the chosen folder, or ``None``."""
    path_key = f"{key}__path"
    st.session_state.setdefault(path_key, "")
    # A widget's value cannot be reassigned once instantiated, so the Choose…
    # button bumps a nonce to give the text field a fresh key instead.
    nonce = st.session_state.setdefault(f"{key}__nonce", 0)

    field, button = st.columns([5, 1], vertical_alignment="bottom")
    typed = field.text_input(
        label,
        value=st.session_state[path_key],
        key=f"{key}__input{nonce}",
        placeholder=placeholder,
    ).strip()
    st.session_state[path_key] = typed

    if platform.system() == "Darwin" and button.button("Choose…", key=f"{key}__browse"):
        chosen = _native_folder_dialog(f"Choose the {label}")
        if chosen:
            st.session_state[path_key] = chosen.rstrip("/")
            st.session_state[f"{key}__nonce"] = nonce + 1
            st.rerun()

    if not typed:
        return None
    folder = Path(typed).expanduser()
    if not folder.is_dir():
        st.error(f"Not a folder: {folder}")
        return None
    return folder
