import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def db(tmp_path):
    from app.db import DB
    from tests.schluessel import TEST_KEY
    return DB(str(tmp_path / "t.db"), key=TEST_KEY)
