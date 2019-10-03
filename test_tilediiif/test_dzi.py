import math
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis.strategies import (
    builds, characters, fixed_dictionaries,
    integers, sampled_from, text)

from tilediiif.dzi import get_dzi_tile_path, parse_dzi_file
from tilediiif.tilelayout import get_layer_tiles


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


path_segments = text(alphabet=characters(blacklist_categories=('Cs', ),
                                         blacklist_characters=('/',)),
                     min_size=1, max_size=12)
fs_paths = builds(lambda prefix, elements: Path(prefix) / Path(*elements),
                  sampled_from(['/', './']), path_segments)

positive_non_zero_integers = integers(min_value=1)
dzi_metadata = fixed_dictionaries({
    'width': sampled_from([43, 800, 1024, 4096, 9631, 100_000]),
    'height': sampled_from([12, 600, 1024, 4096, 6247, 100_000]),
    'tile_size': sampled_from([100, 256, 1024]),
    'format': sampled_from(['jpg', 'png']),
    'overlap': sampled_from([1, 0])
})


@given(dzi_path=fs_paths, dzi_metadata=dzi_metadata,
       layer=integers(min_value=0, max_value=15),
       tile_num=integers(min_value=0))
def test_get_dzi_tile_path(dzi_path, dzi_metadata, layer, tile_num):
    format = dzi_metadata['format']
    width, height, tile_size = [dzi_metadata[k]
                                for k in ['width', 'height', 'tile_size']]

    dzi_level = math.ceil(math.log2(max(width, height))) - layer
    # 0 is the minimum DZI level
    assume(dzi_level >= 0)
    # Don't waste time testing cases with huge numbers of tiles
    assume((width / (2**layer) / tile_size) * (height / (2**layer) / tile_size)
           < 2000)

    tiles = list(get_layer_tiles(width=width, height=height,
                                 tile_size=tile_size, scale_factor=2**layer))
    tile = tiles[tile_num % len(tiles)]

    x, y = [tile['index'][k] for k in ['x', 'y']]
    path = get_dzi_tile_path(dzi_path, dzi_metadata, tile)

    assert isinstance(path, Path)
    assert path == dzi_path / f'{dzi_level}' / f'{x}_{y}.{format}'
