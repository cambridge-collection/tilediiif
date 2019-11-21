import math
import re
import subprocess

import pytest
import pyvips

from integration_test.data import (
    TEST_IMG_PEARS_SRGB_EMBEDDED,
    TEST_IMG_PEARS_SRGB_STRIPPED,
)
from tilediiif.dzi import parse_dzi_file


@pytest.mark.parametrize(
    "test_img, cli_options, expected",
    [
        [TEST_IMG_PEARS_SRGB_EMBEDDED, [], dict(tile_size=254, overlap=1)],
        [
            TEST_IMG_PEARS_SRGB_EMBEDDED,
            ["--dzi-tile-size", "300", "--dzi-overlap", "0"],
            dict(tile_size=300, overlap=0),
        ],
        [
            TEST_IMG_PEARS_SRGB_EMBEDDED,
            ["--dzi-tile-size", "1024", "--dzi-overlap", "0"],
            dict(tile_size=1024, overlap=0),
        ],
        [
            TEST_IMG_PEARS_SRGB_STRIPPED,
            ["--input-colour-sources", "assume-srgb"],
            dict(tile_size=254, overlap=1),
        ],
        [
            TEST_IMG_PEARS_SRGB_STRIPPED,
            [
                # Use an embedded profile if present,
                # otherwise presume the image is sRGB.
                "--input-colour-sources",
                "embedded-profile,assume-srgb",
            ],
            dict(tile_size=254, overlap=1),
        ],
        [
            TEST_IMG_PEARS_SRGB_STRIPPED,
            ["--input-colour-sources", "unmanaged"],
            dict(tile_size=254, overlap=1),
        ],
    ],
)
def test_dzi_tiles_generates_a_dzi(dzi_path, test_img, cli_options, expected):
    result = subprocess.run(
        ["dzi-tiles"] + cli_options + [test_img["path"], dzi_path],
        capture_output=True,
        encoding="utf-8",
    )

    assert result.returncode == 0

    dzi_meta = parse_dzi_file(dzi_path.parent / (dzi_path.name + ".dzi"))
    assert dzi_meta["tile_size"] == expected["tile_size"]
    assert dzi_meta["overlap"] == expected["overlap"]
    assert dzi_meta["width"] == test_img["width"]
    assert dzi_meta["height"] == test_img["height"]
    assert dzi_meta["format"] == "jpg"

    largest_dzi_level = math.ceil(math.log2(max(test_img["width"], test_img["height"])))
    files_path = dzi_path.parent / (dzi_path.name + "_files")
    assert all(p.is_dir() for p in files_path.iterdir())
    assert {p.name for p in files_path.iterdir()} == set(
        str(l) for l in range(largest_dzi_level + 1)
    )

    assert get_image_size(files_path / str(largest_dzi_level) / "0_0.jpg") == (
        min(expected["tile_size"] + expected["overlap"], test_img["width"]),
        min(expected["tile_size"] + expected["overlap"], test_img["height"]),
    )


def get_image_size(path):
    img = pyvips.Image.new_from_file(str(path))
    return (img.width, img.height)


@pytest.mark.parametrize(
    "test_img, cli_options, err_msg",
    [
        # external profile required, but not specified
        [
            TEST_IMG_PEARS_SRGB_EMBEDDED,
            ["--input-colour-sources", "external-profile"],
            (
                "^"
                + re.escape(
                    "Error: DZI generation failed: the 'external-profile' colour source"
                    " is in input_sources but no input_external_profile_path is "
                    "specified"
                )
                + "$"
            ),
        ],
        # external profile required, but missing
        [
            TEST_IMG_PEARS_SRGB_EMBEDDED,
            [
                "--input-colour-sources",
                "external-profile",
                "--external-input-profile",
                "/does/not/exist.icc",
            ],
            (
                "^"
                + re.escape(
                    "Error: DZI generation failed: Unable to read external input ICC "
                    "profile: [Errno 2] No such file or directory: "
                    "'/does/not/exist.icc'"
                )
                + "$"
            ),
        ],
        [
            # external profile exists, but file is empty
            TEST_IMG_PEARS_SRGB_EMBEDDED,
            [
                "--input-colour-sources",
                "external-profile",
                "--external-input-profile",
                "/dev/null",
            ],
            (
                "^"
                + re.escape(
                    "Error: DZI generation failed: Unable to read external input ICC "
                    "profile: ICC profile file is empty: /dev/null"
                )
                + "$"
            ),
        ],
        # embedded profile required, but image has no embedded profile
        [
            TEST_IMG_PEARS_SRGB_STRIPPED,
            [],
            (
                "^"
                + re.escape(
                    "Error: DZI generation failed: no ColourSource could handle image"
                )
                + "$"
            ),
        ],
        # embedded profile required, but image has no embedded profile
        [
            TEST_IMG_PEARS_SRGB_STRIPPED,
            ["--input-colour-sources", "embedded-profile"],
            (
                "^"
                + re.escape(
                    "Error: DZI generation failed: no ColourSource could handle image"
                )
                + "$"
            ),
        ],
    ],
)
def test_dzi_tiles_rejects_src_images_lacking_colour_info(
    dzi_path, test_img, cli_options, err_msg
):
    result = subprocess.run(
        ["dzi-tiles"] + cli_options + [test_img["path"], dzi_path],
        capture_output=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    assert re.match(err_msg, result.stderr)
