"""Streamlit entry point:  streamlit run streamlit_app.py

The page itself lives in the package so the ``appstore-listing ui`` command can
reach it too; this file is just the conventional root-level launcher.
"""

import sys
from pathlib import Path

# Work without installing the package first (plain `streamlit run` in a checkout).
_SRC = Path(__file__).parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from appstore_listing.ui.streamlit_app import main  # noqa: E402

main()
