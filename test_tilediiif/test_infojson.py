import math

import pytest
from hypothesis import assume, example, given
from hypothesis.strategies import integers, none, one_of, sampled_from

from tilediiif.infojson import (
    iiif_image_metadata_with_pow2_tiles, MAX_IMAGE_DIMENSION,
    power2_image_pyramid_scale_factors, validate_id_url)

image_dimensions = integers(min_value=1, max_value=MAX_IMAGE_DIMENSION)
id_urls = sampled_from([
    'https://iiifexample.com/foo',
    'http://iiif.example.com/bar',
])
formats = one_of(none(), sampled_from(['jpg', 'jpeg', 'png']))


@given(id_url=id_urls, format=formats, width=image_dimensions,
       height=image_dimensions, tile_size=integers(min_value=1))
def test_iiif_image_metadata_with_pow2_tiles(id_url, format, width, height,
                                             tile_size):
    meta = iiif_image_metadata_with_pow2_tiles(
        id_url=id_url, format=format, width=width, height=height,
        tile_size=tile_size)

    assert meta['width'] == width
    assert meta['height'] == height
    assert len(meta['tiles']) == 1
    tiles, = meta['tiles']
    assert tiles['width'] == tile_size
    assert tiles['scaleFactors'] == power2_image_pyramid_scale_factors(
        width=width, height=height, tile_size=tile_size)

    # Note that jpeg is not normalised to jpg. Callers should do this
    # themselves, as jpg (not jpeg) is the required level0 format.
    if format in (None, 'jpg'):
        assert meta['profile'] == ['http://iiif.io/api/image/2/level0.json']
    else:
        assert meta['profile'] == ['http://iiif.io/api/image/2/level0.json', {
            'formats': [format]
        }]


@given(width=integers(), height=integers(), tile_size=integers())
@example(MAX_IMAGE_DIMENSION + 1, 1000, 100)
@example(1000, MAX_IMAGE_DIMENSION + 1, 100)
def test_power2_image_pyramid_scale_factors_fails_with_illegal_sizes(
        width, height, tile_size):
    assume(any(n < 1 for n in [width, height, tile_size]) or
           any(n > MAX_IMAGE_DIMENSION for n in [width, height]))
    with pytest.raises(ValueError):
        power2_image_pyramid_scale_factors(
            width=width, height=height, tile_size=tile_size)


@given(width=image_dimensions,
       height=image_dimensions,
       tile_size=integers(min_value=1))
def test_power2_image_pyramid_scale_factors(width, height, tile_size):
    scale_factors = power2_image_pyramid_scale_factors(
        width=width, height=height, tile_size=tile_size)
    # There are no duplicates
    assert len(set(scale_factors)) == len(scale_factors)
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


@pytest.mark.parametrize('url, ok_or_msg', [
    ['http://foo.example/blah', None],
    ['https://foo.example/blah', None],
    ['unknown://foo.example/blah',
     "invalid @id URL: scheme was required to be one of ['http', 'https'] but "
     "was 'unknown'"],
    ['http://foo.example/blah/', 'invalid @id URL: path ends with a /'],
    ['https:/blah/', 'invalid @id URL: host was required but missing'],
    ['https://foo.example', 'invalid @id URL: path was required but missing'],
    ['https://user:pass@foo.example',
     'invalid @id URL: "https://user:pass@foo.example" contained a password '
     'when validation forbade it'],
])
def test_validate_id_url(url, ok_or_msg):
    try:
        validate_id_url(url)
        if ok_or_msg is not None:
            pytest.fail(f'should have raised')
    except ValueError as e:
        assert ok_or_msg in str(e)
