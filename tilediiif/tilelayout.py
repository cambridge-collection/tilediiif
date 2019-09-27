"""
Lay out pyramid image tiles to back a static-file IIIF Image server

Usage:
    iiif-tiles from-dzi [options] <dzi-file> <dest-directory>
    iiif-tiles (-h|--help)
    iiif-tiles --version

Info:
A server implementing the IIIF Image API can serve tiles by mapping the request
URL to a files on disk.

For example, the following is a IIIF Image API URL requesting a 256x256 tile
at the top-left corner of an image at 1:1 scale:
    https://example.com/iiif/my-photo/0,0,256,256/256,256/0/default.jpg

With some simple URL rewriting, the request can be mapped to a file path:
    /var/iiif-images/my-photo/0,0,256,256-256,256-0-default.jpg

This file in turn can be obtained from a DZI tile layer pyramid:
    /var/iiif-images/my-photo.dzi
    /var/iiif-images/my-photo_files/14/0_0.jpg  # assuming layer 14 is 1:1

This program can lay out image tiles with paths allowing them to be addressed
in this way by a IIIF Image server.

Options:

"""
import math

from tilediiif.validation import require_positive_non_zero_int


def get_layer_tiles(*, width, height, tile_size, scale_factor):
    """
    Generate the tiles that comprise a layer in a scaled image.

    For example, a 1000x600 pixel image with a scale factor of 2 and tile size
    250 has 2x2 tiles. The scaled image is 500x300, so there are 2 complete
    horizontal tiles, and the tiles of the bottom row are only 50 pixels high:
        >>> from pprint import pprint
        >>> tiles = get_layer_tiles(width=1000, height=600,
        ...                         tile_size=250, scale_factor=2)
        >>> pprint(list(tiles))
        [{'dst': {'height': 250, 'width': 250, 'x': 0, 'y': 0},
          'index': {'x': 0, 'y': 0},
          'scale_factor': 2,
          'src': {'height': 500, 'width': 500, 'x': 0, 'y': 0}},
         {'dst': {'height': 250, 'width': 250, 'x': 250, 'y': 0},
          'index': {'x': 1, 'y': 0},
          'scale_factor': 2,
          'src': {'height': 500, 'width': 500, 'x': 500, 'y': 0}},
         {'dst': {'height': 50, 'width': 250, 'x': 0, 'y': 250},
          'index': {'x': 0, 'y': 1},
          'scale_factor': 2,
          'src': {'height': 100, 'width': 500, 'x': 0, 'y': 500}},
         {'dst': {'height': 50, 'width': 250, 'x': 250, 'y': 250},
          'index': {'x': 1, 'y': 1},
          'scale_factor': 2,
          'src': {'height': 100, 'width': 500, 'x': 500, 'y': 500}}]

    :param width: The width of the image at 1:1 scale
    :param height: The height of the image at 1:1 scale
    :param tile_size: The width and height of the (square) tiles.
    :param scale_factor: The factor to reduce the 1:1 size by
    :return: an iterable producing tile objects.
    """
    require_positive_non_zero_int(
        width=width, height=height, tile_size=tile_size,
        scale_factor=scale_factor)

    tile_src_area = tile_size * scale_factor
    tiles_x = width // tile_src_area
    tiles_y = height // tile_src_area
    trailing_x = width % tile_src_area
    trailing_y = height % tile_src_area

    for y in range(tiles_y + 1):
        for x in range(tiles_x + 1):
            src_tile_width = tile_src_area
            if x == tiles_x:
                if trailing_x == 0:
                    continue
                src_tile_width = trailing_x

            src_tile_height = tile_src_area
            if y == tiles_y:
                if trailing_y == 0:
                    continue
                src_tile_height = trailing_y

            yield {
                'scale_factor': scale_factor,
                'index': {'x': x, 'y': y},
                'src': {'x': x * tile_src_area, 'y': y * tile_src_area,
                        'width': src_tile_width, 'height': src_tile_height},
                'dst': {'x': x * tile_size, 'y': y * tile_size,
                        'width': math.ceil(src_tile_width / scale_factor),
                        'height': math.ceil(src_tile_height / scale_factor)}
            }
