import math
import struct
from pathlib import Path

import numpy as np
import pytest
import pyvips
from hypothesis import given
from hypothesis._strategies import sampled_from
from hypothesis.strategies import integers, lists

PROJECT_ROOT = Path(__file__).parents[2]
PROFILE_SRGB_PATH = PROJECT_ROOT / "tilediiif/data/sRGB2014.icc"
IMAGE_DATA = Path(__file__).parents[1] / "data/images"
IMAGE_PEARS = PROJECT_ROOT / "test_tilediiif/server/data/pears_small.jpg"
IMAGE_SUNSET_P3 = IMAGE_DATA / "Sunset-P3.jpg"
IMAGE_SUNSET_P3_SIZE = (397, 600)
# Note: libvips doesn't currently support Black Point Compensation. It uses LittleCMS
# for colour management which does support BPC, so libvips just needs to expose that
# functionality in its API.
IMAGE_SUNSET_P3_AS_SSRGB_RELATIVE_NOBPC = (
    IMAGE_DATA / "Sunset-P3_as-sRGB-relative-noBPC.png"
)
IMAGE_SUNSET_P3_AS_SSRGB_PERCEPTUAL_NOBPC = (
    IMAGE_DATA / "Sunset-P3_as-sRGB-perceptual-noBPC.png"
)


@pytest.mark.parametrize(
    "tx_method",
    [
        pytest.param(
            "import-export",
            marks=pytest.mark.xfail(
                reason="converting with icc_import() followed by icc_export() seems to "
                "introduce inaccuracies"
            ),
        ),
        "transform",
    ],
)
@pytest.mark.parametrize("pcs", [pyvips.PCS.XYZ, pyvips.PCS.LAB])
@pytest.mark.parametrize(
    "input_image_path, expected_image_path, intent, profile",
    [
        [
            IMAGE_SUNSET_P3,
            IMAGE_SUNSET_P3_AS_SSRGB_RELATIVE_NOBPC,
            pyvips.Intent.RELATIVE,
            PROFILE_SRGB_PATH,
        ],
        [
            IMAGE_SUNSET_P3,
            IMAGE_SUNSET_P3_AS_SSRGB_PERCEPTUAL_NOBPC,
            pyvips.Intent.PERCEPTUAL,
            PROFILE_SRGB_PATH,
        ],
        # Round-tripping the same image with the same profile.
        [
            IMAGE_SUNSET_P3_AS_SSRGB_PERCEPTUAL_NOBPC,
            IMAGE_SUNSET_P3_AS_SSRGB_PERCEPTUAL_NOBPC,
            pyvips.Intent.RELATIVE,
            PROFILE_SRGB_PATH,
        ],
    ],
)
def test_vips_colour_space_conversion(
    tx_method, pcs, input_image_path, expected_image_path, intent, profile
):
    input_image = pyvips.Image.new_from_file(str(input_image_path))
    expected_image = pyvips.Image.new_from_file(str(expected_image_path))

    if tx_method == "import-export":
        pcs_image = input_image.icc_import(embedded=True, intent=intent, pcs=pcs)
        result_image = pcs_image.icc_export(
            output_profile=str(profile), intent=intent, pcs=pcs
        )
    else:
        assert tx_method == "transform"
        result_image = input_image.icc_transform(
            str(profile), embedded=True, pcs=pcs, intent=intent
        )

    # vips automatically does a colourspace() conversion to LAB if dE00() inputs are
    # not LAB.
    delta_img = expected_image.icc_import(
        embedded=True, intent=pyvips.Intent.RELATIVE, pcs=pyvips.PCS.XYZ
    ).dE00(
        result_image.icc_import(
            embedded=True, intent=pyvips.Intent.RELATIVE, pcs=pyvips.PCS.XYZ
        )
    )

    # Values are Delta E: 0 is identical, 1 is the smallest difference noticeable by a
    # human. See: http://zschuessler.github.io/DeltaE/learn/
    delta = image_as_ndarray(delta_img)
    assert delta.mean() < 0.1
    assert delta.std() < 0.25
    assert (delta >= 1).sum() / delta.size * 100 < 1.1
    assert (delta >= 2).sum() / delta.size * 100 < 0.15
    assert (delta >= 3).sum() / delta.size * 100 < 0.01
    assert delta.max() < 4


def numpy_dtype(vips_format):
    if isinstance(vips_format, pyvips.Image):
        vips_format = vips_format.format
    return {
        "uchar": np.uint8,
        "char": np.int8,
        "ushort": np.uint16,
        "short": np.int16,
        "uint": np.uint32,
        "int": np.int32,
        "float": np.float32,
        "double": np.float64,
        "complex": np.complex64,
        "dpcomplex": np.complex128,
    }[vips_format]


def image_as_ndarray(image: pyvips.Image):
    return np.swapaxes(
        np.ndarray(
            buffer=image.write_to_memory(),
            dtype=numpy_dtype(image),
            shape=[image.height, image.width, image.bands],
        ),
        0,
        1,
    )


@given(
    x=integers(min_value=0, max_value=IMAGE_SUNSET_P3_SIZE[0] - 1),
    y=integers(min_value=0, max_value=IMAGE_SUNSET_P3_SIZE[1] - 1),
)
def test_image_as_ndarray(x, y):
    img_vips = pyvips.Image.new_from_file(str(IMAGE_SUNSET_P3))
    img_np = image_as_ndarray(img_vips)

    assert tuple(img_np[x, y]) == tuple(img_vips(x, y))


byte = integers(min_value=0, max_value=255)
short = integers(min_value=0, max_value=0xFFFF)
profile_connection_spaces = sampled_from([pyvips.PCS.LAB, pyvips.PCS.XYZ])


@given(r=byte, g=byte, b=byte)
def test_srgb_lab_roundtrip(r, g, b):
    img = pyvips.Image.new_from_memory(bytes([r, g, b]), 1, 1, 3, "uchar").copy(
        interpretation=pyvips.Interpretation.SRGB
    )
    img_lab2srgb = img.colourspace(pyvips.Interpretation.LAB).colourspace(
        pyvips.Interpretation.SRGB
    )

    assert dist(img(0, 0), img_lab2srgb(0, 0)) <= 1


@given(r=byte, g=byte, b=byte)
def test_srgb_lab_roundtrip_icc_transform(r, g, b):
    img = pyvips.Image.new_from_memory(bytes([r, g, b]), 1, 1, 3, "uchar").copy(
        interpretation=pyvips.Interpretation.SRGB
    )
    img_lab2srgb = img.icc_transform(
        str(PROFILE_SRGB_PATH), input_profile=str(PROFILE_SRGB_PATH)
    )

    assert dist(img(0, 0), img_lab2srgb(0, 0)) <= 1


@pytest.mark.xfail(reason="icc_import() with icc_export() doesnt seem very precise")
@given(r=byte, g=byte, b=byte, pcs=profile_connection_spaces)
def test_srgb_roundtrip_icc_import_icc_export(r, g, b, pcs):
    img = pyvips.Image.new_from_memory(bytes([r, g, b]), 1, 1, 3, "uchar").copy(
        interpretation=pyvips.Interpretation.SRGB
    )
    img_lab = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), pcs=pcs)
    img_lab2srgb = img_lab.icc_export(output_profile=str(PROFILE_SRGB_PATH), pcs=pcs)

    assert dist(img(0, 0), img_lab2srgb(0, 0)) <= 1


@pytest.mark.xfail(reason="icc_import() with icc_export() doesnt seem very precise")
@given(r=short, g=short, b=short, pcs=profile_connection_spaces)
def test_srgb_roundtrip_icc_import_icc_export_16(r, g, b, pcs):
    img = pyvips.Image.new_from_memory(struct.pack(">HHH", r, g, b), 1, 1, 3, "ushort")

    img_pcs = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), pcs=pcs)
    img_pcs2srgb = img_pcs.icc_export(
        output_profile=str(PROFILE_SRGB_PATH), pcs=pcs, depth=16
    )

    assert dist([r, g, b], img_pcs2srgb(0, 0)) <= 0xFF


intents = sampled_from(
    [
        pyvips.Intent.SATURATION,
        pyvips.Intent.ABSOLUTE,
        pyvips.Intent.PERCEPTUAL,
        pyvips.Intent.RELATIVE,
    ]
)
intent_pairs = lists(elements=intents, min_size=2, max_size=2)


@given(r=byte, g=byte, b=byte, intent_a=intents, intent_b=intents)
def test_srgb_icc_import_intents_are_identical(r, g, b, intent_a, intent_b):
    img = pyvips.Image.new_from_memory(bytes([r, g, b]), 1, 1, 3, "uchar").copy(
        interpretation=pyvips.Interpretation.SRGB
    )

    img_lab_a = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), intent=intent_a)
    img_lab_b = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), intent=intent_b)

    assert img_lab_a(0, 0) == img_lab_b(0, 0)


@given(
    r=byte,
    g=byte,
    b=byte,
    in_intent_a=intents,
    in_intent_b=intents,
    out_intent_a=intents,
    out_intent_b=intents,
)
def test_srgb_icc_export_intents_are_identical(
    r, g, b, in_intent_a, in_intent_b, out_intent_a, out_intent_b
):
    img = pyvips.Image.new_from_memory(bytes([r, g, b]), 1, 1, 3, "uchar").copy(
        interpretation=pyvips.Interpretation.SRGB
    )

    img_lab_a = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), intent=in_intent_a)
    img_lab_b = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), intent=in_intent_b)
    assert img_lab_a(0, 0) == img_lab_b(0, 0)

    img_srgb_a = img_lab_a.icc_export(
        output_profile=str(PROFILE_SRGB_PATH), intent=out_intent_a
    )
    img_srgb_b = img_lab_b.icc_export(
        output_profile=str(PROFILE_SRGB_PATH), intent=out_intent_b
    )
    assert img_srgb_a(0, 0) == img_srgb_b(0, 0)


@pytest.mark.xfail()
@given(r=byte, g=byte, b=byte, pcs=profile_connection_spaces)
def test_srgb_icc_import_matches_colourspace_func(r, g, b, pcs):
    img = pyvips.Image.new_from_memory(bytes([r, g, b]), 1, 1, 3, "uchar").copy(
        interpretation=pyvips.Interpretation.SRGB
    )

    img_icc = img.icc_import(input_profile=str(PROFILE_SRGB_PATH), pcs=pcs)
    img_colourspace = img.colourspace(pcs)

    delta_e = img_icc.dE00(img_colourspace)
    assert delta_e(0, 0)[0] < 1


def test_dist():
    assert dist([0, 0], [0, 1]) == 1
    assert dist([0, 0], [0, 2]) == 2
    assert dist([0, 0], [2, 0]) == 2
    assert dist([1, 1], [0, 0]) == math.sqrt(2)
    assert dist([2, 2], [0, 0]) == math.sqrt(8)
    assert dist([1, 1, 1], [0, 0, 0]) == math.sqrt(3)


def dist(a, b):
    return math.sqrt(sum((_a - _b) ** 2 for _a, _b in zip(a, b)))


@pytest.mark.xfail(
    reason="seems like a libvips bug - green band comes back as ~3095 instead of 255"
)
def test_depth_16_icc_io_bug():
    img = pyvips.Image.new_from_memory(
        struct.pack("<HHH", 0xFF00, 0xFF, 1 << 15), 1, 1, 3, "ushort"
    )
    img_lab = img.icc_import(input_profile=str(PROFILE_SRGB_PATH))
    img_lab2srgb = img_lab.icc_export(output_profile=str(PROFILE_SRGB_PATH), depth=16)

    assert dist(img(0, 0), img_lab2srgb(0, 0)) < 255
