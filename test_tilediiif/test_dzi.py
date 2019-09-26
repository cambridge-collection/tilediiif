from pathlib import Path

import pytest

from tilediiif.dzi import parse_dzi_file


@pytest.fixture
def dzi_ms_add_path():
    return Path(__file__).parent / 'data' / 'MS-ADD-00269-000-01075.dzi'


@pytest.yield_fixture
def dzi_ms_add_file(dzi_ms_add_path):
    with open(dzi_ms_add_path, 'rb') as f:
        yield f


def test_parse_dzi_file(dzi_ms_add_file):
    assert parse_dzi_file(dzi_ms_add_file) == dict(
        width=6365, height=9841, format='jpg', overlap=1, tile_size=256
    )
