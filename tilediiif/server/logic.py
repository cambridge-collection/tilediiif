import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union


_image_req_region = re.compile(
    r"""
\A(?:
    # named regions are handled separately
    # Relative percentage coords (can be real numbers)
    (?:(?P<pct>pct:) (\d{1,10}(?:\.\d{0,10})?),
                     (\d{1,10}(?:\.\d{0,10})?),
                     (\d{1,10}(?:\.\d{0,10})?),
                     (\d{1,10}(?:\.\d{0,10})?)) |
    # Regular pixel coords (only integers)
    (?: (\d{1,10}),(\d{1,10}),(\d{1,10}),(\d{1,10}))
)\Z
""",
    re.VERBOSE,
)

_image_req_size = re.compile(
    r"""
\A(?:
    (?:pct: (\d{1,10}(?:\.\d{0,10})?)) |

    # Note that the presence of w and h is validated separately
    (?:(!)? (\d{1,10})?,
            (\d{1,10})?)
)\Z
""",
    re.VERBOSE,
)

_image_req_rotation = re.compile(r"\A(!)?(\d{1,10}(?:\.\d{0,10})?)\Z")
_image_req_token = re.compile(r"\A[a-z]{1,10}\Z")


def _format_normalised_decimal(d):
    formatted = f"{d:.10f}"
    if "." in formatted:
        return formatted.rstrip("0").rstrip(".")
    return formatted


def _ensure_image_info_not_specified(image_info):
    if image_info is not None:
        raise NotImplementedError(
            "request canonicalisation with respect to image info metadata is "
            "not implemented"
        )


class IIIFRegion:
    def canonical(self, *, image_request, image_info=None):
        _ensure_image_info_not_specified(image_info)
        # can't canonicalise a region without image meta context
        return self


@dataclass(frozen=True)
class NamedIIIFRegion(IIIFRegion):
    name: str

    def __str__(self):
        return self.name


NamedIIIFRegion.FULL = NamedIIIFRegion("full")
NamedIIIFRegion.SQUARE = NamedIIIFRegion("square")


@dataclass(frozen=True)
class RelativeIIIFRegion(IIIFRegion):
    x: Decimal
    y: Decimal
    width: Decimal
    height: Decimal

    def __str__(self):
        return (
            f"pct:{_format_normalised_decimal(self.x)},"
            f"{_format_normalised_decimal(self.y)},"
            f"{_format_normalised_decimal(self.width)},"
            f"{_format_normalised_decimal(self.height)}"
        )


@dataclass(frozen=True)
class AbsoluteIIIFRegion(IIIFRegion):
    x: int
    y: int
    width: int
    height: int

    def __str__(self):
        return f"{self.x},{self.y},{self.width},{self.height}"


@dataclass(frozen=True)
class NamedIIIFSize:
    name: str

    def __str__(self):
        return self.name

    def canonical(self, *, image_request, image_info=None):
        _ensure_image_info_not_specified(image_info)
        return self


NamedIIIFSize.FULL = NamedIIIFSize("full")
NamedIIIFSize.MAX = NamedIIIFSize("max")


@dataclass(frozen=True)
class RelativeIIIFSize:
    proportion: Decimal

    def __str__(self):
        return f"pct:{_format_normalised_decimal(self.proportion)}"

    def canonical(self, *, image_request, image_info=None):
        _ensure_image_info_not_specified(image_info)
        # can't canonicalise a relative size without image meta context
        return self


@dataclass(frozen=True)
class IIIFSize:
    width: Optional[int] = None
    height: Optional[int] = None

    def __post_init__(self):
        if self.width is None and self.height is None:
            raise ValueError("no width or height specified")

    def __str__(self):
        return (
            f'{"" if self.width is None else self.width},'
            f'{"" if self.height is None else self.height}'
        )

    def canonical(self, *, image_request, image_info=None):
        _ensure_image_info_not_specified(image_info)

        if self.width is None or self.height is None:
            return self

        if not isinstance(image_request.region, AbsoluteIIIFRegion):
            return self

        # Eliminate the height if it is within the range that could have
        # resulted from scaling and rounding the region uniformly to our
        # width.
        r_width = image_request.region.width
        r_height = image_request.region.height

        max_width_scale = (self.width + 0.5) / r_width
        min_width_scale = (self.width - 0.5) / r_width

        max_height = math.ceil(r_height * max_width_scale)
        min_height = math.floor(r_height * min_width_scale)

        if min_height <= self.height <= max_height:
            return IIIFSize(self.width, height=None)

        return self


@dataclass(frozen=True)
class BestFitIIIFSize:
    width: int
    height: int

    def __str__(self):
        return f"!{self.width},{self.height}"

    def canonical(self, *, image_request, image_info=None):
        _ensure_image_info_not_specified(image_info)
        # can't canonicalise a relative size without image meta context
        return self


@dataclass(frozen=True)
class IIIFRotation:
    mirrored: bool
    degrees: Decimal

    def __str__(self):
        degrees = _format_normalised_decimal(self.degrees)
        return f'{"!" if self.mirrored else ""}{degrees}'

    def canonical(self, *, image_request, image_info=None):
        _ensure_image_info_not_specified(image_info)
        canonicalised_degrees = self.degrees % 360
        if canonicalised_degrees != self.degrees:
            return IIIFRotation(self.mirrored, canonicalised_degrees)
        return self


@dataclass(frozen=True)
class IIIFImageRequest:
    region: Union[NamedIIIFRegion, RelativeIIIFRegion, AbsoluteIIIFRegion]
    size: Union[NamedIIIFSize, RelativeIIIFSize, IIIFSize]
    rotation: IIIFRotation
    quality: str
    format: str

    def __str__(self):
        return (
            f"{self.region}/{self.size}/{self.rotation}/"
            f"{self.quality}.{self.format}"
        )

    def canonical(self, *, image_info=None):
        _ensure_image_info_not_specified(image_info)

        # Currently we don't have access to info.json meta when canonicalising.
        # As a result, some canonicalisation steps are not possible.
        region = self.region.canonical(image_request=self, image_info=image_info)
        size = self.size.canonical(image_request=self, image_info=image_info)
        rotation = self.rotation.canonical(image_request=self, image_info=image_info)
        # quality and format are just themselves

        if region is self.region and size is self.size and rotation is self.rotation:
            return self
        return IIIFImageRequest(
            region=region,
            size=size,
            rotation=rotation,
            quality=self.quality,
            format=self.format,
        )

    @classmethod
    def parse_request(cls, request):
        segments = request.split("/")
        if len(segments) == 4:
            region, size, rotation, name = segments
            name_parts = name.split(".", maxsplit=1)

            if len(name_parts) == 2:
                quality, format = name_parts
                return cls.parse(
                    region=region,
                    size=size,
                    rotation=rotation,
                    quality=quality,
                    format=format,
                )
        raise ValueError(f"invalid request: {request}")

    @classmethod
    def parse(cls, *, region: str, size: str, rotation: str, quality: str, format: str):
        return IIIFImageRequest(
            region=cls.parse_region(region),
            size=cls.parse_size(size),
            rotation=cls.parse_rotation(rotation),
            quality=cls.parse_quality(quality),
            format=cls.parse_format(format),
        )

    @classmethod
    def parse_region(cls, region: str):
        if region == NamedIIIFRegion.FULL.name:
            return NamedIIIFRegion.FULL
        elif region == NamedIIIFRegion.SQUARE.name:
            return NamedIIIFRegion.SQUARE

        region_match = _image_req_region.match(region)
        if not region_match:
            raise ValueError(f"invalid region: {region}")
        pct = bool(region_match.group(1))

        if pct:
            x, y, w, h = (Decimal(x) for x in region_match.groups()[1:5])
            region_cls = RelativeIIIFRegion
        else:
            x, y, w, h = (int(x) for x in region_match.groups()[5:9])
            region_cls = AbsoluteIIIFRegion

        if w == 0 or h == 0:
            raise ValueError(f"region is empty: {region}")

        return region_cls(x, y, w, h)

    @classmethod
    def parse_size(cls, size: str):
        if size == NamedIIIFSize.FULL.name:
            return NamedIIIFSize.FULL
        if size == NamedIIIFSize.MAX.name:
            return NamedIIIFSize.MAX

        size_match = _image_req_size.match(size)
        if not size_match:
            raise ValueError(f"invalid size: {size}")

        pct = size_match.group(1)
        if pct:
            return RelativeIIIFSize(Decimal(pct))

        is_best_fit = size_match.group(2)
        w, h = (None if x is None else int(x) for x in size_match.groups()[2:4])

        undefined_count = (w is None) + (h is None)

        if undefined_count >= (1 if is_best_fit else 2):
            raise ValueError(f"invalid size: {size}")

        if is_best_fit:
            return BestFitIIIFSize(w, h)
        return IIIFSize(w, h)

    @staticmethod
    def parse_rotation(rotation: str):
        match = _image_req_rotation.match(rotation)

        if not match:
            raise ValueError(f"invalid rotation: {rotation}")

        is_mirrored = bool(match.group(1))
        degrees = Decimal(match.group(2))
        return IIIFRotation(is_mirrored, degrees)

    @classmethod
    def parse_quality(cls, quality: str):
        cls._validate_token(quality, "quality")
        return quality

    @classmethod
    def parse_format(cls, format: str):
        cls._validate_token(format, "format")
        return format

    @staticmethod
    def _validate_token(token: str, name):
        if not _image_req_token.match(token):
            raise ValueError(f"invalid {name}: {token}")
