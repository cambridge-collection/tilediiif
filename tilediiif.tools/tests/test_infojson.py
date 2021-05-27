import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from hypothesis import assume, example, given
from hypothesis.strategies import integers, none, one_of, sampled_from

from tilediiif.tools.infojson import (
    DEFAULT_DATA_PATH,
    DEFAULT_ID_BASE_URL,
    DEFAULT_INDENT,
    DEFAULT_PATH_TEMPLATE,
    MAX_IMAGE_DIMENSION,
    CLIError,
    _create_templated_file_output_method,
    get_id_url,
    iiif_image_metadata_with_pow2_tiles,
    main,
    power2_image_pyramid_scale_factors,
)

image_dimensions = integers(min_value=1, max_value=MAX_IMAGE_DIMENSION)
id_urls = sampled_from(["https://iiifexample.com/foo", "http://iiif.example.com/bar"])
formats = one_of(none(), sampled_from(["jpg", "jpeg", "png"]))


@given(
    id_url=id_urls,
    format=formats,
    width=image_dimensions,
    height=image_dimensions,
    tile_size=integers(min_value=1),
)
def test_iiif_image_metadata_with_pow2_tiles(id_url, format, width, height, tile_size):
    meta = iiif_image_metadata_with_pow2_tiles(
        id_url=id_url, format=format, width=width, height=height, tile_size=tile_size
    )

    assert meta["width"] == width
    assert meta["height"] == height
    assert len(meta["tiles"]) == 1
    (tiles,) = meta["tiles"]
    assert tiles["width"] == tile_size
    assert tiles["scaleFactors"] == power2_image_pyramid_scale_factors(
        width=width, height=height, tile_size=tile_size
    )

    # Note that jpeg is not normalised to jpg. Callers should do this
    # themselves, as jpg (not jpeg) is the required level0 format.
    if format in (None, "jpg"):
        assert meta["profile"] == ["http://iiif.io/api/image/2/level0.json"]
    else:
        assert meta["profile"] == [
            "http://iiif.io/api/image/2/level0.json",
            {"formats": [format]},
        ]


@given(width=integers(), height=integers(), tile_size=integers())
@example(MAX_IMAGE_DIMENSION + 1, 1000, 100)
@example(1000, MAX_IMAGE_DIMENSION + 1, 100)
def test_power2_image_pyramid_scale_factors_fails_with_illegal_sizes(
    width, height, tile_size
):
    assume(
        any(n < 1 for n in [width, height, tile_size])
        or any(n > MAX_IMAGE_DIMENSION for n in [width, height])
    )
    with pytest.raises(ValueError):
        power2_image_pyramid_scale_factors(
            width=width, height=height, tile_size=tile_size
        )


@given(width=image_dimensions, height=image_dimensions, tile_size=integers(min_value=1))
def test_power2_image_pyramid_scale_factors(width, height, tile_size):
    scale_factors = power2_image_pyramid_scale_factors(
        width=width, height=height, tile_size=tile_size
    )
    # There are no duplicates
    assert len(set(scale_factors)) == len(scale_factors)
    # We always start with a 1:1 layer
    assert scale_factors[0] == 1
    # All the layers except the last are larger than tile size (which implies
    # that if the image size is <= tile size, there's one layer).
    assert all(max(width, height) / sf > tile_size for sf in scale_factors[:-1])
    # All the scale factors are powers of 2
    assert all(2 ** int(math.log2(n)) == n for n in scale_factors)
    # The image fits into one tile at the last layer
    assert max(width, height) / scale_factors[-1] <= tile_size


@pytest.mark.parametrize(
    "base, id, msg",
    [
        ["https://example.com/", "", "identifier is not a relative URL path: ''"],
        [
            "https://example.com/",
            "foo/",
            "invalid @id URL 'https://example.com/foo/': path ends with a /",
        ],
        [
            "foo://example.com/",
            "abc",
            "invalid @id URL 'foo://example.com/abc': scheme was required to be one "
            "of ['http', 'https'] but was 'foo'",
        ],
        [
            "https:/abc/",
            "123",
            "invalid @id URL 'https:/abc/123': host was required but missing",
        ],
        [
            "https://user:pass@foo.example/",
            "abc",
            "invalid @id URL 'https://user:pass@foo.example/abc': "
            '"https://user:pass@foo.example/abc" contained a password when '
            "validation forbade it",
        ],
    ],
)
def test_get_id_url_rejects_invalid_urls(base, id, msg):
    with pytest.raises(CLIError) as exc_info:
        get_id_url(base, id)
    assert msg in str(exc_info.value)


@pytest.yield_fixture
def mock_run():
    with patch("tilediiif.tools.infojson.run") as mock_run:
        yield mock_run


@pytest.mark.parametrize(
    "argv, expected_args",
    [
        [
            ["--stdout", "/tmp/foo.dzi"],
            {"--stdout": True, "<dzi-file>": "/tmp/foo.dzi"},
        ],
        [
            [
                "--data-path",
                "/data/path",
                "--id-base-url",
                "http://example.com/foo/",
                "--id",
                "bar",
                "--path-template",
                "example",
                "--indent",
                "4",
                "/tmp/foo.dzi",
            ],
            {
                "--data-path": "/data/path",
                "--id-base-url": "http://example.com/foo/",
                "--id": "bar",
                "--path-template": "example",
                "--indent": "4",
                "<dzi-file>": "/tmp/foo.dzi",
            },
        ],
    ],
)
def test_arg_parsing(argv, expected_args, mock_run):
    call_args = {
        "from-dzi": True,
        "--stdout": False,
        "--data-path": DEFAULT_DATA_PATH,
        "--id-base-url": DEFAULT_ID_BASE_URL,
        "--indent": DEFAULT_INDENT,
        "--path-template": DEFAULT_PATH_TEMPLATE,
        "--help": False,
        "-h": False,
        "--version": False,
        **expected_args,
    }

    main(["from-dzi"] + argv)
    mock_run.assert_called_once()
    assert mock_run.mock_calls[0][1][0] == call_args


@pytest.yield_fixture()
def tmp_data_path(tmp_path):
    with TemporaryDirectory(dir=tmp_path) as path:
        yield Path(path)


@pytest.mark.parametrize(
    "path_template, identifier, expected_sub_path",
    [
        ["{identifier}/info.json", "foo", "foo/info.json"],
        ["{identifier-shard}/{identifier}/info.json", "foo", "b1/71/foo/info.json"],
    ],
)
def test_create_templated_file_output_method(
    path_template, identifier, expected_sub_path, tmp_data_path
):
    write_output = _create_templated_file_output_method(tmp_data_path, path_template)
    write_output(b"content", identifier)
    assert (tmp_data_path / expected_sub_path).read_bytes() == b"content"
