import struct

from hypothesis import given, strategies as st
from pathlib import Path
import pytest
import pyvips

from tilediiif.tools.dzi_generation import VIPS_META_ICC_PROFILE

ROOT = (Path(__file__) / "../../..").resolve()


@pytest.mark.parametrize("bytes_per_channel, format", [(1, "uchar"), (2, "ushort")])
def test_new_images_use_srgb_interpretation(bytes_per_channel, format):
    img = pyvips.Image.new_from_memory(b"\x00" * bytes_per_channel * 3, 1, 1, 3, format)
    assert img.interpretation == pyvips.Interpretation.SRGB


def test_rgb_images_loaded_from_files_use_srgb_interpretation():
    img = pyvips.Image.new_from_file(
        str(ROOT / "integration_tests/data/images/pears_small_adobergb1998.jpg")
    )
    assert img.interpretation == pyvips.Interpretation.SRGB
    assert isinstance(img.get(VIPS_META_ICC_PROFILE), bytes)
    assert len(img.get(VIPS_META_ICC_PROFILE)) > 0


def test_16_bit_rgb_images_loaded_from_files_use_rgb16_interpretation():
    img = pyvips.Image.new_from_file(
        str(ROOT / "integration_tests/data/images/test-16_no-colour-profile.png")
    )
    assert img.interpretation == pyvips.Interpretation.RGB16
    assert VIPS_META_ICC_PROFILE not in img.get_fields()


def test_16_bit_rgb_with_colour_profiles_images_loaded_from_files_use_rgb16_interpretation():
    img = pyvips.Image.new_from_file(
        str(ROOT / "integration_tests/data/images/test-16_with-colour-profile.png")
    )
    assert img.interpretation == pyvips.Interpretation.RGB16
    assert isinstance(img.get(VIPS_META_ICC_PROFILE), bytes)
    assert len(img.get(VIPS_META_ICC_PROFILE)) > 0


byte = st.integers(min_value=0, max_value=255)
short = st.integers(min_value=0, max_value=0xFFFF)


@given(byte, byte, byte)
def test_rgb_and_srgb_are_synonymous(r, g, b):
    """
    There's no difference between SRGB and RGB when shifting colour space
    """
    image = pyvips.Image.new_from_memory(struct.pack("<BBB", r, g, b), 1, 1, 3, "uchar")
    rgb = image.copy(interpretation=pyvips.Interpretation.RGB)
    srgb = image.copy(interpretation=pyvips.Interpretation.SRGB)

    rgb_as_lab = rgb.colourspace(pyvips.Interpretation.LAB)
    srgb_as_lab = srgb.colourspace(pyvips.Interpretation.LAB)

    assert rgb_as_lab(0, 0) == srgb_as_lab(0, 0)


@given(byte, byte, byte)
def test_rgb16_is_required_for_correct_interpretation_of_16_bit_images(r, g, b):
    """
    RGB16 is equivalent to SRGB, but the channel range being 0-0xffff rather than 0-0xff
    """
    srgb8 = pyvips.Image.new_from_memory(struct.pack("<BBB", r, g, b), 1, 1, 3, "uchar")
    assert srgb8.interpretation == pyvips.Interpretation.SRGB
    srgb16 = pyvips.Image.new_from_memory(
        struct.pack("<HHH", r * 255, g * 255, b * 255), 1, 1, 3, "ushort"
    ).copy(interpretation=pyvips.Interpretation.RGB16)

    srgb8_as_lab = srgb8.colourspace(pyvips.Interpretation.LAB)
    srgb16_as_lab = srgb16.colourspace(pyvips.Interpretation.LAB)
    roundtrip_srgb8 = srgb8_as_lab.colourspace(pyvips.Interpretation.SRGB)
    roundtrip_srgb16 = srgb16_as_lab.colourspace(pyvips.Interpretation.RGB16)

    # less than 1% difference after round trip to and from LAB. i.e. initial colour
    # values are interpreted in the same way.
    for i in range(3):
        assert (
            abs(
                (roundtrip_srgb8(0, 0)[i] / 0xFF) - (roundtrip_srgb16(0, 0)[i] / 0xFFFF)
            )
            * 100
            < 1
        )


upper_short = st.integers(min_value=255, max_value=0xFFFF)


@given(upper_short, upper_short, upper_short)
def test_srgb_interpretation_of_16_bit_images_is_not_valid_2(r, g, b):
    """
    SRGB interpretation of a 16 bit image format results in the channels being treated
    as 8 bit (0-0xff range).
    """
    image = pyvips.Image.new_from_memory(
        struct.pack("<HHH", r, g, b), 1, 1, 3, "ushort"
    )
    # pyvips defaults to SRGB for 16 bit images, despite it not working as expected if
    # the range used in the channels is > 255.
    assert image.interpretation == pyvips.Interpretation.SRGB
    srgb = image.copy(interpretation=pyvips.Interpretation.SRGB)

    # roundtrip through LAB
    as_lab = srgb.colourspace(pyvips.Interpretation.LAB)
    roundtrip = as_lab.colourspace(pyvips.Interpretation.SRGB)
    assert roundtrip.format == "uchar"  # srgb comes back out as 8 bits

    # The srgb image was interpreted as if it had 0-0xff, not 0-0xffff - all pixels
    # over 255 are treated as 255 when converting to LAB.
    assert roundtrip(0, 0) == [255, 255, 255]
