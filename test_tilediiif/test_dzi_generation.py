from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tilediiif.dzi_generation import (
    DEFAULT_OUTPUT_PROFILE,
    ColourConfig,
    ColourSource,
    DZITilesConfiguration,
    IOConfig,
    JPEGConfig,
    JPEGQuantTable,
    RenderingIntent,
    ensure_mozjpeg_present_if_required,
    indent,
)
from tilediiif.exceptions import CommandError

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
        [{"<src-image>": "foo/bar.tif"}, Path("foo/bar.tif"), Path("foo/bar.tif.dzi")],
        [
            {"<src-image>": "foo/bar.tif", "<dest-dzi>": "foo/bar.dzi"},
            Path("foo/bar.tif"),
            Path("foo/bar.dzi"),
        ],
    ],
)
def test_io_config(args, src_image, dest_dzi):
    config = IOConfig.from_cli_args(args)
    assert config.values.src_image == src_image
    assert config.values.dest_dzi == dest_dzi


@pytest.fixture
def enable_example_config(monkeypatch, config_file):
    if config_file is None:
        monkeypatch.delenv("DZI_TILES_CONFIG_FILE", raising=False)
    else:
        monkeypatch.setenv("DZI_TILES_CONFIG_FILE", config_file)


@pytest.fixture
def dzi_config(enable_example_config, override_argv, override_envars):
    return DZITilesConfiguration.load()


@pytest.fixture
def override_envars(monkeypatch, envars):
    for name, value in envars.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


@pytest.yield_fixture
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
                        optimize_coding=True,
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
                        dest_dzi="some/path/image.tif.dzi",
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
                "--input-colour-sources=external-profile,assume-srgb",
                "--external-input-profile=/opt/profile-b.icc",
                "--output-profile=/opt/profile-c.icc",
                "--colour-transform-intent=perceptual",
                "--jpeg-quality=30",
                "--jpeg-optimize-coding",
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
                        dest_dzi="some/path/image.tif.dzi",
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
                        dest_dzi="some/path/image.tif.dzi",
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
                        dest_dzi="some/path/image.tif.dzi",
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
                        dest_dzi="some/path/image.tif.dzi",
                    ),
                    "undefined": [],
                },
            },
        ],
    ],
)
def test_load_config(dzi_config, expected):
    assert expected
    for config_name, data in expected.items():
        expected_values = data["values"]
        config_cls = DZITilesConfiguration.CONFIGS[config_name]
        expected_config = config_cls(expected_values)
        config = getattr(dzi_config, config_name)

        assert dict(config.values) == dict(expected_config.non_default_values)

        for property in data["undefined"]:
            assert property not in config.values


@pytest.mark.parametrize("mozjpeg_supported", [True, False])
@pytest.mark.parametrize("mozjpeg_option_used", [True, False])
def test_ensure_mozjpeg_present_if_required(mozjpeg_supported, mozjpeg_option_used):
    jpeg_config = JPEGConfig(overshoot_deringing=mozjpeg_option_used)

    libjpeg_supports_params = MagicMock(return_value=mozjpeg_supported)
    with patch(
        "tilediiif.dzi_generation.libjpeg_supports_params", libjpeg_supports_params
    ):
        try:
            ensure_mozjpeg_present_if_required(jpeg_config)
            assert mozjpeg_supported or not mozjpeg_option_used
        except CommandError:
            assert not mozjpeg_supported or not mozjpeg_option_used
