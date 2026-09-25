import sys
from pathlib import Path

import pytest

MODULE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MODULE_ROOT))

from .helpers import assert_element_lifecycle_methods_exist


def pytest_sessionstart(session: pytest.Session) -> None:
    try:
        assert_element_lifecycle_methods_exist()
    except AssertionError as error:
        pytest.exit(str(error), returncode=1)
