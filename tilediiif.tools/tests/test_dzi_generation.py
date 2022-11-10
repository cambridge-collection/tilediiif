from __future__ import annotations

import contextlib
import logging
import re
import sys
import traceback
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Generator, Sequence
from unittest.mock import MagicMock, patch

import pytest
import pyvips
from tilediiif.core.config.exceptions import ConfigValidationError

from tilediiif.tools.dzi_generation import (
    DEFAULT_OUTPUT_PROFILE,
    VIPS_META_ICC_PROFILE,
    ApplyColourProfileImageOperation,
    AssignProfileVIPSColourSource,
    AssumeSRGBColourSource,
    BaseColourSource,
    ColourConfig,
    ColourManagedImageLoader,
    ColourSource,
    ColourSourceNotAvailable,
    DZIConfig,
    DZIGenerationError,
    DZITilesConfiguration,
    EmbeddedProfileVIPSColourSource,
    InterceptingHandler,
    IOConfig,
    JPEGConfig,
    JPEGQuantTable,
    LoadColoursImageOperation,
    RenderingIntent,
    UnexpectedVIPSLogDZIGenerationError,
    UnmanagedColourSource,
    capture_vips_log_messages,
    ensure_mozjpeg_present_if_required,
    format_jpeg_encoding_options,
    get_image_colour_source,
    indent,
    save_dzi,
    set_icc_profile,
)

EXAMPLE_CONFIG_FILE = str(
    Path(__file__).parent / "data" / "dzi-tiles-example-config.toml"
)


def test_coloursource_for_label():
    assert ColourSource.for_label("embedded-profile") == ColourSource.EMBEDDED_PROFILE

    with pytest.raises(ValueError) as exc_info:
        ColourSource.for_label("foo")

    assert str(exc_info.value) == "'foo' is not a valid ColourSource label"


@pytest.mark.parametrize("by", [2, "  "])
def test_indent(by):
    msg = "hi\nbye\n"
    assert indent(msg, by=by) == "  hi\n  bye\n"


@pytest.mark.parametrize(
    "args, src_image, dest_dzi",
    [
        [{"<src-image>": "foo/bar.tif"}, Path("foo/bar.tif"), Path("foo/bar.tif")],
        [
            {"<src-image>": "foo/bar.tif", "<dest-dzi>": "foo/bar"},
            Path("foo/bar.tif"),
            Path("foo/bar"),
        ],
    ],
)
def test_io_config(args, src_image, dest_dzi):
    config = IOConfig.from_cli_args(args)
    assert config.values.src_image == src_image
    assert config.values.dest_dzi == dest_dzi


def test_io_config_validation_rejects_invalid_dzi_paths():
    with pytest.raises(ConfigValidationError) as exc_info:
        IOConfig(src_image="blah.jpg", dest_dzi="some/dir/")

    assert (
        str(exc_info.value)
        == "value for 'dest_dzi' is invalid: path ends with a /, but the path should "
        "identify a path under a directory"
    )


@pytest.fixture
def enable_example_config(monkeypatch, config_file):
    if config_file is None:
        monkeypatch.delenv("DZI_TILES_CONFIG_FILE", raising=False)
    else:
        monkeypatch.setenv("DZI_TILES_CONFIG_FILE", config_file)


@pytest.fixture
def full_dzi_config(enable_example_config, override_argv, override_envars):
    return DZITilesConfiguration.load()


@pytest.fixture
def override_envars(monkeypatch, envars):
    for name, value in envars.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.fixture
def override_argv(argv):
    argv = argv.split() if isinstance(argv, str) else argv
    with patch("sys.argv", ["dzi-tiles"] + argv):
        yield


@pytest.mark.usefixtures(
    "enable_example_config", "override_argv", "envars", "argv", "config_file"
)
@pytest.mark.parametrize(
    "config_file, envars, argv, expected",
    [
        # Defaults
        [
            None,
            {},
            ["some/path/image.tif"],
            {
                "colour": {
                    "values": dict(
                        input_sources=[ColourSource.EMBEDDED_PROFILE],
                        output_profile_path=DEFAULT_OUTPUT_PROFILE,
                        rendering_intent=RenderingIntent.RELATIVE,
                    ),
                    "undefined": [ColourConfig.input_external_profile_path],
                },
                "dzi": {"values": dict(tile_size=254, overlap=1), "undefined": []},
                "jpeg": {
                    "values": dict(
                        quality=75,
                        optimize_coding=False,
                        progressive=False,
                        subsample=True,
                        trellis_quant=False,
                        overshoot_deringing=False,
                        optimize_scans=False,
                        quant_table=JPEGQuantTable.for_label(0),
                    ),
                    "undefined": [],
                },
                "io": {
                    "values": dict(
                        src_image="some/path/image.tif",
                        dest_dzi="some/path/image.tif",
                    ),
                    "undefined": [],
                },
            },
        ],
        # Just CLI args
        [
            None,
            {},
            [
                "--input-colour-sources=external-profile,assume-srgb,unmanaged",
                "--external-input-profile=/opt/profile-b.icc",
                "--output-profile=/opt/profile-c.icc",
                "--colour-transform-intent=perceptual",
                "--jpeg-quality=30",
                "--jpeg-optimize-coding",
                "--jpeg-progressive",
                "--no-jpeg-subsample",
                "--jpeg-trellis-quant",
                "--jpeg-overshoot-deringing",
                "--jpeg-optimize-scans",
                "--jpeg-quant-table=5",
                "--dzi-tile-size=200",
                "--dzi-overlap=2",
                "some/path/image.tif",
            ],
            {
                "colour": {
                    "values": dict(
                        input_sources=[
                            ColourSource.EXTERNAL_PROFILE,
                            ColourSource.ASSUME_SRGB,
                            ColourSource.UNMANAGED,
                        ],
                        input_external_profile_path="/opt/profile-b.icc",
                        output_profile_path="/opt/profile-c.icc",
                        rendering_intent=RenderingIntent.PERCEPTUAL,
                    ),
                    "undefined": [],
                },
                "dzi": {"values": dict(tile_size=200, overlap=2), "undefined": []},
                "jpeg": {
                    "values": dict(
                        quality=30,
                        optimize_coding=True,
                        progressive=True,
                        subsample=False,
                        trellis_quant=True,
                        overshoot_deringing=True,
                        optimize_scans=True,
                        quant_table=JPEGQuantTable.for_label(5),
                    ),
                    "undefined": [],
                },
                "io": {
                    "values": dict(
                        src_image="some/path/image.tif",
                        dest_dzi="some/path/image.tif",
                    ),
                    "undefined": [],
                },
            },
        ],
        # Primarily config file
        [
            EXAMPLE_CONFIG_FILE,
            {},
            ["some/path/image.tif"],
            {
                "colour": {
                    "values": dict(
                        input_sources=[
                            ColourSource.EMBEDDED_PROFILE,
                            ColourSource.EXTERNAL_PROFILE,
                            ColourSource.ASSUME_SRGB,
                            ColourSource.UNMANAGED,
                        ],
                        input_external_profile_path="/opt/profile-a.icc",
                        output_profile_path="/opt/profile-b.icc",
                        rendering_intent=RenderingIntent.SATURATION,
                    ),
                    "undefined": [],
                },
                "dzi": {"values": dict(tile_size=256, overlap=3), "undefined": []},
                "jpeg": {
                    "values": dict(
                        quality=80,
                        optimize_coding=True,
                        progressive=True,
                        subsample=False,
                        trellis_quant=True,
                        overshoot_deringing=True,
                        optimize_scans=True,
                        quant_table=JPEGQuantTable.for_label(4),
                    ),
                    "undefined": [],
                },
                "io": {
                    "values": dict(
                        src_image="some/path/image.tif",
                        dest_dzi="some/path/image.tif",
                    ),
                    "undefined": [],
                },
            },
        ],
        # Primarily envars
        [
            None,
            {
                "DZI_TILES_INPUT_COLOUR_SOURCES": "external-profile,assume-srgb",
                "DZI_TILES_EXTERNAL_INPUT_PROFILE": "/opt/profile-b.icc",
                "DZI_TILES_OUTPUT_PROFILE": "/opt/profile-c.icc",
                "DZI_TILES_COLOUR_TRANSFORM_INTENT": "perceptual",
                "DZI_TILES_JPEG_QUALITY": "30",
                "DZI_TILES_JPEG_OPTIMIZE_CODING": "true",
                "DZI_TILES_JPEG_PROGRESSIVE": "true",
                "DZI_TILES_JPEG_SUBSAMPLE": "false",
                "DZI_TILES_JPEG_TRELLIS_QUANT": "true",
                "DZI_TILES_JPEG_OVERSHOOT_DERINGING": "true",
                "DZI_TILES_JPEG_OPTIMIZE_SCANS": "true",
                "DZI_TILES_JPEG_QUANT_TABLE": "5",
                "DZI_TILES_DZI_TILE_SIZE": "200",
                "DZI_TILES_DZI_OVERLAP": "2",
            },
            ["some/path/image.tif"],
            {
                "colour": {
                    "values": dict(
                        input_sources=[
                            ColourSource.EXTERNAL_PROFILE,
                            ColourSource.ASSUME_SRGB,
                        ],
                        input_external_profile_path="/opt/profile-b.icc",
                        output_profile_path="/opt/profile-c.icc",
                        rendering_intent=RenderingIntent.PERCEPTUAL,
                    ),
                    "undefined": [],
                },
                "dzi": {"values": dict(tile_size=200, overlap=2), "undefined": []},
                "jpeg": {
                    "values": dict(
                        quality=30,
                        optimize_coding=True,
                        progressive=True,
                        subsample=False,
                        trellis_quant=True,
                        overshoot_deringing=True,
                        optimize_scans=True,
                        quant_table=JPEGQuantTable.for_label(5),
                    ),
                    "undefined": [],
                },
                "io": {
                    "values": dict(
                        src_image="some/path/image.tif",
                        dest_dzi="some/path/image.tif",
                    ),
                    "undefined": [],
                },
            },
        ],
        # Merged
        [
            EXAMPLE_CONFIG_FILE,
            {
                "DZI_TILES_INPUT_COLOUR_SOURCES": "external-profile,assume-srgb",
                "DZI_TILES_EXTERNAL_INPUT_PROFILE": "/opt/profile-c.icc",
                "DZI_TILES_JPEG_QUALITY": "70",
                "DZI_TILES_JPEG_OPTIMIZE_CODING": "false",
                "DZI_TILES_JPEG_PROGRESSIVE": "false",
                "DZI_TILES_JPEG_QUANT_TABLE": "5",
                "DZI_TILES_DZI_TILE_SIZE": "100",
                "DZI_TILES_DZI_OVERLAP": "2",
            },
            [
                "--input-colour-sources=embedded-profile",
                "--jpeg-subsample",
                "--jpeg-quant-table=3",
                "--dzi-overlap=0",
                "some/path/image.tif",
                "some/path/dzis/image",
            ],
            {
                "colour": {
                    "values": dict(
                        input_sources=[ColourSource.EMBEDDED_PROFILE],
                        input_external_profile_path="/opt/profile-c.icc",
                        output_profile_path="/opt/profile-b.icc",
                        rendering_intent=RenderingIntent.SATURATION,
                    ),
                    "undefined": [],
                },
                "dzi": {"values": dict(tile_size=100, overlap=0), "undefined": []},
                "jpeg": {
                    "values": dict(
                        quality=70,
                        optimize_coding=False,
                        progressive=False,
                        subsample=True,
                        trellis_quant=True,
                        overshoot_deringing=True,
                        optimize_scans=True,
                        quant_table=JPEGQuantTable.for_label(3),
                    ),
                    "undefined": [],
                },
                "io": {
                    "values": dict(
                        src_image="some/path/image.tif",
                        dest_dzi="some/path/dzis/image",
                    ),
                    "undefined": [],
                },
            },
        ],
    ],
)
def test_load_config(full_dzi_config, expected):
    assert expected
    for config_name, data in expected.items():
        expected_values = data["values"]
        config_cls = DZITilesConfiguration.CONFIGS[config_name]
        expected_config = config_cls(expected_values)
        config = getattr(full_dzi_config, config_name)

        assert dict(config.values) == dict(expected_config.non_default_values)

        for property in data["undefined"]:
            assert property not in config.values


@pytest.mark.parametrize("libjpeg_supports_params", [True, False])
@pytest.mark.parametrize("libvips_supports_libjpeg_params", [True, False])
@pytest.mark.parametrize("mozjpeg_option_used", [True, False])
def test_ensure_mozjpeg_present_if_required(
    libjpeg_supports_params, libvips_supports_libjpeg_params, mozjpeg_option_used
):
    jpeg_config = JPEGConfig(overshoot_deringing=mozjpeg_option_used)

    mozjpeg_supported = libjpeg_supports_params and libvips_supports_libjpeg_params

    _libjpeg_supports_params = MagicMock(return_value=libjpeg_supports_params)
    _pyvips_supports_params = MagicMock(return_value=libvips_supports_libjpeg_params)
    with patch(
        "tilediiif.tools.dzi_generation.libjpeg_supports_params",
        _libjpeg_supports_params,
    ):
        with patch(
            "tilediiif.tools.dzi_generation.pyvips_supports_params",
            _pyvips_supports_params,
        ):
            try:
                ensure_mozjpeg_present_if_required(jpeg_config)
                assert mozjpeg_supported or not mozjpeg_option_used
            except DZIGenerationError:
                assert not mozjpeg_supported or not mozjpeg_option_used


def new_test_image(depth=8):
    """Create a 1x1 8 or 16 bit RGB image with all channels set to 0."""
    if depth == 8:
        img = pyvips.Image.new_from_memory(b"\x00" * 3, 1, 1, 3, "uchar")
        assert img.interpretation == pyvips.Interpretation.SRGB
        return img
    elif depth == 16:
        img = pyvips.Image.new_from_memory(b"\x00\x00" * 3, 1, 1, 3, "ushort").copy(
            interpretation=pyvips.Interpretation.RGB16,
        )
        assert img.interpretation == pyvips.Interpretation.RGB16
        return img
    raise ValueError(f"unsupported depth: {depth}")


@pytest.fixture
def srgb_image():
    image = new_test_image()
    assert image.interpretation == pyvips.Interpretation.SRGB
    return image


@pytest.fixture
def srgb16_image(rgb16_image):
    return rgb16_image.copy(interpretation=pyvips.Interpretation.SRGB)


@pytest.fixture
def generic_multiband_8bit_image():
    img = new_test_image().copy(interpretation=pyvips.Interpretation.MULTIBAND)
    assert img.interpretation == pyvips.Interpretation.MULTIBAND
    assert img.format == pyvips.BandFormat.UCHAR
    return img


@pytest.fixture
def rgb16_image():
    return new_test_image(depth=16)


@pytest.fixture
def image_with_srgb_icc_profile(srgb_image, srgb_profile):
    image = srgb_image.copy()
    set_icc_profile(image, srgb_profile)
    return image


@pytest.fixture
def image_16_with_srgb_icc_profile(rgb16_image, srgb_profile):
    image = rgb16_image.copy()
    set_icc_profile(image, srgb_profile)
    return image


@pytest.fixture(
    params=[
        "srgb_image",
        "srgb16_image",
        "generic_multiband_8bit_image",
        "rgb16_image",
        "image_with_srgb_icc_profile",
        "image_16_with_srgb_icc_profile",
    ]
)
def image(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def image_with_invalid_icc_profile(invalid_icc_profile):
    image = new_test_image()
    set_icc_profile(image, invalid_icc_profile)
    return image


@pytest.fixture(scope="session")
def srgb_profile_path():
    path = Path(__file__).parent.parent / "tilediiif/tools/data/sRGB2014.icc"
    assert path.is_file()
    return path


@pytest.fixture(scope="session")
def srgb_profile(srgb_profile_path: Path):
    profile_data = srgb_profile_path.read_bytes()
    assert len(profile_data) > 0
    return profile_data


@pytest.fixture(scope="session")
def invalid_icc_profile():
    return b"\x00" * 4


def test_assume_srgb_colour_source_returns_srgb_input_image(srgb_image, srgb_profile):
    image = AssumeSRGBColourSource().load(srgb_image)
    assert image is not srgb_image
    assert get_image_colour_source(image) == ColourSource.ASSUME_SRGB
    assert image.interpretation == pyvips.Interpretation.SRGB
    assert image.get(VIPS_META_ICC_PROFILE) == srgb_profile


def test_assume_srgb_colour_source_rejects_non_srgb_images(
    generic_multiband_8bit_image,
):
    assert (
        generic_multiband_8bit_image.interpretation == pyvips.Interpretation.MULTIBAND
    )
    with pytest.raises(ColourSourceNotAvailable):
        AssumeSRGBColourSource().load(generic_multiband_8bit_image)


@pytest.mark.parametrize(
    "image",
    ["image_with_srgb_icc_profile", "image_16_with_srgb_icc_profile"],
    indirect=True,
)
def test_embedded_profile_vips_colour_source_loads_image_with_embedded_profile(
    image,
    srgb_profile,
):
    assert image.get(VIPS_META_ICC_PROFILE) == srgb_profile
    assert image.interpretation in {
        pyvips.Interpretation.SRGB,
        pyvips.Interpretation.RGB16,
    }

    colour_source = EmbeddedProfileVIPSColourSource()

    result_image = colour_source.load(image)

    assert get_image_colour_source(result_image) == ColourSource.EMBEDDED_PROFILE
    assert result_image.format == image.format
    assert image.get(VIPS_META_ICC_PROFILE) == srgb_profile


def test_embedded_profile_vips_colour_source_rejects_image_without_embedded_profile(
    srgb_image,
):
    assert VIPS_META_ICC_PROFILE not in srgb_image.get_fields()
    with pytest.raises(ColourSourceNotAvailable):
        EmbeddedProfileVIPSColourSource().load(srgb_image)


@pytest.mark.parametrize(
    "icc_profile, icc_profile_path, expected_profile",
    [
        [
            pytest.lazy_fixture("srgb_profile"),
            None,
            pytest.lazy_fixture("srgb_profile"),
        ],
        [
            None,
            pytest.lazy_fixture("srgb_profile_path"),
            pytest.lazy_fixture("srgb_profile"),
        ],
    ],
)
def test_assign_profile_vips_colour_source_assigns_profile_from_path(
    image, icc_profile, icc_profile_path, expected_profile
):
    colour_source = AssignProfileVIPSColourSource(
        icc_profile=icc_profile,
        icc_profile_path=icc_profile_path,
    )
    assert colour_source.icc_profile == expected_profile

    result_image = colour_source.load(image)

    assert result_image is not image
    assert result_image.format == image.format
    assert get_image_colour_source(result_image) == ColourSource.EXTERNAL_PROFILE
    assert result_image.get(VIPS_META_ICC_PROFILE) == expected_profile


@pytest.mark.parametrize(
    "params",
    [
        dict(),
        dict(icc_profile=42),
        dict(icc_profile_path=42),
        dict(icc_profile_path="foo", icc_profile=b"foo"),
    ],
)
def test_assign_profile_vips_colour_source_rejects_invalid_init_params(params):
    with pytest.raises((TypeError, ValueError)):
        AssignProfileVIPSColourSource(**params)


def test_unmanaged_colour_source(srgb_image):
    image = UnmanagedColourSource().load(srgb_image)

    assert image is not srgb_image
    assert image.format == srgb_image.format
    assert get_image_colour_source(image) == ColourSource.UNMANAGED


@pytest.fixture
def assume_srgb_colour_source():
    return AssumeSRGBColourSource()


@pytest.fixture
def embedded_profile_colour_source():
    return EmbeddedProfileVIPSColourSource()


@pytest.fixture
def assign_profile_colour_source(srgb_profile):
    return AssignProfileVIPSColourSource(icc_profile=srgb_profile)


@pytest.fixture
def unmanaged_colour_source():
    return UnmanagedColourSource()


@pytest.fixture
def dummy_colour_source():
    source = MagicMock(spec=BaseColourSource)

    def load(_):
        raise AssertionError("should not be invoked")

    source.load.side_effect = load
    return source


@pytest.fixture
def colour_sources(request):
    sources = [request.getfixturevalue(name) for name in request.param]
    assert all(isinstance(s, BaseColourSource) for s in sources)
    return sources


@pytest.mark.parametrize(
    "colour_sources, image, source_used",
    [
        [
            ["assume_srgb_colour_source"],
            pytest.lazy_fixture("generic_multiband_8bit_image"),
            None,
        ],
        [
            ["embedded_profile_colour_source", "assume_srgb_colour_source"],
            pytest.lazy_fixture("generic_multiband_8bit_image"),
            None,
        ],
        [
            ["embedded_profile_colour_source", "assume_srgb_colour_source"],
            pytest.lazy_fixture("srgb_image"),
            1,
        ],
        [
            [
                "embedded_profile_colour_source",
                "assume_srgb_colour_source",
                "assign_profile_colour_source",
            ],
            pytest.lazy_fixture("generic_multiband_8bit_image"),
            2,
        ],
        [
            [
                "embedded_profile_colour_source",
                "assume_srgb_colour_source",
                "assign_profile_colour_source",
                "dummy_colour_source",
            ],
            pytest.lazy_fixture("generic_multiband_8bit_image"),
            2,
        ],
        [
            [
                "embedded_profile_colour_source",
                "assume_srgb_colour_source",
                "dummy_colour_source",
            ],
            pytest.lazy_fixture("srgb_image"),
            1,
        ],
        [
            ["embedded_profile_colour_source", "dummy_colour_source"],
            pytest.lazy_fixture("image_with_srgb_icc_profile"),
            0,
        ],
        [
            ["unmanaged_colour_source", "dummy_colour_source"],
            pytest.lazy_fixture("srgb_image"),
            0,
        ],
    ],
    indirect=("colour_sources",),
)
def test_load_colours_image_operation(colour_sources, image, source_used):
    wrapped_sources = [MagicMock(wraps=s) for s in colour_sources]
    load_colours = LoadColoursImageOperation(colour_sources=wrapped_sources)

    try:
        result = load_colours(image)
        assert source_used is not None
        assert isinstance(result, pyvips.Image)
    except DZIGenerationError as e:
        assert source_used is None
        assert str(e) == "no ColourSource could handle image"
        return

    assert (
        get_image_colour_source(result)
        == colour_sources[source_used].colour_source_type
    )

    for i, wrapped_source in enumerate(wrapped_sources):
        if i <= source_used:
            wrapped_source.load.assert_called_once_with(image)
        else:
            wrapped_source.load.assert_not_called()


@pytest.fixture
def pcs_image(pcs, image_with_srgb_icc_profile):
    image = image_with_srgb_icc_profile.icc_import(
        embedded=True, pcs=pcs or pyvips.PCS.LAB
    )
    image.remove(VIPS_META_ICC_PROFILE)
    return image


@pytest.mark.parametrize("intent", [pyvips.Intent.RELATIVE, pyvips.Intent.PERCEPTUAL])
@pytest.mark.parametrize(
    "image",
    ["image_with_srgb_icc_profile", "image_16_with_srgb_icc_profile"],
    indirect=True,
)
@pytest.mark.parametrize(
    "depth, expected_interpretation, expected_format",
    [
        [8, pyvips.Interpretation.SRGB, pyvips.BandFormat.UCHAR],
        [16, pyvips.Interpretation.RGB16, pyvips.BandFormat.USHORT],
    ],
)
@pytest.mark.parametrize(
    "icc_profile_path, expected_profile",
    [[pytest.lazy_fixture("srgb_profile_path"), pytest.lazy_fixture("srgb_profile")]],
)
@pytest.mark.parametrize("pcs", [None, pyvips.PCS.LAB, pyvips.PCS.XYZ])
def test_apply_colour_profile_image_operation(
    intent,
    image,
    pcs,
    depth,
    expected_interpretation,
    expected_format,
    icc_profile_path,
    expected_profile,
):
    assert isinstance(image.get(VIPS_META_ICC_PROFILE), bytes)

    image_op = ApplyColourProfileImageOperation(
        icc_profile_path=icc_profile_path,
        profile_connection_space=pcs,
        intent=intent,
        depth=depth,
    )

    assert image_op.profile_connection_space == pcs  # None indicates any PCS is fine
    assert image_op.icc_profile_path == icc_profile_path
    assert image_op.intent == intent
    assert image_op.depth == depth

    result = image_op(image)
    assert result.interpretation == expected_interpretation
    assert result.format == expected_format
    assert result.get(VIPS_META_ICC_PROFILE) == expected_profile


@pytest.mark.parametrize(
    "image", ["srgb_image", "generic_multiband_8bit_image"], indirect=True
)
def test_apply_colour_profile_image_operation_requires_input_image_to_have_profile(
    image,
    srgb_profile_path,
):
    image_op = ApplyColourProfileImageOperation(
        icc_profile_path=srgb_profile_path, intent=pyvips.Intent.RELATIVE
    )

    with pytest.raises(ValueError) as exc_info:
        image_op(image)

    assert str(exc_info.value) == "image has no ICC profile attached"


def test_apply_colour_profile_image_operation_raises_error_on_failed_conversion(
    image_with_invalid_icc_profile, srgb_profile_path
):
    with pytest.raises(DZIGenerationError) as exc_info:
        ApplyColourProfileImageOperation(
            icc_profile_path=srgb_profile_path,
            intent=pyvips.Intent.RELATIVE,
        )(image_with_invalid_icc_profile)

    assert "icc_transform() failed: unable to call icc_transform" in str(exc_info.value)


@pytest.mark.parametrize(
    "config, expected",
    [
        [JPEGConfig(), ""],
        [JPEGConfig(quality=75, quant_table=JPEGQuantTable.JPEG_ANNEX_K), ""],
        [JPEGConfig(quality=81), "Q=81"],
        [JPEGConfig(optimize_coding=True), "optimize_coding"],
        [JPEGConfig(progressive=True), "interlace"],
        [JPEGConfig(subsample=False), "no_subsample"],
        [JPEGConfig(trellis_quant=True), "trellis_quant"],
        [JPEGConfig(overshoot_deringing=True), "overshoot_deringing"],
        [JPEGConfig(optimize_scans=True), "optimize_scans"],
        [JPEGConfig(quant_table=JPEGQuantTable.IMAGEMAGICK), "quant_table=3"],
        [
            JPEGConfig(
                quality=50,
                optimize_coding=True,
                progressive=True,
                subsample=False,
                trellis_quant=True,
                overshoot_deringing=True,
                optimize_scans=True,
                quant_table=JPEGQuantTable.IMAGEMAGICK,
            ),
            (
                "Q=50,optimize_coding,interlace,no_subsample,trellis_quant,"
                "overshoot_deringing,optimize_scans,quant_table=3"
            ),
        ],
    ],
)
def test_format_jpeg_encoding_options(config, expected):
    assert format_jpeg_encoding_options(config) == expected


@pytest.fixture
def dzi_config():
    return DZIConfig()


@pytest.fixture
def colour_config():
    return ColourConfig()


@pytest.fixture
def jpeg_config():
    return JPEGConfig()


@pytest.mark.parametrize(
    "io_args, msg",
    [
        [
            dict(src_image=new_test_image(), io_config=IOConfig()),
            "cannot specify src_image and io_config",
        ],
        [
            dict(src_image="some/path", io_config=IOConfig()),
            "cannot specify src_image and io_config",
        ],
        [
            dict(dest_dzi="some/path", io_config=IOConfig()),
            "cannot specify dest_dzi and io_config",
        ],
        [
            dict(dest_dzi="some/path"),
            "src_image and dest_dzi must be specified if io_config isn't",
        ],
        [
            dict(src_image=new_test_image()),
            "src_image and dest_dzi must be specified if io_config isn't",
        ],
        [
            dict(src_image="some/path"),
            "src_image and dest_dzi must be specified if io_config isn't",
        ],
    ],
)
def test_save_dzi_takes_io_as_two_args_or_io_config(io_args, msg):
    with pytest.raises(TypeError) as exc_info:
        save_dzi(**io_args)

    assert str(exc_info.value) == msg


def test_save_dzi_raises_file_not_found_if_src_does_not_exist(tmp_data_path):
    with pytest.raises(FileNotFoundError) as exc_info:
        save_dzi(
            io_config=IOConfig(
                src_image=tmp_data_path / "does-not-exist",
                dest_dzi=tmp_data_path / "out",
            )
        )
    assert str(exc_info.value) == str(tmp_data_path / "does-not-exist")


@pytest.fixture
def unreadable_file(tmp_data_path):
    file = tmp_data_path / "unreadable_file"
    file.touch(mode=0o000)
    return file


@pytest.fixture
def empty_file(tmp_data_path):
    file = tmp_data_path / "empty_file"
    file.touch()
    return file


@pytest.mark.parametrize(
    "src_img_path, expected_message",
    [
        [
            pytest.lazy_fixture("unreadable_file"),
            re.compile(
                r"\Aunable to load src image: ",
                re.MULTILINE | re.DOTALL,
            ),
        ],
        [
            pytest.lazy_fixture("empty_file"),
            re.compile(
                r"\Aunable to load src image: unable to load from file.*"
                r"is not a known file format",
                re.MULTILINE | re.DOTALL,
            ),
        ],
    ],
)
def test_save_dzi_raises_dzi_generation_error_if_src_cannot_be_loaded(
    tmp_data_path, src_img_path, expected_message
):

    with pytest.raises(DZIGenerationError) as exc_info:
        save_dzi(
            io_config=IOConfig(src_image=src_img_path, dest_dzi=tmp_data_path / "out")
        )
    assert expected_message.search(str(exc_info.value))


@pytest.fixture(
    params=[
        "with_existing_dzi",
        "with_existing_files_dir",
        "with_non_dir_parent",
        "with_missing_parent",
    ]
)
def invalid_dest_dzi_type(request):
    return request.param


@pytest.fixture
def invalid_dest_dzi(request, tmp_data_path, invalid_dest_dzi_type):
    return request.getfixturevalue(f"invalid_dest_dzi_{invalid_dest_dzi_type}")


@pytest.fixture(
    params=[
        pytest.param(True, id="via-io_config"),
        pytest.param(False, id="via-src_image-and-dest_dzi"),
    ]
)
def invalid_dest_dzi_save_dzi_io_args(
    request,
    image_with_srgb_icc_profile,
    image_with_srgb_icc_profile_path,
    invalid_dest_dzi,
):
    use_io_config = request.param
    if use_io_config:
        return {
            "io_config": IOConfig(
                src_image=image_with_srgb_icc_profile_path, dest_dzi=invalid_dest_dzi
            )
        }
    else:
        return {"src_image": image_with_srgb_icc_profile, "dest_dzi": invalid_dest_dzi}


@pytest.fixture
def tmp_data_path(tmp_path):
    with TemporaryDirectory(dir=tmp_path) as path:
        yield Path(path)


@pytest.fixture
def image_with_srgb_icc_profile_path(image_with_srgb_icc_profile):
    with NamedTemporaryFile() as f:
        image_with_srgb_icc_profile.pngsave(f.name)
        yield f.name


@pytest.fixture
def invalid_dest_dzi_exception(request, invalid_dest_dzi_type):
    return request.getfixturevalue(
        f"invalid_dest_dzi_{invalid_dest_dzi_type}_exception"
    )


@pytest.fixture
def invalid_dest_dzi_with_existing_dzi(tmp_data_path):
    dest_dzi = tmp_data_path / "out"
    (tmp_data_path / "out.dzi").touch()
    return dest_dzi


@pytest.fixture
def invalid_dest_dzi_with_existing_dzi_exception(invalid_dest_dzi):
    return FileExistsError(f"{invalid_dest_dzi}.dzi already exists")


@pytest.fixture
def invalid_dest_dzi_with_existing_files_dir(tmp_data_path):
    dest_dzi = tmp_data_path / "out"
    (tmp_data_path / "out_files").mkdir()
    return dest_dzi


@pytest.fixture
def invalid_dest_dzi_with_existing_files_dir_exception(invalid_dest_dzi):
    return FileExistsError(f"{invalid_dest_dzi}_files already exists")


@pytest.fixture
def invalid_dest_dzi_with_non_dir_parent(tmp_data_path):
    dzi_parent = tmp_data_path / "a"
    dest_dzi = dzi_parent / "out"
    dzi_parent.touch()
    return dest_dzi


@pytest.fixture
def invalid_dest_dzi_with_non_dir_parent_exception(invalid_dest_dzi):
    return NotADirectoryError(
        f"{invalid_dest_dzi.parent} exists but is not a directory"
    )


@pytest.fixture
def invalid_dest_dzi_with_missing_parent(tmp_data_path):
    # parent is not created
    dzi_parent = tmp_data_path / "a"
    dest_dzi = dzi_parent / "out"
    return dest_dzi


@pytest.fixture
def invalid_dest_dzi_with_missing_parent_exception(invalid_dest_dzi):
    return FileNotFoundError(
        f"{invalid_dest_dzi.parent} does not exist, it must be a directory"
    )


def test_save_dzi_raises_appropriate_os_error_for_dest_path_errors(
    invalid_dest_dzi_save_dzi_io_args, invalid_dest_dzi_exception
):

    with pytest.raises(type(invalid_dest_dzi_exception)) as exc_info:
        save_dzi(**invalid_dest_dzi_save_dzi_io_args)

    assert str(exc_info.value) == str(invalid_dest_dzi_exception)


@pytest.fixture
def mock_colour_managed_image_loader(mock_colour_loader):
    mock = MagicMock(return_value=mock_colour_loader)
    with patch.object(ColourManagedImageLoader, "from_colour_config", new=mock):
        yield mock


@pytest.fixture
def mock_colour_loader(mock_output_image):
    return MagicMock(side_effect=lambda _: mock_output_image)


@pytest.fixture
def mock_output_image(mock_dzsave):
    mock = MagicMock(spec=pyvips.Image)
    mock.dzsave = mock_dzsave
    return mock


@pytest.fixture
def dest_dzi(tmp_data_path):
    return tmp_data_path / "out"


@pytest.fixture
def mock_dzsave():
    def dzsave(dzi_path, **_):
        Path(f"{dzi_path}.dzi").touch()
        Path(f"{dzi_path}_files").mkdir()

    return MagicMock(side_effect=dzsave)


@pytest.fixture
def mock_dzsave_with_vips_warning():
    def dzsave(dzi_path, **_):
        Path(f"{dzi_path}.dzi").touch()
        Path(f"{dzi_path}_files").mkdir()
        # This should result in an error
        logging.getLogger("pyvips").warning("something went slightly wrong")

    return MagicMock(side_effect=dzsave)


@pytest.fixture
def mock_dzsave_raising_pyvips_error():
    def dzsave(dzi_path, **_):
        Path(f"{dzi_path}.dzi").touch()
        Path(f"{dzi_path}_files").mkdir()
        raise pyvips.Error("something went very wrong")

    return MagicMock(side_effect=dzsave)


@pytest.mark.parametrize("colour_config", [None, ColourConfig()])
def test_save_dzi_loads_colour_managed_image_and_saves_it(
    image_with_srgb_icc_profile,
    dest_dzi,
    colour_config,
    dzi_config,
    jpeg_config,
    mock_colour_managed_image_loader,
    mock_colour_loader,
    mock_output_image,
    mock_dzsave,
):
    assert not Path(f"{dest_dzi}.dzi").exists()
    assert not Path(f"{dest_dzi}_files").exists()

    mock_src_img = MagicMock(wraps=image_with_srgb_icc_profile, spec=pyvips.Image)
    save_dzi(
        src_image=mock_src_img,
        dest_dzi=dest_dzi,
        colour_config=colour_config,
        tile_encoding_config=jpeg_config,
        dzi_config=dzi_config,
    )

    mock_colour_managed_image_loader.assert_called_once()
    (used_config,) = mock_colour_managed_image_loader.mock_calls[0][1]
    if colour_config is None:
        assert used_config == ColourConfig()
    else:
        assert used_config is colour_config

    mock_colour_loader.assert_called_once_with(mock_src_img)
    mock_output_image.dzsave.assert_called_once()
    # DZI is created in a temporary location
    tmp_dest_dzi = Path(mock_output_image.dzsave.mock_calls[0][1][0])
    assert mock_output_image.dzsave.mock_calls[0][1][0] != dest_dzi
    assert tmp_dest_dzi.name == "tmp"
    assert mock_output_image.dzsave.mock_calls[0][2] == dict(
        overlap=dzi_config.overlap,
        tile_size=dzi_config.tile_size,
        suffix=f".jpg[{format_jpeg_encoding_options(jpeg_config)}]",
    )

    assert Path(f"{dest_dzi}.dzi").is_file()
    assert Path(f"{dest_dzi}_files").is_dir()
    # temp output is cleaned up
    assert not Path(f"{tmp_dest_dzi}.dzi").exists()
    assert not Path(f"{tmp_dest_dzi}_files").exists()


@pytest.mark.parametrize(
    "mock_dzsave",
    [
        pytest.lazy_fixture("mock_dzsave_with_vips_warning"),
        pytest.lazy_fixture("mock_dzsave_raising_pyvips_error"),
    ],
)
def test_save_dzi_cleans_up_if_dzsave_fails(
    image_with_srgb_icc_profile,
    dest_dzi,
    mock_colour_managed_image_loader,
    mock_colour_loader,
    mock_output_image,
    mock_dzsave,
):
    with pytest.raises(DZIGenerationError) as exc_info:
        save_dzi(src_image=image_with_srgb_icc_profile, dest_dzi=dest_dzi)

    assert any(
        str(exc_info.value) == msg
        for msg in [
            (
                "pyvips unexpectedly emitted a log message at WARNING level: something "
                "went slightly wrong, aborting DZI generation"
            ),
            "dzsave() failed: something went very wrong",
        ]
    )

    (tmp_dest_dzi,) = mock_dzsave.mock_calls[0][1]
    assert not Path(f"{tmp_dest_dzi}.dzi").exists()
    assert not Path(f"{tmp_dest_dzi}_files").exists()

    assert not Path(f"{dest_dzi}.dzi").exists()
    assert not Path(f"{dest_dzi}_files").exists()


@pytest.mark.parametrize(
    "logger",
    [
        # Note that pyvips had a bug resulting in its log messages going to a child
        # logger under pyvips. And regardless, we want to ensure we see messages from
        # sub loggers.
        pytest.param(pyvips.logger, id="pyvips_logger_attribute"),
        pytest.param("pyvips", id="named_logger_pyvips"),
        pytest.param("pyvips.foo", id="named_logger_pyvips.foo"),
    ],
)
@pytest.mark.parametrize(
    "level, level_threshold, should_capture",
    [
        pytest.param(
            level,
            level_threshold,
            should_capture,
            id=f"{logging.getLevelName(level)}_{logging.getLevelName(level_threshold)}",
        )
        for level, level_threshold, should_capture in [
            [logging.ERROR, None, True],
            [logging.WARNING, None, True],
            [logging.INFO, None, False],
            [logging.ERROR, logging.WARNING, True],
            [logging.WARNING, logging.WARNING, True],
            [logging.INFO, logging.WARNING, False],
            [logging.ERROR, logging.ERROR, True],
            [logging.WARNING, logging.ERROR, False],
            [logging.INFO, logging.ERROR, False],
        ]
    ],
)
def test_capture_vips_log_messages_captures_warnings(
    logger, level, level_threshold, should_capture
):
    level_arg = {} if level_threshold is None else {"level": level_threshold}
    assert not any(
        isinstance(h, InterceptingHandler) for h in logging.getLogger("pyvips").handlers
    )
    with capture_vips_log_messages(**level_arg) as capture:
        assert any(
            isinstance(h, InterceptingHandler)
            for h in logging.getLogger("pyvips").handlers
        )

        log = logging.getLogger(logger) if isinstance(logger, str) else logger
        log.log(level, "foo")

    assert not any(
        isinstance(h, InterceptingHandler) for h in logging.getLogger("pyvips").handlers
    )

    if should_capture:
        assert len(capture.records) == 1
        assert capture.records[0].message == "foo"
    else:
        assert len(capture.records) == 0


def test_capture_vips_log_messages_intercepts_warnings_from_vips_native_code():
    with capture_vips_log_messages() as capture:
        trigger_vips_warning()

    assert len(capture.records) == 1
    assert TRIGGERED_VIPS_WARNING_MSG.match(capture.records[0].message)

    with pytest.raises(UnexpectedVIPSLogDZIGenerationError) as exc_info:
        capture.raise_if_records_seen()
        assert re.match(
            r"^pyvips unexpectedly emitted a log message at "
            r"WARNING level: VIPS: ignoring optimize_scans.*, aborting DZI generation$",
            str(exc_info),
        )


@contextlib.contextmanager
def capture_unraisable() -> Generator[
    Sequence[traceback.TracebackException], None, None
]:
    """A context manager that captures an un-raisable exception passed to
    sys.unraisablehook in the context block.
    """
    existing_handler = sys.unraisablehook

    caught: list[traceback.TracebackException] = []

    def on_unraisable(unraisable: sys.UnraisableHookArgs):
        if unraisable.exc_value:
            caught.append(
                traceback.TracebackException.from_exception(unraisable.exc_value)
            )

    try:
        sys.unraisablehook = on_unraisable
        yield caught
    finally:
        sys.unraisablehook = existing_handler


def test_exceptions_in_cffi_callbacks_are_swallowed():
    """Exceptions raised in callbacks from VIPS native code to not terminate the
    main thread. In Python 3.8+ they get passed to sys.unraisablehook.

    This matters to us because we raise an error/warning in response to VIPS
    logging warnings, and those warnings are logged from a a VIPS native code
    callback, so if we raise from the log handler directly, the exception is
    lost.

    We handle this situation, see:
        test_capture_vips_log_messages_intercepts_warnings_from_vips_native_code

    This test exists to document/demonstrate this behaviour of libvips.
    """

    class TestHandler(logging.NullHandler):
        def handle(self, record):
            raise RuntimeError("something went wrong")

    handler = TestHandler()
    logger = logging.getLogger("pyvips")
    try:
        logger.addHandler(handler)
        with capture_unraisable() as captured:
            trigger_vips_warning()

        assert len(captured) == 1
        assert "RuntimeError: something went wrong" in "".join(captured[0].format())
    finally:
        logger.removeHandler(handler)


TRIGGERED_VIPS_WARNING_MSG = re.compile(r"\AVIPS: ignoring optimize_scans.*\Z")


def trigger_vips_warning():
    img = pyvips.Image.new_from_memory(b"\x00" * 3, 1, 1, 3, "uchar")
    # Can't optimise scans in a non-progressive JPEG, so this warns. MozJPEG is
    # required to use optimize_scans, and it also warns if MozJPEG is not available,
    # so doing this will always emit a warning:
    #  - "ignoring optimize_scans" if MozJPEG is not present
    #  - "ignoring optimize_scans for baseline" if MozJPEG is present
    img.jpegsave_buffer(interlace=False, optimize_scans=True)
