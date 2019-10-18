import json
import math
import re
import sys
from pathlib import Path

import docopt
import rfc3986
from rfc3986.exceptions import ValidationError
from rfc3986.validators import Validator

from tilediiif.dzi import DZIError, parse_dzi_file
from tilediiif.filesystem import ensure_sub_directories_exist
from tilediiif.templates import get_info_json_path_renderer, TemplateError
from tilediiif.version import __version__

# math.log2(2**49) == math.log2(2**49 + 1) so anything above 2**49 won't work
# with the current implementation. Could use decimals instead of float, but I
# don't think this limit is going to constrain anyone any time soon. :)
MAX_IMAGE_DIMENSION = 2 ** 49
MAX_IMAGE_DIMENSION_DESC = "2**49"

DEFAULT_DATA_PATH = "."
DEFAULT_ID_BASE_URL = "https://iiif.example.com/image/"
DEFAULT_INDENT = 2
DEFAULT_PATH_TEMPLATE = "{identifier}/info.json"


__doc__ = f"""
Generate IIIF Image API info.json metadata

Usage:
    infojson from-dzi [options] [--stdout] <dzi-file>
    infojson (--help|-h)
    infojson --version

Options:
    --id-base-url=<url>
        The base public URL of the IIIF image. The --id is resolved onto this
        URL to form the image's @id URL.
        Default: {DEFAULT_ID_BASE_URL!r}

    --id=<identifier>
        The IIIF Image API identifier for the image.
        Default: the <dzi-file>'s name.

    --data-path=<data-dir>
        The data directory to create content under. Default: {DEFAULT_DATA_PATH!r}

    --path-template=<template>
        The template defining the relative path under --data-path at which to
        write the output. Available placeholders:
          - {{identifier}}       - The IIIF Image API Identifier value
          - {{identifier-shard}} - A hash-based prefix based on the identifier;
                                 used to evenly distribute image content over
                                 multiple subdirectories.
        Default: {DEFAULT_PATH_TEMPLATE!r}

    --stdout
        Write the output to stdout instead of under --data-path

    --indent=<n>
        Indent JSON output with <n> spaces. Default: {DEFAULT_INDENT}
"""  # noqa: E501


def info_json_from_dzi(dzi_data, *, id_url):
    try:
        width = dzi_data["width"]
        height = dzi_data["height"]
        tile_size = dzi_data["tile_size"]
        format = dzi_data["format"]
    except KeyError as e:
        raise DZIError(f"dzi_data is missing a value for {e}")

    if format == "jpeg" or format == "jpg":
        format = None

    try:
        return iiif_image_metadata_with_pow2_tiles(
            id_url=id_url,
            width=width,
            height=height,
            tile_size=tile_size,
            format=format,
        )
    except ValueError as e:
        raise DZIError(
            f"\
Unable to create iiif:Image metadata from DZI metadata: {e}"
        ) from e


def iiif_image_metadata_with_pow2_tiles(
    *, id_url, width, height, tile_size, format=None
):
    """
    Create iiif:Image metadata (e.g. contents of an info.json file)

    The image has tiles which halve in resolution at each level.

    :param width: Width of the image
    :param height: Height of the image
    :param tile_size: The width and height of the (square) tiles
    :return: The iiif:Image metadata as a dict
    """
    _validate_image_dimensions(width, height, tile_size)
    validate_id_url(id_url)

    profile = ["http://iiif.io/api/image/2/level0.json"]

    # jpg is the profile level 0 default and required format
    if format is not None and format != "jpg":
        profile.append({"formats": [format]})

    return {
        "@context": "http://iiif.io/api/image/2/context.json",
        "@id": id_url,
        "protocol": "http://iiif.io/api/image",
        "profile": profile,
        "width": width,
        "height": height,
        "tiles": [
            {
                "scaleFactors": power2_image_pyramid_scale_factors(
                    width=width, height=height, tile_size=tile_size
                ),
                "width": tile_size,
            }
        ],
    }


def _validate_image_dimensions(width, height, tile_size):
    if not 1 <= width <= MAX_IMAGE_DIMENSION:
        raise ValueError(
            f"\
width must be >= 1 and <= {MAX_IMAGE_DIMENSION_DESC}: {width}"
        )
    if not 1 <= height <= MAX_IMAGE_DIMENSION:
        raise ValueError(
            f"\
height must be >= 1 and <= {MAX_IMAGE_DIMENSION_DESC}: {height}"
        )
    if tile_size < 1:
        raise ValueError(f"tile_size is < 1: {tile_size}")


def power2_image_pyramid_scale_factors(*, width, height, tile_size):
    """
    Get a list of the scale factors in an image pyramid with power 2.

    Each scale factor is a power of 2 (1, 2, 4, 8..) which the width and height
    will be divided by at the layer.

    - Each layer is 2x as big/small as its neighbor.
    - Each layer, numbered from 0 upwards has a width and height of 2**n
      - e.g. layer 8 is 256,256

    - The smallest layer is the smallest 2**n which can contain a single tile.
    - The largest layer is the smallest 2**n which can contain the
      width x height.

    :param width: Width of the image
    :param height: Height of the image
    :param tile_size: The width and height of the (square) tiles
    :return: The scale factors required to represent the tiled image pyramid.
    """
    _validate_image_dimensions(width, height, tile_size)

    # Note:
    # - each level is half the size of the next larger level
    # - The min and max levels are the smallest power of 2 that can contain the
    # entire image:
    #   - the max level needs to contain the entire image at 1:1, so the max
    #     area of the level needs to be >= the image size
    #   - min level needs to contain the entire image within one tile, so the
    #     size of the image at the scale of the level needs to be <= the tile
    #     size

    size = max(width, height)
    # ideally the smallest layer would be the scale factor that makes the
    # image = the tile size. If the image is smaller than the tile size, then
    # we wouldn't scale the image, so 1 is the smallest scale factor.
    ideal_smallest_scale_factor = max(1, size / tile_size)
    # However our scales are always powers of 2 (half the size of the last), so
    # the smallest layer is the image / n where n is the next power of
    # 2 greater than the ideal scale factor. e.g. if the ideal scale was 3.5
    # then 4 would be the scale factor of the smallest layer.
    smallest_layer_power = math.ceil(math.log2(ideal_smallest_scale_factor))

    return [2 ** power for power in range(smallest_layer_power + 1)]


id_validator = (
    Validator()
    .allow_schemes("http", "https")
    .forbid_use_of_password()
    .require_presence_of("scheme", "host", "path")
    .check_validity_of("scheme", "host", "path")
)

id_base_validator = (
    Validator()
    .allow_schemes("http", "https")
    .forbid_use_of_password()
    .require_presence_of("scheme", "host")
    .check_validity_of("scheme", "host", "path")
)


def _validate_id_url_path(url):
    if url.path.endswith("/"):
        raise ValueError("path ends with a /")


def _get_error_message(e):
    return e.args[0] if isinstance(e, ValidationError) else str(e)


def validate_id_url(url):
    if not isinstance(url, rfc3986.URIReference):
        url = rfc3986.uri_reference(url)
    try:
        id_validator.validate(url)
        _validate_id_url_path(url)
    except (ValueError, ValidationError) as e:
        msg = e.args[0] if isinstance(e, ValidationError) else str(e)
        raise ValueError(f"invalid @id URL {url.unsplit()!r}: {msg}") from e


def _is_relative_uri_path(uri):
    if not all(x is None for x in (uri.scheme, uri.authority, uri.query, uri.fragment)):
        return False

    return uri.path and not uri.path.startswith("/")


def get_id_url(id_base_url, id):
    relative_id = rfc3986.uri_reference(id)
    if not _is_relative_uri_path(relative_id):
        raise CLIError(f"identifier is not a relative URL path: {id!r}")

    base = rfc3986.uri_reference(id_base_url)
    if not base.is_absolute():
        raise CLIError(f"invalid --id-base-url {id_base_url!r}: url is not absolute")

    id_url = relative_id.resolve_with(base)
    try:
        validate_id_url(id_url)
    except ValueError as e:
        raise CLIError(str(e)) from e
    return id_url.unsplit()


def _output_to_stdout(info_json_content: bytes, identifier: str):
    sys.stdout.buffer.write(info_json_content)


def _create_templated_file_output_method(data_path: Path, path_template: str):
    try:
        get_path = get_info_json_path_renderer(data_path, path_template)
    except TemplateError as e:
        raise CLIError(f"Invalid --path-template: {e}")

    def _output_to_file(info_json_content: bytes, identifier: str):
        path = get_path(identifier)
        assert data_path in path.parents
        ensure_sub_directories_exist(data_path, path.relative_to(data_path))
        try:
            with open(path, "wb") as f:
                f.write(info_json_content)
        except OSError as e:
            raise CLIError(f"failed to write output to {path} because {e}") from e

    return _output_to_file


def _get_output_method(args):
    if args["--stdout"]:
        return _output_to_stdout

    return _create_templated_file_output_method(
        Path(args["--data-path"]), args["--path-template"]
    )


def _json_serialise(obj, indent) -> bytes:
    dump_args = (
        {"separators": (",", ":"), "indent": None}
        if indent == 0
        else {"indent": indent}
    )
    output = json.dumps(obj, **dump_args)
    if indent != 0:
        output += "\n"
    return output.encode("utf-8")


def _get_default_id(dzi_path):
    match = re.search(r"(?:\A|/)([^/]+)\.dzi\Z", dzi_path)
    if match:
        return match.group(1)

    if dzi_path == "-":
        issue = "DZI is read from stdin"
    else:
        issue = f"{str(dzi_path)!r} is not like *.dzi"

    raise CLIError(
        f"no --id is specified so --id is derived from <dzi-file>, "
        f"but {issue}; nothing to generate @id attribute from"
    )


class CLIError(Exception):
    def __init__(self, msg, exit_status=1):
        self.msg = msg
        self.exit_status = exit_status


def main(argv=None):
    args = docopt.docopt(__doc__, argv=argv, version=__version__)
    # Strip unspecified arguments and apply defaults
    args = {
        "--data-path": DEFAULT_DATA_PATH,
        "--id-base-url": DEFAULT_ID_BASE_URL,
        "--indent": DEFAULT_INDENT,
        "--path-template": DEFAULT_PATH_TEMPLATE,
        **{k: v for k, v in args.items() if v is not None},
    }
    try:
        run(args)
    except CLIError as e:
        print(f"Error: {e.msg}", file=sys.stderr)
        exit(e.exit_status)


def run(args):
    write_output = _get_output_method(args)

    indent = DEFAULT_INDENT
    if "--indent" in args:
        try:
            indent = int(args["--indent"])
            if indent < 0:
                raise ValueError(f"--indent was negative: {indent}")
        except Exception as e:
            raise CLIError(f'Invalid --indent: {args["--indent"]}') from e

    identifier = args["--id"] if "--id" in args else _get_default_id(args["<dzi-file>"])
    id_base_url = args["--id-base-url"]
    id_url = get_id_url(id_base_url, identifier)

    if args["<dzi-file>"] == "-":
        input = sys.stdin.buffer
    else:
        input = open(args["<dzi-file>"], "rb")

    dzi_meta = parse_dzi_file(input)
    json_meta = info_json_from_dzi(dzi_meta, id_url=id_url)
    write_output(_json_serialise(json_meta, indent), identifier)


if __name__ == "__main__":
    main()
