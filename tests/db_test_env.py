"""Load project .env so TEST_DATABASE_URL is available under unittest discover."""

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_ROOT / ".env")


_load_dotenv()
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
