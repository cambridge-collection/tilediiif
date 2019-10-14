"""
Generate IIIF Image API info.json metadata

Usage:
    infojson from-dzi [options] --id=<url> <dzi-file>
    infojson (--help|-h)
    infojson --version

Options:
    --id=<url>
        The public URL of the IIIF image - the @id property of the metadata

    --indent=<n>
        Indent JSON output with <n> spaces
"""
import json
import math
import sys

import docopt
import rfc3986
from rfc3986.exceptions import ValidationError
from rfc3986.validators import Validator

from tilediiif.dzi import DZIError, parse_dzi_file
from tilediiif.version import __version__

# math.log2(2**49) == math.log2(2**49 + 1) so anything above 2**49 won't work
# with the current implementation. Could use decimals instead of float, but I
# don't think this limit is going to constrain anyone any time soon. :)
MAX_IMAGE_DIMENSION = 2**49
MAX_IMAGE_DIMENSION_DESC = '2**49'


def info_json_from_dzi(dzi_data, *, id_url):
    try:
        width = dzi_data['width']
        height = dzi_data['height']
        tile_size = dzi_data['tile_size']
        format = dzi_data['format']
    except KeyError as e:
        raise DZIError(f'dzi_data is missing a value for {e}')

    if format == 'jpeg' or format == 'jpg':
        format = None

    try:
        return iiif_image_metadata_with_pow2_tiles(
            id_url=id_url, width=width, height=height, tile_size=tile_size,
            format=format)
    except ValueError as e:
        raise DZIError(f'\
Unable to create iiif:Image metadata from DZI metadata: {e}') from e


def iiif_image_metadata_with_pow2_tiles(*, id_url, width, height, tile_size,
                                        format=None):
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
    if format is not None and format != 'jpg':
        profile.append({
            'formats': [format]
        })

    return {
        "@context": "http://iiif.io/api/image/2/context.json",
        "@id": id_url,
        "protocol": "http://iiif.io/api/image",
        "profile": profile,
        "width": width,
        "height": height,
        "tiles": [
            {"scaleFactors": power2_image_pyramid_scale_factors(
                width=width, height=height, tile_size=tile_size),
             "width": tile_size}
        ]
    }


def _validate_image_dimensions(width, height, tile_size):
    if not 1 <= width <= MAX_IMAGE_DIMENSION:
        raise ValueError(f'\
width must be >= 1 and <= {MAX_IMAGE_DIMENSION_DESC}: {width}')
    if not 1 <= height <= MAX_IMAGE_DIMENSION:
        raise ValueError(f'\
height must be >= 1 and <= {MAX_IMAGE_DIMENSION_DESC}: {height}')
    if tile_size < 1:
        raise ValueError(f'tile_size is < 1: {tile_size}')


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

    return [2**power for power in range(smallest_layer_power + 1)]


class CLIError(Exception):
    def __init__(self, msg, exit_status=1):
        self.msg = msg
        self.exit_status = exit_status


def main(argv=None):
    args = docopt.docopt(__doc__, argv=argv, version=__version__)
    try:
        run(args)
    except CLIError as e:
        print(f'Error: {e.msg}', file=sys.stderr)
        exit(e.exit_status)


id_validator = (Validator()
                .allow_schemes('http', 'https')
                .forbid_use_of_password()
                .require_presence_of('scheme', 'host', 'path')
                .check_validity_of('scheme', 'host', 'path'))


def _validate_id_url_path(url):
    if url.path.endswith('/'):
        raise ValueError('path ends with a /')


def validate_id_url(identifier):
    url = rfc3986.uri_reference(identifier)
    try:
        id_validator.validate(url)
        _validate_id_url_path(url)
    except (ValueError, ValidationError) as e:
        msg = e.args[0] if isinstance(e, ValidationError) else str(e)
        raise ValueError(f'invalid @id URL: {msg}') from e


def run(args):
    if args['<dzi-file>'] == '-':
        input = sys.stdin.buffer
    else:
        input = open(args['<dzi-file>'], 'rb')

    indent = 2
    if args['--indent'] is not None:
        try:
            indent = int(args['--indent'])
            if indent < 0:
                raise ValueError(f'--indent was negative: {indent}')
        except Exception as e:
            raise CLIError(f'Invalid --indent: {args["--indent"]}') from e

    identifier = args['--id']
    try:
        validate_id_url(identifier)
    except ValueError as e:
        # e's message starts with "invalid @id URL ..."
        raise CLIError(f'--id={identifier!r} is an {e}')
    dzi_meta = parse_dzi_file(input)
    json_meta = info_json_from_dzi(dzi_meta, id_url=identifier)

    dump_args = ({'separators': (',', ':'), 'indent': None} if indent == 0 else
                 {'indent': indent})
    json.dump(json_meta, sys.stdout, **dump_args)
    if indent != 0:
        print(file=sys.stdout)


if __name__ == '__main__':
    main()
