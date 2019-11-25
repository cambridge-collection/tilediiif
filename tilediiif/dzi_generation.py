import enum
import logging
from abc import ABC
from contextlib import contextmanager
from ctypes import CDLL
from dataclasses import dataclass, field
from functools import lru_cache
from logging import LogRecord
from pathlib import Path
from pprint import pformat
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Iterable, List, Tuple, Union

import pyvips
from docopt import docopt

from tilediiif.config import BaseConfig, Config, ConfigProperty, EnvironmentConfigMixin
from tilediiif.config.exceptions import ConfigError, ConfigValidationError
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
    length_validator,
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
                        "enum": [
                            "embedded-profile",
                            "external-profile",
                            "assume-srgb",
                            "unmanaged",
                        ],
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
SRGB_ICC_PROFILE = str(Path(__file__).parent / "data/sRGB2014.icc")
DEFAULT_OUTPUT_PROFILE = SRGB_ICC_PROFILE


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
    UNMANAGED = (
        "unmanaged",
        "Don't colour-manage the image, pass through image data as-is.",
    )


def indent(lines, *, by):
    if isinstance(by, int):
        by = " " * by

    return "\n".join(by + l if l else l for l in lines.split("\n"))


validate_colour_sources = all_validator(
    iterable_validator(element_validator=isinstance_validator(ColourSource)),
    validate_no_duplicates,
    length_validator(at_least=1),
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


def validate_no_vips_options(path: Union[Path, str]):
    if path_has_vips_options(path):
        raise ConfigValidationError(
            "Image filenames cannot end with square brackets because VIPS parses "
            "image load options inside square brackets from filenames"
        )


class IOConfig(Config):
    json_schema = None
    property_definitions = [
        PathConfigProperty(
            "src_image",
            cli_arg="<src-image>",
            validator=all_validator(
                isinstance_validator((Path, str)), validate_no_vips_options
            ),
        ),
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
        The path to write the generated DZI data to.
        This path must be of the form "[${{path}}/]${{name}}":

          • The tiles are created in the directory  "[${{path}}/]${{name}}_files"
          • The dzi metadata is created in the file "[${{path}}/]${{name}}.dzi"

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


@lru_cache(maxsize=1)
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


@dataclass(frozen=True)
class InterceptedLogRecords:
    records: List[LogRecord] = field(default_factory=list)

    def raise_if_records_seen(self):
        """
        Raises a UnexpectedVIPSLogDZIGenerationError any log messages were captured.
        """
        for record in self.records:
            raise UnexpectedVIPSLogDZIGenerationError(
                f"pyvips unexpectedly emitted a log message at {record.levelname} "
                f"level: {record.msg}, aborting DZI generation",
                log_record=record,
            )


class InterceptingHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level=level)
        self.intercepted_records = InterceptedLogRecords()

    def filter(self, record: LogRecord):
        self.intercepted_records.records.append(record)
        return True

    def emit(self, record):
        pass


@contextmanager
def capture_vips_log_messages(level=logging.WARNING):
    """
    A context manager that captures pyvips log messages while active.
    """
    # Note that we can't raise while handling a vips warning log message, as vips logs
    # come from naitive code via cffi, and exceptions raised in cffi callbacks get
    # swallowed. See the test:
    # test_tilediiif.test_dzi_generation.test_exceptions_in_cffi_callbacks_are_swallowed
    interceptor = InterceptingHandler(level=level)
    logger = logging.getLogger("pyvips")
    try:
        logger.addHandler(interceptor)
        yield interceptor.intercepted_records
    finally:
        logger.removeHandler(interceptor)


@lru_cache(maxsize=1)
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
        # MozJPEG contains a function which checks if a named param is supported.
        # Regular libjpeg doesn't.
        jpeg.jpeg_c_bool_param_supported
        return True
    except AttributeError:
        return False


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
VIPS_META_TILEDIIIF_COLOUR_SOURCE = "tilediiif.dzi_generation.ColourSource"


class DZIGenerationError(Exception):
    pass


@dataclass()
class UnexpectedVIPSLogDZIGenerationError(DZIGenerationError):
    message: str
    log_record: LogRecord

    def __str__(self):
        return self.message


class ColourSourceNotAvailable(LookupError):
    pass


def get_image_colour_source(vips_image: pyvips.Image):
    if VIPS_META_TILEDIIIF_COLOUR_SOURCE not in vips_image.get_fields():
        raise KeyError(
            f"Unable to determine colour source: image has no metadata value for "
            f"key {VIPS_META_TILEDIIIF_COLOUR_SOURCE!r}"
        )
    try:
        return ColourSource.for_label(vips_image.get(VIPS_META_TILEDIIIF_COLOUR_SOURCE))
    except ValueError as e:
        raise ValueError(f"Unable to determine colour source: {e}") from e


class BaseColourSource(ABC):
    colour_source_type: ColourSource = None

    def tag_colour_source_type(self, vips_image: pyvips.Image):
        label = self.colour_source_type.label
        vips_image.set_type(
            pyvips.GValue.gstr_type, VIPS_META_TILEDIIIF_COLOUR_SOURCE, label
        )
        return vips_image

    @staticmethod
    def get_image_colour_source(vips_image: pyvips.Image):
        if VIPS_META_TILEDIIIF_COLOUR_SOURCE not in vips_image.get_fields():
            raise ValueError(
                f"Unable to determine colour source: image has no metadata value for "
                f"key {VIPS_META_TILEDIIIF_COLOUR_SOURCE!r}"
            )
        try:
            ColourSource.for_label(vips_image.get(VIPS_META_TILEDIIIF_COLOUR_SOURCE))
        except ValueError as e:
            raise ValueError(f"Unable to determine colour source: {e}") from e

    def load(self, vips_image: pyvips.Image):
        return self.tag_colour_source_type(vips_image.copy())


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
    colour_source_type = ColourSource.EMBEDDED_PROFILE

    def load(self, vips_image: pyvips.Image):
        if VIPS_META_ICC_PROFILE not in vips_image.get_fields():
            raise ColourSourceNotAvailable("image has no embedded ICC profile")
        return super().load(vips_image)


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
                "icc_profile_path and icc_profile cannot both be specified"
            )
        if not isinstance(icc_profile_path, (Path, str)):
            raise TypeError("icc_profile_path must be a Path or str")
        icc_profile = read_icc_profile(str(icc_profile_path))
    elif icc_profile is None:
        raise ValueError("icc_profile or icc_profile_path must be specified")
    if not (isinstance(icc_profile, bytes) and icc_profile):
        raise ValueError(f"invalid icc_profile: {icc_profile}")
    return icc_profile


@dataclass(frozen=True)
class AssignProfileVIPSColourSource(BaseColourSource):
    colour_source_type = ColourSource.EXTERNAL_PROFILE
    icc_profile: bytes

    def __init__(self, *, icc_profile=None, icc_profile_path: Union[str, Path] = None):
        super().__init__()
        icc_profile = get_icc_profile(
            icc_profile=icc_profile, icc_profile_path=icc_profile_path
        )
        object.__setattr__(self, "icc_profile", icc_profile)

    def load(self, vips_image: pyvips.Image):
        image = super().load(vips_image)
        assert image is not vips_image
        set_icc_profile(image, self.icc_profile)
        return image


class AssumeSRGBColourSource(AssignProfileVIPSColourSource):
    colour_source_type = ColourSource.ASSUME_SRGB

    def __init__(self):
        super().__init__(icc_profile_path=SRGB_ICC_PROFILE)

    def load(self, vips_image: pyvips.Image):
        if not vips_image.interpretation == pyvips.Interpretation.SRGB:
            raise ColourSourceNotAvailable("image interpretation is not sRGB")
        return super().load(vips_image)


@dataclass(frozen=True)
class UnmanagedColourSource(BaseColourSource):
    """
    Performs no colour management on the input image, the pixel data is left unchanged.
    """

    colour_source_type = ColourSource.UNMANAGED


@dataclass(frozen=True)
class LoadColoursImageOperation:
    """
    Convert an image from a non-colour managed representation (e.g. generic RGB) into
    a colour space with defined colours.
    """

    colour_sources: Tuple[BaseColourSource]

    def __init__(self, colour_sources: Iterable[BaseColourSource]):
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

    The input image must be in a device format (e.g. RGB) with an ICC profile attached
    as VIPS metadata.
    """

    icc_profile_path: Path
    intent: pyvips.Intent
    profile_connection_space: pyvips.PCS
    depth: int

    def __init__(
        self,
        *,
        intent: pyvips.Intent,
        icc_profile_path: Union[Path, str],
        profile_connection_space: pyvips.PCS = None,
        depth: int = None,
    ):
        object.__setattr__(self, "icc_profile_path", icc_profile_path)

        validate_intent(intent)
        object.__setattr__(self, "intent", intent)

        if profile_connection_space is not None:
            validate_profile_connection_space(profile_connection_space)
        object.__setattr__(self, "profile_connection_space", profile_connection_space)

        if depth is None:
            depth = VIPS_DEFAULT_DEPTH
        validate_depth(depth)
        object.__setattr__(self, "depth", depth)

    @staticmethod
    def ensure_image_has_attached_profile(image: pyvips.Image):
        profile = (
            None
            if VIPS_META_ICC_PROFILE not in image.get_fields()
            else image.get(VIPS_META_ICC_PROFILE)
        )
        if not (isinstance(profile, bytes) and len(profile) > 0):
            raise ValueError(f"image has no ICC profile attached")

    def __call__(self, image: pyvips.Image) -> pyvips.Image:
        self.ensure_image_has_attached_profile(image)
        pcs_args = (
            {}
            if self.profile_connection_space is None
            else {"pcs": self.profile_connection_space}
        )
        try:
            return image.icc_transform(
                str(self.icc_profile_path),
                embedded=True,
                intent=self.intent,
                depth=self.depth,
                **pcs_args,
            )
        except pyvips.Error as e:
            raise DZIGenerationError(f"icc_transform() failed: {e}") from e


@dataclass(frozen=True)
class ColourManagedImageLoader:
    colour_loader: LoadColoursImageOperation
    colour_converter: ApplyColourProfileImageOperation

    @classmethod
    def get_colour_source(
        cls, colour_source_type: ColourSource, config: ColourConfig
    ) -> BaseColourSource:
        if colour_source_type == ColourSource.UNMANAGED:
            return UnmanagedColourSource()
        if colour_source_type == ColourSource.ASSUME_SRGB:
            return AssumeSRGBColourSource()
        if colour_source_type == ColourSource.EMBEDDED_PROFILE:
            return EmbeddedProfileVIPSColourSource()
        if colour_source_type == ColourSource.EXTERNAL_PROFILE:
            if ColourConfig.input_external_profile_path not in config.values:
                raise DZIGenerationError(
                    f"the {ColourSource.EXTERNAL_PROFILE.label!r} colour source is in "
                    f"input_sources but no input_external_profile_path is specified"
                )
            try:
                icc_profile = read_icc_profile(
                    config.values.input_external_profile_path
                )
            except (OSError, ValueError) as e:
                raise DZIGenerationError(
                    f"Unable to read external input ICC profile: {e}"
                ) from e
            return AssignProfileVIPSColourSource(icc_profile=icc_profile)

    @classmethod
    def from_colour_config(cls, config: ColourConfig):
        colour_source_types = config.values.input_sources
        if len(colour_source_types) < 1:
            raise ValueError("no input_sources specified")
        if len(set(colour_source_types)) != len(colour_source_types):
            raise ValueError("input_sources contains a duplicate")

        sources = tuple(
            cls.get_colour_source(cst, config) for cst in colour_source_types
        )
        colour_loader = LoadColoursImageOperation(sources)

        colour_converter = ApplyColourProfileImageOperation(
            intent=config.values.rendering_intent.value,
            icc_profile_path=config.values.output_profile_path,
        )

        return cls(colour_loader=colour_loader, colour_converter=colour_converter)

    def __call__(self, image: pyvips.Image) -> pyvips.Image:
        loaded_image = self.colour_loader(image)

        # Images using the unmanaged colour source are not modified in any way
        if get_image_colour_source(loaded_image) == ColourSource.UNMANAGED:
            return loaded_image

        return self.colour_converter(loaded_image)


@lru_cache(maxsize=4)
def read_icc_profile(path: str) -> bytes:
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


def path_has_vips_options(path: Union[Path, str]) -> bool:
    path = str(path)
    return path.endswith("]") and "[" in path


def save_dzi(
    *,
    src_image: Union[pyvips.Image, Path, str] = None,
    dest_dzi: Union[Path, str] = None,
    io_config: IOConfig = None,
    dzi_config: DZIConfig = None,
    tile_encoding_config: JPEGConfig = None,
    colour_config: ColourConfig = None,
):
    if io_config is not None:
        if src_image is not None:
            raise TypeError("cannot specify src_image and io_config")
        if dest_dzi is not None:
            raise TypeError("cannot specify dest_dzi and io_config")

        src_image = str(io_config.values.src_image)
        dest_dzi = Path(io_config.values.dest_dzi)
    else:
        if src_image is None or dest_dzi is None:
            raise TypeError(
                "src_image and dest_dzi must be specified if io_config isn't"
            )
        if isinstance(src_image, (Path, str)):
            try:
                IOConfig(src_image=src_image)
            except ConfigValidationError as e:
                raise ValueError(f"invalid src_image: {e}")
        try:
            IOConfig(dest_dzi=dest_dzi)
        except ConfigValidationError as e:
            raise ValueError(f"invalid dest_dzi: {e}")
        dest_dzi = Path(dest_dzi)

    if Path(f"{dest_dzi}.dzi").exists():
        raise FileExistsError(f"{dest_dzi}.dzi already exists")
    if Path(f"{dest_dzi}_files").exists():
        raise FileExistsError(f"{dest_dzi}_files already exists")
    if not dest_dzi.parent.is_dir():
        if dest_dzi.parent.exists():
            raise NotADirectoryError(f"{dest_dzi.parent} exists but is not a directory")
        raise FileNotFoundError(
            f"{dest_dzi.parent} does not exist, it must be a directory"
        )

    if isinstance(src_image, (str, Path)):
        try:
            with capture_vips_log_messages() as capture:
                src_image = pyvips.Image.new_from_file(src_image)
            capture.raise_if_records_seen()
        except pyvips.Error as e:
            if f'file "{src_image}" not found' in str(e):
                raise FileNotFoundError(src_image) from e
            raise DZIGenerationError(f"unable to load src image: {e}") from e
    if not isinstance(src_image, pyvips.Image):
        raise TypeError("src_image must be a pyvips.Image, str or Path")

    if dzi_config is None:
        dzi_config = DZIConfig()
    if tile_encoding_config is None:
        tile_encoding_config = JPEGConfig()
    if colour_config is None:
        colour_config = ColourConfig()

    ensure_mozjpeg_present_if_required(tile_encoding_config)
    tile_suffix = f".jpg[{format_jpeg_encoding_options(tile_encoding_config)}]"

    with capture_vips_log_messages() as capture:
        # Transform input image to output colour profile
        colour_loader = ColourManagedImageLoader.from_colour_config(colour_config)
        output_image = colour_loader(src_image)
    capture.raise_if_records_seen()

    try:
        # We need to generate the output in a temporary location, as we must not leave
        # any partial/undefined output if generation fails.
        with TemporaryDirectory(
            prefix="__dzi-tiles-tmp-", suffix=f"__{dest_dzi.name}", dir=dest_dzi.parent
        ) as tmp_dzi_dir:
            tmp_dest_dzi = Path(tmp_dzi_dir) / "tmp"

            # VIPS has a few places where it logs warnings rather than failing if
            # something is wrong. One such case (which we handle explicitly) is MozJPEG
            # encoding params being requested without the library being available. In
            # order to avoid silently ignoring things not working as expected, we
            # intercept any VIPS log messages and raise errors from them, terminating
            # the DZI generation.
            with capture_vips_log_messages() as capture:
                output_image.dzsave(
                    str(tmp_dest_dzi),
                    overlap=dzi_config.values.overlap,
                    tile_size=dzi_config.tile_size,
                    suffix=tile_suffix,
                )
            capture.raise_if_records_seen()

            Path(f"{tmp_dest_dzi}.dzi").replace(f"{dest_dzi}.dzi")
            Path(f"{tmp_dest_dzi}_files").replace(f"{dest_dzi}_files")
    except pyvips.Error as e:
        raise DZIGenerationError(f"dzsave() failed: {str(e).strip()}") from e


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

    raise DZIGenerationError(
        f"""\
JPEG compression options requiring mozjpeg are enabled, but mozjpeg is not supported:

    • libjpeg supports param API: {libjpeg_params_supported}
    • libvips supports libjpeg params: {pyvips_params_supported}

The following config options are set to non-default values (the
defaults do not require mozjpeg):

{indent(options_desc, by=4)}
"""
    )


def main():
    try:
        run()
    except CommandError as e:
        e.do_exit()


def run():
    try:
        config = DZITilesConfiguration.load()
    except ConfigError as e:
        raise CommandError(f"{e}") from e

    try:
        save_dzi(
            io_config=config.io,
            dzi_config=config.dzi,
            tile_encoding_config=config.jpeg,
            colour_config=config.colour,
        )
    except DZIGenerationError as e:
        raise CommandError(f"DZI generation failed: {e}") from e


if __name__ == "__main__":
    main()
