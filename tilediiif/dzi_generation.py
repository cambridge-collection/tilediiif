import enum
from abc import ABC, abstractmethod
from ctypes import CDLL, c_bool
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from types import MappingProxyType
from typing import Iterable, Tuple, Union

import pyvips
from docopt import docopt

from tilediiif.config import BaseConfig, Config, ConfigProperty, EnvironmentConfigMixin
from tilediiif.config.exceptions import ConfigValidationError
from tilediiif.config.parsing import delegating_parser, enum_list_parser, simple_parser
from tilediiif.config.properties import (
    BoolConfigProperty,
    EnumConfigProperty,
    IntConfigProperty,
    PathConfigProperty,
)
from tilediiif.config.validation import (
    all_validator,
    in_validator,
    isinstance_validator,
    iterable_validator,
    validate_no_duplicates,
    validate_string,
)
from tilediiif.exceptions import CommandError

from .version import __version__

CONFIG_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "definitions": {
        "colour": {
            "type": "object",
            "properties": {
                "input-colour-sources": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["embedded-profile", "external-profile", "assume-srgb"],
                    },
                },
                "external-input-profile": {"type": "string"},
                "output-profile": {"type": "string"},
                "colour-transform-intent": {
                    "type": "string",
                    "enum": ["perceptual", "relative", "saturation", "absolute"],
                },
            },
            "additionalProperties": False,
        },
        "jpeg": {
            "type": "object",
            "properties": {
                "quality": {"type": "integer", "minimum": 0, "maximum": 100},
                "optimize-coding": {"type": "boolean"},
                "subsample": {"type": "boolean"},
                "trellis-quant": {"type": "boolean"},
                "overshoot-deringing": {"type": "boolean"},
                "optimize-scans": {"type": "boolean"},
                "quant-table": {
                    "anyOf": [
                        {
                            "type": "string",
                            "enum": ["0", "1", "2", "3", "4", "5", "6", "7", "8"],
                        },
                        {"type": "integer", "minimum": 0, "maximum": 8},
                    ]
                },
            },
            "additionalProperties": False,
        },
        "dzi": {
            "type": "object",
            "properties": {
                "tile-size": {"type": "integer", "minimum": 1, "maximum": 8192},
                "overlap": {"type": "integer", "minimum": 0, "maximum": 8192},
            },
            "additionalProperties": False,
        },
    },
    "type": "object",
    "properties": {
        "dzi-tiles": {
            "type": "object",
            "properties": {
                "colour": {"$ref": "#/definitions/colour"},
                "jpeg": {"$ref": "#/definitions/jpeg"},
                "dzi": {"$ref": "#/definitions/dzi"},
            },
            "additionalProperties": False,
        }
    },
    "additionalProperties": False,
}
ENVAR_PREFIX = "DZI_TILES"


class RenderingIntent(enum.Enum):
    PERCEPTUAL = "perceptual"
    RELATIVE = "relative"
    SATURATION = "saturation"
    ABSOLUTE = "absolute"

    @classmethod
    def available_values_description(cls):
        return ", ".join(f"{i.value!r}" for i in cls)

    def __repr__(self):
        return f"{type(self).__name__}.{self.name}"


DEFAULT_RENDERING_INTENT = RenderingIntent.RELATIVE
DEFAULT_OUTPUT_PROFILE = str(Path(__file__).parent / "data/sRGB2014.icc")


class DescribedEnumMixin:
    def __init__(self, label, description):
        self.label = label
        self.description = description

    @classmethod
    def for_label(cls, label):
        try:
            return next(s for s in cls if s.label == label)
        except StopIteration:
            raise ValueError(f"{label!r} is not a valid {cls.__name__} label") from None

    @classmethod
    def describe_members(cls):
        return "\n".join(f"• {member.label} ➜ {member.description}" for member in cls)

    def __repr__(self):
        return f"{type(self).__name__}.for_label({self.label!r})"

    def __str__(self):
        return f"{self.label} ({self.description})"


class ColourSource(DescribedEnumMixin, enum.Enum):
    EMBEDDED_PROFILE = "embedded-profile", "Use an ICC profile embedded in the image"
    EXTERNAL_PROFILE = "external-profile", "Use an ICC profile in an external file"
    ASSUME_SRGB = (
        "assume-srgb",
        "Treat the image as being in the standard sRGB colour space",
    )


def indent(lines, *, by):
    if isinstance(by, int):
        by = " " * by

    return "\n".join(by + l if l else l for l in lines.split("\n"))


validate_colour_sources = all_validator(
    iterable_validator(element_validator=isinstance_validator(ColourSource)),
    validate_no_duplicates,
)


class ColourConfig(Config):
    json_schema = CONFIG_SCHEMA
    property_definitions = [
        ConfigProperty(
            "input_sources",
            default=[ColourSource.EMBEDDED_PROFILE],
            validator=validate_colour_sources,
            normaliser=list,
            parse=enum_list_parser(ColourSource.for_label),
            parse_json=simple_parser(
                lambda sources: [ColourSource.for_label(s) for s in sources]
            ),
            cli_arg="--input-colour-sources=",
            envar_name=f"{ENVAR_PREFIX}_INPUT_COLOUR_SOURCES",
            json_path="dzi-tiles.colour.input-colour-sources",
        ),
        ConfigProperty(
            "input_external_profile_path",
            validator=validate_string,
            cli_arg="--external-input-profile=",
            envar_name=f"{ENVAR_PREFIX}_EXTERNAL_INPUT_PROFILE",
            json_path="dzi-tiles.colour.external-input-profile",
        ),
        ConfigProperty(
            "output_profile_path",
            default=DEFAULT_OUTPUT_PROFILE,
            validator=validate_string,
            cli_arg="--output-profile=",
            envar_name=f"{ENVAR_PREFIX}_OUTPUT_PROFILE",
            json_path="dzi-tiles.colour.output-profile",
        ),
        EnumConfigProperty(
            "rendering_intent",
            RenderingIntent,
            default=DEFAULT_RENDERING_INTENT,
            cli_arg="--colour-transform-intent=",
            envar_name=f"{ENVAR_PREFIX}_COLOUR_TRANSFORM_INTENT",
            json_path="dzi-tiles.colour.colour-transform-intent",
        ),
    ]


class JPEGQuantTable(DescribedEnumMixin, enum.Enum):
    JPEG_ANNEX_K = ("0", "Tables from JPEG Annex K (vips and libjpeg default)")
    FLAT = ("1", "Flat table")
    KODAK_MSSIM = ("2", "Table tuned for MSSIM on Kodak image set")
    IMAGEMAGICK = (
        "3",
        "Table from ImageMagick by N. Robidoux (current mozjpeg default)",
    )
    KODAK_PSNR = ("4", "Table tuned for PSNR-HVS-M on Kodak image set")
    PAPER_5 = (
        "5",
        "Table from Relevance of Human Vision to JPEG-DCT Compression (1992)",
    )
    PAPER_6 = (
        "6",
        "Table from DCTune Perceptual Optimization of Compressed Dental X-Rays (1997)",
    )
    PAPER_7 = (
        "7",
        "Table from A Visual Detection Model for DCT Coefficient Quantization (1993)",
    )
    PAPER_8 = (
        "8",
        "Table from "
        "An Improved Detection Model for DCT Coefficient Quantization (1993)",
    )

    @classmethod
    def for_label(cls, label):
        return super().for_label(str(label) if isinstance(label, int) else label)


class JPEGConfig(Config):
    json_schema = CONFIG_SCHEMA
    property_definitions = [
        IntConfigProperty(
            "quality",
            default=75,
            validate=in_validator(range(0, 101)),
            cli_arg="--jpeg-quality=",
            envar_name=f"{ENVAR_PREFIX}_JPEG_QUALITY",
            json_path="dzi-tiles.jpeg.quality",
        ),
        BoolConfigProperty(
            "optimize_coding",
            default=False,
            cli_arg="--jpeg-optimize-coding",
            envar_name=f"{ENVAR_PREFIX}_JPEG_OPTIMIZE_CODING",
            json_path="dzi-tiles.jpeg.optimize-coding",
        ),
        BoolConfigProperty(
            "subsample",
            default=True,
            cli_arg="--jpeg-subsample",
            envar_name=f"{ENVAR_PREFIX}_JPEG_SUBSAMPLE",
            json_path="dzi-tiles.jpeg.subsample",
        ),
        BoolConfigProperty(
            "trellis_quant",
            default=False,
            cli_arg="--jpeg-trellis-quant",
            envar_name=f"{ENVAR_PREFIX}_JPEG_TRELLIS_QUANT",
            json_path="dzi-tiles.jpeg.trellis-quant",
            requires_mozjpeg=True,
        ),
        BoolConfigProperty(
            "overshoot_deringing",
            default=False,
            cli_arg="--jpeg-overshoot-deringing",
            envar_name=f"{ENVAR_PREFIX}_JPEG_OVERSHOOT_DERINGING",
            json_path="dzi-tiles.jpeg.overshoot-deringing",
            requires_mozjpeg=True,
        ),
        BoolConfigProperty(
            "optimize_scans",
            default=False,
            cli_arg="--jpeg-optimize-scans",
            envar_name=f"{ENVAR_PREFIX}_JPEG_OPTIMIZE_SCANS",
            json_path="dzi-tiles.jpeg.optimize-scans",
            requires_mozjpeg=True,
        ),
        EnumConfigProperty(
            "quant_table",
            JPEGQuantTable,
            default=JPEGQuantTable.JPEG_ANNEX_K,
            parse=simple_parser(JPEGQuantTable.for_label),
            parse_json=delegating_parser(lambda val, next: next(val)),
            cli_arg="--jpeg-quant-table=",
            envar_name=f"{ENVAR_PREFIX}_JPEG_QUANT_TABLE",
            json_path="dzi-tiles.jpeg.quant-table",
            requires_mozjpeg=True,
        ),
    ]

    def get_values_requiring_mozjpeg(self):
        return {
            p: self.non_default_values[p]
            for p in self.properties().values()
            if p.attrs.get("requires_mozjpeg") and p in self.non_default_values
        }


class DZIConfig(Config):
    json_schema = CONFIG_SCHEMA
    property_definitions = [
        IntConfigProperty(
            "tile_size",
            default=254,
            validator=in_validator(range(1, 2 ** 13 + 1)),
            cli_arg="--dzi-tile-size=",
            envar_name=f"{ENVAR_PREFIX}_DZI_TILE_SIZE",
            json_path="dzi-tiles.dzi.tile-size",
        ),
        IntConfigProperty(
            "overlap",
            default=1,
            validator=in_validator(range(0, 2 ** 13 + 1)),
            cli_arg="--dzi-overlap=",
            envar_name=f"{ENVAR_PREFIX}_DZI_OVERLAP",
            json_path="dzi-tiles.dzi.overlap",
        ),
    ]


def validate_dzi_path(path: Union[str, Path]):
    if str(path).endswith("/"):
        raise ConfigValidationError(
            "path ends with a /, but the path should identify a path under a "
            "directory"
        )


class IOConfig(Config):
    json_schema = None
    property_definitions = [
        PathConfigProperty("src_image", cli_arg="<src-image>"),
        PathConfigProperty(
            "dest_dzi",
            cli_arg="<dest-dzi>",
            default_factory=lambda *, config, **_: config.src_image,
            validator=all_validator(
                isinstance_validator((Path, str)), validate_dzi_path
            ),
        ),
    ]


class MetaConfig(EnvironmentConfigMixin, BaseConfig):
    property_definitions = [
        PathConfigProperty("config_file", envar_name="DZI_TILES_CONFIG_FILE",),
        BoolConfigProperty(
            "ignore_missing_config_file",
            default=False,
            envar_name="DZI_TILES_IGNORE_MISSING_CONFIG_FILE",
        ),
    ]


__doc__ = f"""
Generate a tiled image pyramid in DZI format.

Usage:
    dzi-tiles [options] <src-image> [<dest-dzi>]

Info:
    The vips image library is used to efficiently create tiles from a high-res input
    image. You might wonder why this is needs to exist, given that you can run
        $ vips dzsave ...
    and produce DZI tiles. The answer is that it's very easy to shoot yourself in the
    foot doing that.

    You must ensure that your input image is already converted to sRGB, vips won't do
    it for you, even if a colour profile is attached to the input image. Additionally,
    the MozJPEG library can be used for better compression (better quality for a given
    size). However if you use MozJPEG features without them being available to vips
    (perhaps library paths are wrong...) your conversion won't fail, it will succeed
    with a warning on stderr, which will probably go ignored in any kind of automated
    scenario.

Arguments:

    <src-image>
        The path of the image to build DZI tiles from.

    <dest-dzi>
        The path to write the generated DZI data to. This path must be of the form
        [${{path}}/]${{name}}.
          - The tiles are created in the directory  [${{path}}/]${{name}}_files
          - The dzi metadata is created in the file [${{path}}/]${{name}}.dzi

        If not specified, <dest-dzi> defaults to the <src-image> path (which gets
        .dzi and _files appended as described).

Colour space conversion options:

    These options control the colour space handling of the input image. Generally the
    input image needs to be converted to sRGB, because not embedding an ICC profile in
    the tile images saves space, and browsers interpret images without embedded profiles
    as sRGB.

    --input-colour-sources=<src-list>
        Allow the colours of the source image to be determined using the listed methods.
        Generation fails if none of the methods succeed. Methods are:

{indent(ColourSource.describe_members(), by=10)}

        Multiple comma-separated methods can be specified.
        Default: embedded-profile (fail unless the <src-image> contains an ICC profile)

    --external-input-profile=<icc-profile-path>
        The ICC profile to use as the the <src-image>'s profile when converting its
        colours to the output profile. This only has an effect if --colour-sources
        contains 'external-profile' as the first successful source.

    --output-profile=<icc-profile-path>
        The ICC profile to convert the src-image to before splitting into tiles. By
        default the image is converted to sRGB using the sRGB v2 February 2015 from:
            http://www.color.org/srgbprofiles.xalter#v2
        Note that output tiles have no ICC profile attached, so the output images should
        be sRGB, as browsers will treat an untagged image as sRGB.

    --colour-transform-intent=<intent>
        The rendering intent to use when transforming the <src-image>'s colours into the
        output profile. One of {RenderingIntent.available_values_description()}.
        Default: {DEFAULT_RENDERING_INTENT.value}

Output tile encoding options:

    These options control the encoding of the JPEG tiles. They correspond to the
    vips_jpegsave() function:
        https://jcupitt.github.io/libvips/API/current/VipsForeignSave.html#vips-jpegsave

    Some options are marked as requiring mozjpeg. An error is raised if they're enabled
    and mozjpeg is not present.

    --jpeg-quality=<number>
        The JPEG compression level to generate tiles with. Default: 75

    --jpeg-optimize-coding
    --no-jpeg-optimize-coding
        Compute optimal Huffman coding tables. Default: enabled

    --jpeg-subsample
    --no-jpeg-subsample
        If disabled, chrominance subsampling is disabled. This will improve quality at
        the cost of larger file size. Useful for high quality factors.
        Default: enabled

    --jpeg-trellis-quant
    --no-jpeg-trellis-quant
        Apply trellis quantisation to each 8x8 block. Requires mozjpeg.
        Default: disabled

    --jpeg-overshoot-deringing
    --no-jpeg-overshoot-deringing
        Overshoot samples with extreme values. Requires mozjpeg.
        Default: disabled

    --jpeg-optimize-scans
    --no-jpeg-optimize-scans
        Split DCT coefficients into separate scans. Requires mozjpeg.
        Default: disabled

    --jpeg-quant-table=<value>
        Selects the quantization table to use (see vips_jpegsave docs).
        Requires mozjpeg unless set to the default of 0. Available values are:

{indent(JPEGQuantTable.describe_members(), by=10)}

DZI image pyramid options:

    These options control the multi-resolution DZI image pyramid of tiles.

    --dzi-tile-size=<n>
        The size in pixels of tiles (tiles are always square).
        Default: 254

    --dzi-overlap=<n>
        The number of pixels to extend the right and bottom edges of tile images by.
        Default: 1

"""


def pyvips_supports_params():
    """
    Check if the VIPS library pyvips is binding supports the libjpeg param API.

    If not then the MozJPEG options will not work.

    :return: True or False
    """
    # VIPS doesn't seem to provide a way to check if it was compiled with support for
    # JPEG params/MozJPEG. As far as I can see, the only way to check is to try encoding
    # a JPEG using params and see if a warning is logged.

    ignored_param_warning_seen = False

    def filter(record):
        if "ignoring trellis_quant" in record.msg:
            nonlocal ignored_param_warning_seen
            ignored_param_warning_seen = True

        # Suppress all log messages while we're checking for param support
        return False

    img = pyvips.Image.new_from_array([[0.0]])
    logger = pyvips.logger
    try:
        logger.filters.insert(0, filter)
        img.jpegsave_buffer(trellis_quant=True)
    finally:
        logger.removeFilter(filter)

    return not ignored_param_warning_seen


def libjpeg_supports_params():
    """Check if the libjpeg used by this process supports param API.

    This is used by MozJPEG to set additional compression options.

    :return True or False
    """
    try:
        jpeg = CDLL("libjpeg.so")
    except OSError:
        return False

    try:
        jpeg_c_bool_param_supported = c_bool.in_dll(jpeg, "jpeg_c_bool_param_supported")
    except ValueError:
        return False
    return bool(jpeg_c_bool_param_supported)


@dataclass
class DZITilesConfiguration:
    """Aggregate config for dzi-tiles."""

    colour: ColourConfig
    jpeg: JPEGConfig
    dzi: DZIConfig
    io: IOConfig

    @classmethod
    def load(cls):
        meta_config = MetaConfig.from_environ()
        args = docopt(__doc__, version=__version__)

        config_file = None
        if MetaConfig.config_file in meta_config.values:
            config_file = meta_config.values.config_file

            if not config_file.exists():
                if not meta_config.ignore_missing_config_file:
                    raise CommandError(
                        f"config file does not exist: {config_file}\n"
                        "\n"
                        f"To ignore, unset {MetaConfig.config_file.attrs['envar_name']}"
                        " or set "
                        f"{MetaConfig.ignore_missing_config_file.attrs['envar_name']} "
                        "to 'true'."
                    )
                config_file = None

        return DZITilesConfiguration(
            **{
                name: config_cls.from_merged_sources(
                    cli_args=args,
                    toml_file=None if config_cls.json_schema is None else config_file,
                )
                for name, config_cls in cls.CONFIGS.items()
            }
        )

    def __str__(self):
        members = []
        for (name, cls) in self.CONFIGS.items():
            member_prefix = f"{name}={cls.__name__}("
            member_suffix = "),"
            member_values = pformat(
                {prop.name: value for prop, value in getattr(self, name).values.items()}
            )
            member_values = indent(member_values, by=len(member_prefix)).lstrip()
            members.append(f"{member_prefix}{member_values}{member_suffix}")

        members = indent("\n".join(members), by=4)
        return f"{type(self).__name__}(\n{members})"


DZITilesConfiguration.CONFIGS = MappingProxyType(
    {"colour": ColourConfig, "jpeg": JPEGConfig, "dzi": DZIConfig, "io": IOConfig}
)

VIPS_META_ICC_PROFILE = "icc-profile-data"


class DZIGenerationError(Exception):
    pass


class ColourSourceNotAvailable(LookupError):
    pass


class BaseColourSource(ABC):
    @abstractmethod
    def load(self, vips_image: pyvips.Image):
        raise NotImplementedError()


def validate_intent(intent):
    if intent not in VIPS_INTENT_VALUES:
        raise ValueError(f"invalid intent: {intent!r}")


def validate_profile_connection_space(profile_connection_space):
    if profile_connection_space not in VIPS_PCS_VALUES:
        raise ValueError(
            f"invalid profile_connection_space: {profile_connection_space!r}"
        )


def validate_depth(depth):
    if depth not in VIPS_DEPTH_VALUES:
        raise ValueError(f"invalid depth value: {depth!r}")


@dataclass(frozen=True)
class EmbeddedProfileVIPSColourSource(BaseColourSource):
    intent: pyvips.Intent
    profile_connection_space: pyvips.PCS

    def __init__(
        self, *, intent: pyvips.Intent, profile_connection_space: pyvips.PCS = None
    ):
        validate_intent(intent)
        object.__setattr__(self, "intent", intent)

        if profile_connection_space is None:
            profile_connection_space = VIPS_DEFAULT_PCS
        validate_profile_connection_space(profile_connection_space)
        object.__setattr__(self, "profile_connection_space", profile_connection_space)

    def load(self, vips_image: pyvips.Image):
        if VIPS_META_ICC_PROFILE not in vips_image.get_fields():
            raise ColourSourceNotAvailable("image has no embedded ICC profile")

        try:
            return vips_image.icc_import(
                intent=self.intent, embedded=True, pcs=self.profile_connection_space
            )
        except pyvips.Error as e:
            raise DZIGenerationError(f"icc_import() failed: {e}") from e


VIPS_INTENT_VALUES = frozenset(
    [
        pyvips.Intent.RELATIVE,
        pyvips.Intent.SATURATION,
        pyvips.Intent.PERCEPTUAL,
        pyvips.Intent.ABSOLUTE,
    ]
)
VIPS_PCS_VALUES = frozenset([pyvips.PCS.LAB, pyvips.PCS.XYZ])
VIPS_DEFAULT_PCS = pyvips.PCS.LAB
VIPS_DEPTH_VALUES = frozenset([8, 16])
VIPS_DEFAULT_DEPTH = 8


def set_icc_profile(image: pyvips.Image, icc_profile_data: bytes):
    image.set_type(pyvips.GValue.blob_type, VIPS_META_ICC_PROFILE, icc_profile_data)


def get_icc_profile(*, icc_profile, icc_profile_path):
    if icc_profile_path is not None:
        if icc_profile is not None:
            raise ValueError(
                f"icc_profile_path and icc_profile cannot both be specified"
            )
        icc_profile = read_icc_profile(icc_profile_path)
    elif icc_profile is None:
        raise ValueError(f"icc_profile or icc_profile_path must be specified")
    if not (isinstance(icc_profile, bytes) and icc_profile):
        raise ValueError(f"invalid icc_profile: {icc_profile}")
    return icc_profile


@dataclass(frozen=True)
class AssignProfileVIPSColourSource(EmbeddedProfileVIPSColourSource):
    icc_profile: bytes

    def __init__(
        self,
        *,
        intent: pyvips.Intent,
        icc_profile=None,
        icc_profile_path: Union[str, Path] = None,
        profile_connection_space: pyvips.PCS = None,
    ):
        super().__init__(
            intent=intent, profile_connection_space=profile_connection_space
        )
        icc_profile = get_icc_profile(
            icc_profile=icc_profile, icc_profile_path=icc_profile_path
        )
        object.__setattr__(self, "icc_profile", icc_profile)

    def load(self, vips_image: pyvips.Image):
        vips_image = vips_image.copy()
        set_icc_profile(vips_image, self.icc_profile)
        return super().load(vips_image)


class AssumeSRGBColourSource(BaseColourSource):
    def load(self, vips_image: pyvips.Image):
        if not vips_image.interpretation == pyvips.Interpretation.SRGB:
            raise ColourSourceNotAvailable("image interpretation is not sRGB")
        return vips_image


@dataclass(frozen=True)
class LoadColoursImageOperation:
    """
    Convert an image from a non-colour managed representation (e.g. generic RGB) into
    a colour space with defined colours.
    """

    colour_sources: Tuple[ColourSource]

    def __init__(self, colour_sources: Iterable[ColourSource]):
        object.__setattr__(self, "colour_sources", tuple(colour_sources))
        if not colour_sources and all(
            isinstance(cs, ColourSource) for cs in colour_sources
        ):
            raise ValueError(
                f"colour_sources must contain one or more ColourSource objects, got: "
                f"{self.colour_sources}"
            )

    def __call__(self, image: pyvips.Image):
        for colour_source in self.colour_sources:
            try:
                return colour_source.load(image)
            except ColourSourceNotAvailable:
                pass
        raise DZIGenerationError("no ColourSource could handle image")


@dataclass(frozen=True)
class ApplyColourProfileImageOperation:
    """
    Convert the colours of an image to those of an ICC profile.

    The input image must already be in a profile connection space.
    """

    icc_profile: bytes
    intent: pyvips.Intent
    profile_connection_space: pyvips.PCS
    depth: int

    def __init__(
        self,
        *,
        intent: pyvips.Intent,
        icc_profile: bytes = None,
        icc_profile_path: Union[Path, str] = None,
        profile_connection_space: pyvips.PCS = None,
        depth: int = None,
    ):
        object.__setattr__(
            self,
            "icc_profile",
            get_icc_profile(icc_profile=icc_profile, icc_profile_path=icc_profile_path),
        )

        validate_intent(intent)
        object.__setattr__(self, "intent", intent)

        if profile_connection_space is not None:
            validate_profile_connection_space(profile_connection_space)
        object.__setattr__(self, "profile_connection_space", profile_connection_space)

        if depth is None:
            depth = VIPS_DEFAULT_DEPTH
        validate_depth(depth)
        object.__setattr__(self, "depth", depth)

    def ensure_image_in_expected_pcs(self, image):
        expected_pcs = (
            (self.profile_connection_space,)
            if self.profile_connection_space is not None
            else VIPS_PCS_VALUES
        )
        if image.interpretation not in expected_pcs:
            raise ValueError(
                "image is not in a profile connection space: interpretation = "
                f"{image.interpretation}, expected {' or '.join(expected_pcs)}"
            )

    def __call__(self, image: pyvips.Image) -> pyvips.Image:
        image = image.copy()  # Don't change the input image
        self.ensure_image_in_expected_pcs(image)
        set_icc_profile(image, self.icc_profile)
        assert isinstance(image.get(VIPS_META_ICC_PROFILE), bytes)
        pcs_args = (
            {}
            if self.profile_connection_space is None
            else {"pcs": self.profile_connection_space}
        )
        return image.icc_export(intent=self.intent, depth=self.depth, **pcs_args)


def read_icc_profile(path: Union[str, Path]) -> bytes:
    profile = Path(path).read_bytes()
    if len(profile) == 0:
        raise ValueError(f"ICC profile file is empty: {path}")
    return profile


def format_jpeg_encoding_options(config: JPEGConfig) -> str:
    params = [
        (
            "Q",
            str(config.values.quality)
            if config.values.quality != config.default_values.quality
            else None,
        ),
        (("optimize_coding" if config.values.optimize_coding else None),),
        (("no_subsample" if config.values.subsample is False else None),),
        (("trellis_quant" if config.values.trellis_quant else None),),
        (("overshoot_deringing" if config.values.overshoot_deringing else None),),
        (("optimize_scans" if config.values.optimize_scans else None),),
        (
            "quant_table",
            (
                str(config.values.quant_table.label)
                if config.values.quant_table != config.default_values.quant_table
                else None
            ),
        ),
    ]

    return ",".join(
        f"{p[0]}={p[1]}" if len(p) == 2 else p[0] for p in params if p[-1] is not None
    )


def main():
    try:
        run()
    except CommandError as e:
        e.do_exit()


def ensure_mozjpeg_present_if_required(jpeg_config):
    mozjpeg_values = jpeg_config.get_values_requiring_mozjpeg()
    if len(mozjpeg_values) == 0:
        return

    libjpeg_params_supported = libjpeg_supports_params()
    pyvips_params_supported = pyvips_supports_params()
    if libjpeg_params_supported and pyvips_params_supported:
        return

    options_desc = "\n".join(
        f"• {property.name} = {value} "
        f"(default: {property.get_default(config=jpeg_config)})"
        for property, value in mozjpeg_values.items()
    )

    # TODO: should make this part of the JPEG saving API and raise a regular exception
    raise CommandError(
        f"""\
JPEG compression options requiring mozjpeg are enabled, but mozjpeg is not supported:
    - libjpeg supports param API: {libjpeg_params_supported}
    - libvips supports libjpeg params: {pyvips_params_supported}

The following config options are set to non-default values (the
defaults do not require mozjpeg):

{indent(options_desc, by=4)}
"""
    )


def run():
    config = DZITilesConfiguration.load()

    ensure_mozjpeg_present_if_required(config)


if __name__ == "__main__":
    main()
