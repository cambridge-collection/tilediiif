import math
import subprocess
from pathlib import Path
from types import MappingProxyType

import pytest
import pyvips
from hypothesis import given
from hypothesis.strategies import data, integers

from integration_test.data import (
    TEST_IMG_PEARS_ADOBERGB1998_EMBEDDED,
    TEST_IMG_PEARS_ADOBERGB1998_STRIPPED,
    TEST_IMG_PEARS_SRGB_EMBEDDED,
    TEST_IMG_PEARS_SRGB_STRIPPED,
)
from integration_test.dzi_tiles.test_icc_profile_behaviour import image_as_ndarray
from tilediiif.dzi import parse_dzi_file

from .test_icc_profile_behaviour import PROFILE_SRGB_PATH

SRC_IMAGES = {
    "pears_srgb": TEST_IMG_PEARS_SRGB_EMBEDDED,
    "pears_srgb_stripped": TEST_IMG_PEARS_SRGB_STRIPPED,
    # Note: these Adobe RGB 1998 images were generated from an sRGB image, so we can
    # expect that their colours are all within the sRGB gamut, so colour values of the
    # tiles should precisely match those of these reference images.
    "pears_adobergb1998": TEST_IMG_PEARS_ADOBERGB1998_EMBEDDED,
    "pears_adobergb1998_stripped": TEST_IMG_PEARS_ADOBERGB1998_STRIPPED,
}


@pytest.fixture(scope="session", params=SRC_IMAGES.keys())
def src_image_id(request):
    return request.param


@pytest.fixture(scope="session")
def src_image_data(src_image_id):
    return SRC_IMAGES[src_image_id]


@pytest.fixture(scope="session")
def dzi_path(session_tmp_data_path, src_image_id, dzi_overlap):
    return session_tmp_data_path / f"{src_image_id}_overlap{dzi_overlap}"


@pytest.fixture(scope="session")
def src_image_path(src_image_data):
    return src_image_data["path"]


@pytest.fixture(scope="session")
def src_image(src_image_path, src_image_data):
    img = pyvips.Image.new_from_file(str(src_image_path))
    cpl = src_image_data["colour_profile_location"]
    if cpl == "embedded":
        return img.icc_transform(
            str(PROFILE_SRGB_PATH), embedded=True, intent=pyvips.Intent.RELATIVE
        ).copy(interpretation=pyvips.Interpretation.SRGB)
    elif cpl is None and src_image_data["colour_profile"] == "srgb":
        return img
    elif isinstance(cpl, Path):
        return img.icc_transform(
            str(PROFILE_SRGB_PATH),
            input_profile=str(cpl),
            embedded=False,
            intent=pyvips.Intent.RELATIVE,
        ).copy(interpretation=pyvips.Interpretation.SRGB)
    raise AssertionError(f"Unable to handle src_image_data: {src_image_data}")


@pytest.fixture(scope="session", params=[0, 1, 10])
def dzi_overlap(request):
    return request.param


@pytest.fixture(scope="session")
def colour_handling_args(src_image_data):
    cpl = src_image_data["colour_profile_location"]
    if cpl == "embedded":
        return []
    elif cpl is None and src_image_data["colour_profile"] == "srgb":
        return ["--input-colour-sources=assume-srgb"]
    elif isinstance(cpl, Path):
        return [
            "--input-colour-sources=external-profile",
            "--external-input-profile",
            str(cpl),
        ]
    raise AssertionError(f"Unable to handle src_image_data: {src_image_data}")


@pytest.fixture(scope="session")
def generated_dzi(src_image_path, dzi_path, dzi_overlap, colour_handling_args):
    result = subprocess.run(
        [
            "dzi-tiles",
            # use excessive quality to minimise differences from JPEG losses
            "--jpeg-quality=100",
            "--no-jpeg-subsample",
            "--dzi-overlap",
            str(dzi_overlap),
            *colour_handling_args,
            src_image_path,
            dzi_path,
        ],
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="session")
def max_dzi_level(dzi_meta):
    return math.ceil(math.log2(max(dzi_meta["width"], dzi_meta["height"])))


@pytest.fixture(scope="session")
def min_dzi_level(dzi_meta):
    # note that generated DZIs have levels down to 0 (below tile size, e.g. to 1x1
    # pixels), but they're pointless.
    return math.ceil(math.log2(dzi_meta["tile_size"]))


@pytest.fixture(scope="session")
def get_tile_count(dzi_meta, max_dzi_level):
    def get_tile_count(level: int):
        assert 0 <= level <= max_dzi_level
        scale = 2 ** (max_dzi_level - level)

        sizes = dzi_meta["width"], dzi_meta["height"]
        return tuple(math.ceil(size / scale / dzi_meta["tile_size"]) for size in sizes)

    return get_tile_count


@pytest.fixture(scope="session")
def get_tile_coords_strategies(get_tile_count):
    def get_tile_coords_strategies(level: int):
        width, height = get_tile_count(level)
        return (
            integers(min_value=0, max_value=width - 1),
            integers(min_value=0, max_value=height - 1),
        )

    return get_tile_coords_strategies


@pytest.fixture(scope="session")
def tile_levels_strategy(min_dzi_level, max_dzi_level):
    return integers(min_value=min_dzi_level, max_value=max_dzi_level)


@pytest.fixture(scope="session")
def dzi_meta(generated_dzi, dzi_path):
    return MappingProxyType(parse_dzi_file(f"{dzi_path}.dzi"))


@given(data=data())
def test_generated_dzi_tiles_match_src_image(
    data,
    src_image,
    dzi_meta,
    dzi_path,
    tile_levels_strategy,
    get_tile_coords_strategies,
):
    level = data.draw(tile_levels_strategy)
    xs, ys = get_tile_coords_strategies(level)
    x, y = data.draw(xs), data.draw(ys)

    tile_deltae = get_tile_deltae(
        src_img=src_image, dzi_path=dzi_path, level=level, x=x, y=y, dzi_meta=dzi_meta
    )

    assert image_as_ndarray(tile_deltae).mean() < 0.7


def get_tile_deltae(
    *, src_img: pyvips.Image, dzi_path: Path, level: int, x: int, y: int, dzi_meta=None
):
    """Calculate the colour difference between a single DZI tile and a reference image.

    :arg src_img The 100% scale reference image. Subregions will be compared with the
                 selected tile.
    :returns an image of the same size as the selected tile, where each pixel is the
             CIE 2000 Colour-Difference Delta E difference between the reference and the
             actual DZI tile at that pixel.
    """
    # Assume the source image is in a format with defined colours, e.g. 'srgb'
    # interpretation. dE00() internally invokes colourspace('LAB'), so src_img can be
    # in any interpretation that vips supports as input to colourspace().
    assert src_img.interpretation not in (
        pyvips.Interpretation.RGB,
        pyvips.Interpretation.RGB16,
    )
    if dzi_meta is None:
        dzi_meta = parse_dzi_file(f"{dzi_path}.dzi")

    assert src_img.width == dzi_meta["width"]
    assert src_img.height == dzi_meta["height"]

    max_level = math.ceil(math.log2(max(dzi_meta["width"], dzi_meta["height"])))
    assert 0 <= level <= max_level

    scale = 2 ** (max_level - level)
    tile_size = dzi_meta["tile_size"]
    src_overlap = dzi_meta["overlap"] * scale
    src_tile_size = tile_size * scale

    src_left = x * src_tile_size - src_overlap
    src_top = y * src_tile_size - src_overlap
    src_right = src_left + src_tile_size + src_overlap * 2
    src_bottom = src_top + src_tile_size + src_overlap * 2
    clamped_src_left = max(0, src_left)
    clamped_src_top = max(0, src_top)
    clamped_src_right = min(src_img.width, src_right)
    clamped_src_bottom = min(src_img.height, src_bottom)

    src_tile = src_img.crop(
        clamped_src_left,
        clamped_src_top,
        clamped_src_right - clamped_src_left,
        clamped_src_bottom - clamped_src_top,
    ).shrink(scale, scale)

    dzi_tile = pyvips.Image.new_from_file(
        f"{dzi_path}_files/{level}/{x}_{y}.{dzi_meta['format']}"
    )
    assert src_tile.width == dzi_tile.width
    assert src_tile.height == dzi_tile.height

    # Assume tiles are sRGB
    assert dzi_tile.interpretation == pyvips.Interpretation.SRGB
    dzi_tile_lab = dzi_tile.colourspace(pyvips.Interpretation.LAB)

    return src_tile.dE00(dzi_tile_lab)
