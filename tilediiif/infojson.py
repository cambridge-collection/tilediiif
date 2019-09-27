"""
Generate IIIF Image API info.json metadata

Usage:
    infojson from-dzi [options] <dzi-file>
    infojson (--help|-h)
    infojson --version

Options:
    --indent=<n>
        Indent JSON output with <n> spaces
"""
import json
import math
import sys

import docopt

from tilediiif.dzi import DZIError, parse_dzi_file
from .version import __version__

# math.log2(2**49) == math.log2(2**49 + 1) so anything above 2**49 won't work
# with the current implementation. Could use decimals instead of float, but I
# don't think this limit is going to constrain anyone any time soon. :)
MAX_IMAGE_DIMENSION = 2**49
MAX_IMAGE_DIMENSION_DESC = '2**49'


def info_json_from_dzi(dzi_data):
    try:
        width = dzi_data['width']
        height = dzi_data['height']
        tile_size = dzi_data['tile_size']
    except KeyError as e:
        raise DZIError(f'dzi_data is missing a value for {e}')

    try:
        return iiif_image_metadata_with_pow2_tiles(width=width, height=height,
                                                   tile_size=tile_size)
    except ValueError as e:
        raise DZIError(f'\
Unable to create iiif:Image metadata from DZI metadata: {e}') from e


def iiif_image_metadata_with_pow2_tiles(*, width, height, tile_size):
    """
    Create iiif:Image metadata (e.g. contents of an info.json file)

    The image has tiles which halve in resolution at each level.

    :param width: Width of the image
    :param height: Height of the image
    :param tile_size: The width and height of the (square) tiles
    :return: The iiif:Image metadata as a dict
    """
    if not 1 <= width <= MAX_IMAGE_DIMENSION:
        raise ValueError(f'\
width must be >= 1 and <= {MAX_IMAGE_DIMENSION_DESC}: {width}')
    if not 1 <= height <= MAX_IMAGE_DIMENSION:
        raise ValueError(f'\
height must be >= 1 and <= {MAX_IMAGE_DIMENSION_DESC}: {height}')
    if tile_size < 1:
        raise ValueError(f'tile_size is < 1: {tile_size}')

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
    # However our layers are always half the size of the last, so the smallest
    # layer is the image / n where n is the next power of
    # 2 greater than the ideal scale factor. e.g. if the ideal scale was 3.5
    # then 4 would be the scale factor of the smallest layer.
    smallest_layer_power = math.ceil(math.log2(ideal_smallest_scale_factor))

    return {
        "@context": "http://iiif.io/api/image/2/context.json",
        "@id": "https://images.cudl.lib.cam.ac.uk/iiif/MS-ADD-00269-000-01075",
        "protocol": "http://iiif.io/api/image",
        "profile": ["http://iiif.io/api/image/2/level0.json"],
        "width": width,
        "height": height,
        "tiles": [
            {"scaleFactors": [2**power for power in
                              range(smallest_layer_power + 1)],
             "width": tile_size}
        ]
    }


class CLIError(Exception):
    def __init__(self, msg, exit_status=1):
        self.msg = msg
        self.exit_status = exit_status


def main(argv=None):
    try:
        _main(sys.argv if argv is None else argv)
    except CLIError as e:
        print(f'Error: {e.msg}', file=sys.stderr)
        exit(e.exit_status)


def _main(argv):
    args = docopt.docopt(__doc__, version=__version__)

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

    dzi_meta = parse_dzi_file(input)
    json_meta = info_json_from_dzi(dzi_meta)

    dump_args = ({'separators': (',', ':'), 'indent': None} if indent == 0 else
                 {'indent': indent})
    json.dump(json_meta, sys.stdout, **dump_args)
    if indent != 0:
        print(file=sys.stdout)


if __name__ == '__main__':
    main()
