import math
from pathlib import Path
import pytest
from hypothesis import given, assume
from hypothesis.strategies import integers

from tilediiif.infojson import (
    parse_dzi_file, iiif_image_metadata_with_pow2_tiles)


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


@given(width=integers(), height=integers(), tile_size=integers())
def test_iiif_image_metadata_with_pow2_tiles_fails_with_values_under_one(
        width, height, tile_size):
    assume(any(n < 1 for n in [width, height, tile_size]))
    with pytest.raises(ValueError):
        iiif_image_metadata_with_pow2_tiles(
            width=width, height=height, tile_size=tile_size)


@given(width=integers(min_value=1),
       height=integers(min_value=1),
       tile_size=integers(min_value=1))
def test_iiif_image_metadata_with_pow2_tiles(width, height, tile_size):
    meta = iiif_image_metadata_with_pow2_tiles(
        width=width, height=height, tile_size=tile_size)

    assert meta['width'] == width
    assert meta['height'] == height
    assert len(meta['tiles']) == 1
    tiles, = meta['tiles']
    assert tiles['width'] == tile_size
    scale_factors = sorted(tiles['scaleFactors'])
    # There are no duplicates
    assert len(set(scale_factors)) == len(tiles['scaleFactors'])
    # We always start with a 1:1 layer
    assert scale_factors[0] == 1
    # All the layers except the last are larger than tile size (which implies
    # that if the image size is <= tile size, there's one layer).
    assert all(max(width, height) / sf > tile_size
               for sf in scale_factors[:-1])
    # All the scale factors are powers of 2
    assert all(2**int(math.log2(n)) == n for n in scale_factors)
    # The image fits into one tile at the last layer
    assert max(width, height) / scale_factors[-1] <= tile_size
