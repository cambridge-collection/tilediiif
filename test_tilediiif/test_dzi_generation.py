from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pyvips

from tilediiif.config.exceptions import ConfigValidationError
from tilediiif.dzi_generation import (
    DEFAULT_OUTPUT_PROFILE,
    VIPS_META_ICC_PROFILE,
    ApplyColourProfileImageOperation,
    AssignProfileVIPSColourSource,
    AssumeSRGBColourSource,
    BaseColourSource,
    ColourConfig,
    ColourSource,
    ColourSourceNotAvailable,
    DZIGenerationError,
    DZITilesConfiguration,
    EmbeddedProfileVIPSColourSource,
    IOConfig,
    JPEGConfig,
    JPEGQuantTable,
    LoadColoursImageOperation,
    RenderingIntent,
    UnmanagedColourSource,
    ensure_mozjpeg_present_if_required,
    format_jpeg_encoding_options,
    get_image_colour_source,
    indent,
    set_icc_profile,
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

    assert str(exc_info.value) == (
        "value for 'dest_dzi' is invalid: path ends with a /, but the path should "
        "identify a path under a directory"
    )


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
                        optimize_coding=False,
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
                        src_image="some/path/image.tif", dest_dzi="some/path/image.tif",
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
                        src_image="some/path/image.tif", dest_dzi="some/path/image.tif",
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
                        src_image="some/path/image.tif", dest_dzi="some/path/image.tif",
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
                        src_image="some/path/image.tif", dest_dzi="some/path/image.tif",
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
        "tilediiif.dzi_generation.libjpeg_supports_params", _libjpeg_supports_params
    ):
        with patch(
            "tilediiif.dzi_generation.pyvips_supports_params", _pyvips_supports_params
        ):
            try:
                ensure_mozjpeg_present_if_required(jpeg_config)
                assert mozjpeg_supported or not mozjpeg_option_used
            except CommandError:
                assert not mozjpeg_supported or not mozjpeg_option_used


def new_test_image():
    """Create a 1x1 8bit RGB image with all channels set to 0."""
    return pyvips.Image.new_from_memory(b"\x00" * 3, 1, 1, 3, "uchar")


@pytest.fixture
def srgb_image():
    return new_test_image().copy(interpretation=pyvips.Interpretation.SRGB)


@pytest.fixture
def rgb_image():
    return new_test_image()


@pytest.fixture
def image_with_srgb_icc_profile(srgb_profile):
    image = new_test_image()
    set_icc_profile(image, srgb_profile)
    return image


@pytest.fixture(params=["srgb_image", "rgb_image", "image_with_srgb_icc_profile"])
def image(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def image_with_invalid_icc_profile(invalid_icc_profile):
    image = new_test_image()
    set_icc_profile(image, invalid_icc_profile)
    return image


@pytest.fixture(scope="session")
def srgb_profile_path():
    path = Path(__file__).parent.parent / "tilediiif/data/sRGB2014.icc"
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


def test_assume_srgb_colour_source_returns_srgb_input_image(srgb_image):
    image = AssumeSRGBColourSource().load(srgb_image)
    assert image is not srgb_image
    assert get_image_colour_source(image) == ColourSource.ASSUME_SRGB
    assert image.interpretation == pyvips.PCS.LAB


def test_assume_srgb_colour_source_rejects_non_srgb_images(rgb_image):
    assert rgb_image.interpretation == pyvips.Interpretation.RGB
    with pytest.raises(ColourSourceNotAvailable):
        AssumeSRGBColourSource().load(rgb_image)


@pytest.mark.parametrize("intent", [pyvips.Intent.RELATIVE, pyvips.Intent.PERCEPTUAL])
@pytest.mark.parametrize(
    "pcs, expected_pcs",
    [
        [None, pyvips.PCS.LAB],
        [pyvips.PCS.LAB, pyvips.PCS.LAB],
        [pyvips.PCS.XYZ, pyvips.PCS.XYZ],
    ],
)
def test_embedded_profile_vips_colour_source_loads_image_with_embedded_profile(
    pcs, expected_pcs, image_with_srgb_icc_profile, srgb_profile, intent
):
    assert image_with_srgb_icc_profile.get(VIPS_META_ICC_PROFILE) == srgb_profile
    assert image_with_srgb_icc_profile.interpretation == pyvips.Interpretation.RGB

    colour_source = EmbeddedProfileVIPSColourSource(
        intent=intent, profile_connection_space=pcs
    )
    assert colour_source.intent == intent
    assert colour_source.profile_connection_space == expected_pcs

    image = colour_source.load(image_with_srgb_icc_profile)

    assert get_image_colour_source(image) == ColourSource.EMBEDDED_PROFILE
    assert image.interpretation == expected_pcs
    assert image.get(VIPS_META_ICC_PROFILE) == srgb_profile


def test_embedded_profile_vips_colour_source_rejects_image_without_embedded_profile(
    srgb_image,
):
    assert VIPS_META_ICC_PROFILE not in srgb_image.get_fields()
    with pytest.raises(ColourSourceNotAvailable):
        EmbeddedProfileVIPSColourSource(intent=pyvips.Intent.RELATIVE).load(srgb_image)


def test_embedded_profile_vips_colour_source_raises_error_on_failed_conversion(
    image_with_invalid_icc_profile,
):
    with pytest.raises(DZIGenerationError) as exc_info:
        EmbeddedProfileVIPSColourSource(intent=pyvips.Intent.RELATIVE).load(
            image_with_invalid_icc_profile
        )

    assert "icc_import() failed: unable to call icc_import" in str(exc_info.value)


@pytest.mark.parametrize(
    "params",
    [
        dict(),
        dict(intent="sdf"),
        dict(intent=pyvips.Intent.RELATIVE, profile_connection_space="sfds"),
    ],
)
def test_embedded_profile_vips_colour_source_rejects_invalid_init_params(params):
    with pytest.raises((TypeError, ValueError)):
        EmbeddedProfileVIPSColourSource(**params)


@pytest.mark.parametrize("intent", [pyvips.Intent.RELATIVE, pyvips.Intent.PERCEPTUAL])
@pytest.mark.parametrize(
    "pcs, expected_pcs",
    [
        [None, pyvips.PCS.LAB],
        [pyvips.PCS.LAB, pyvips.PCS.LAB],
        [pyvips.PCS.XYZ, pyvips.PCS.XYZ],
    ],
)
def test_assign_profile_vips_colour_source_assigns_profile_from_path(
    image, srgb_profile_path, srgb_profile, pcs, expected_pcs, intent
):
    colour_source = AssignProfileVIPSColourSource(
        icc_profile_path=srgb_profile_path, intent=intent, profile_connection_space=pcs
    )
    assert colour_source.icc_profile == srgb_profile
    assert colour_source.profile_connection_space == expected_pcs
    assert colour_source.intent == intent

    result_image = colour_source.load(image)

    assert get_image_colour_source(result_image) == ColourSource.EXTERNAL_PROFILE
    assert result_image.get(VIPS_META_ICC_PROFILE) == srgb_profile
    assert result_image.interpretation == expected_pcs


@pytest.mark.parametrize(
    "params",
    [
        dict(),
        dict(icc_profile=42, intent=pyvips.Intent.RELATIVE),
        dict(icc_profile_path="foo", icc_profile=b"foo", intent=pyvips.Intent.RELATIVE),
        dict(icc_profile=b"foo", intent="sdf"),
        dict(
            icc_profile=b"foo",
            intent=pyvips.Intent.RELATIVE,
            profile_connection_space="sfds",
        ),
    ],
)
def test_assign_profile_vips_colour_source_rejects_invalid_init_params(params):
    with pytest.raises((TypeError, ValueError)):
        AssignProfileVIPSColourSource(**params)


def test_unmanaged_colour_source(srgb_image):
    image = UnmanagedColourSource().load(srgb_image)

    assert image is not srgb_image
    assert get_image_colour_source(image) == ColourSource.UNMANAGED


@pytest.fixture
def assume_srgb_colour_source():
    return AssumeSRGBColourSource()


@pytest.fixture
def embedded_profile_colour_source():
    return EmbeddedProfileVIPSColourSource(intent=pyvips.Intent.RELATIVE)


@pytest.fixture
def assign_profile_colour_source(srgb_profile):
    return AssignProfileVIPSColourSource(
        intent=pyvips.Intent.RELATIVE, icc_profile=srgb_profile
    )


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
        [["assume_srgb_colour_source"], pytest.lazy_fixture("rgb_image"), None],
        [
            ["embedded_profile_colour_source", "assume_srgb_colour_source"],
            pytest.lazy_fixture("rgb_image"),
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
            pytest.lazy_fixture("rgb_image"),
            2,
        ],
        [
            [
                "embedded_profile_colour_source",
                "assume_srgb_colour_source",
                "assign_profile_colour_source",
                "dummy_colour_source",
            ],
            pytest.lazy_fixture("rgb_image"),
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
    "depth, expected_interpretation, expected_format",
    [
        [8, pyvips.Interpretation.RGB, pyvips.BandFormat.UCHAR],
        [16, pyvips.Interpretation.RGB16, pyvips.BandFormat.USHORT],
    ],
)
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
@pytest.mark.parametrize(
    "pcs, expected_pcs",
    [
        [None, pyvips.PCS.LAB],
        [pyvips.PCS.LAB, pyvips.PCS.LAB],
        [pyvips.PCS.XYZ, pyvips.PCS.XYZ],
    ],
)
def test_apply_colour_profile_image_operation(
    intent,
    pcs_image,
    pcs,
    expected_pcs,
    depth,
    expected_interpretation,
    expected_format,
    icc_profile,
    icc_profile_path,
    expected_profile,
):
    assert pcs_image.interpretation == expected_pcs

    image_op = ApplyColourProfileImageOperation(
        icc_profile=icc_profile,
        icc_profile_path=icc_profile_path,
        profile_connection_space=pcs,
        intent=intent,
        depth=depth,
    )

    assert image_op.profile_connection_space == pcs  # None indicates any PCS is fine
    assert image_op.icc_profile == expected_profile
    assert image_op.intent == intent
    assert image_op.depth == depth

    result = image_op(pcs_image)
    assert result.interpretation == expected_interpretation
    assert result.format == expected_format
    assert result.get(VIPS_META_ICC_PROFILE) == expected_profile


@pytest.mark.parametrize(
    "config, expected",
    [
        [JPEGConfig(), ""],
        [JPEGConfig(quality=75, quant_table=JPEGQuantTable.JPEG_ANNEX_K), ""],
        [JPEGConfig(quality=81), "Q=81"],
        [JPEGConfig(optimize_coding=True), "optimize_coding"],
        [JPEGConfig(subsample=False), "no_subsample"],
        [JPEGConfig(trellis_quant=True), "trellis_quant"],
        [JPEGConfig(overshoot_deringing=True), "overshoot_deringing"],
        [JPEGConfig(optimize_scans=True), "optimize_scans"],
        [JPEGConfig(quant_table=JPEGQuantTable.IMAGEMAGICK), "quant_table=3"],
        [
            JPEGConfig(
                quality=50,
                optimize_coding=True,
                subsample=False,
                trellis_quant=True,
                overshoot_deringing=True,
                optimize_scans=True,
                quant_table=JPEGQuantTable.IMAGEMAGICK,
            ),
            "Q=50,optimize_coding,no_subsample,trellis_quant,overshoot_deringing,"
            "optimize_scans,quant_table=3",
        ],
    ],
)
def test_format_jpeg_encoding_options(config, expected):
    assert format_jpeg_encoding_options(config) == expected
