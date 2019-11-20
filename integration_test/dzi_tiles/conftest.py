from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def tmp_data_path(tmp_path):
    with TemporaryDirectory(dir=tmp_path) as path:
        yield Path(path)


@pytest.fixture
def dzi_basename():
    return "result"


@pytest.fixture
def dzi_path(tmp_data_path, dzi_basename):
    return tmp_data_path / dzi_basename
