import math
import os
import re
import shutil
import sys
from functools import lru_cache, partial, reduce
from pathlib import Path
from typing import Dict

from docopt import docopt

from tilediiif.dzi import get_dzi_tile_path, parse_dzi_file
from tilediiif.infojson import iiif_image_metadata_with_pow2_tiles
from tilediiif.validation import require_positive_non_zero_int
from tilediiif.version import __version__

DEFAULT_FILE_METHOD = 'hardlink'
DEFAULT_FILE_PATH_TEMPLATE = '{region}-{size.w},-{rotation}-{quality}.{format}'


def get_usage():
    file_methods = ', '.join(sorted(create_file_methods.keys()))

    return f"""\
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

Arguments:
    <dzi-file>
        The DZI file to map to a IIIF Image API layout. The file must be
        located alongside a directory containing the DZI tiles. E.g. for a DZI
        file at foo/bar.dzi a directory foo/bar_files must exist.

    <dest-directory>
        The base path to create the layout under. A directory will be created
        at this path. The command will fail if the path exists, unless
        --allow-existing-dest is used.

Options:
    --tile-path-template=<template>
        Specify how the IIIF tiles will be named. The template is a relative
        path string with placeholders for coordinates, sizes, etc. Available
        placeholders are named as specified in the spec:
        https://iiif.io/api/image/2.1/#image-request-parameters
          - {{region}} - The whole source region as x,y,w,h
          - {{region.x}} {{region.y}} {{region.w}} {{region.h}} -
                Individual region components.
          - {{size}} - The size as w,h
          - {{size.w}} {{size.h}} - Individual size components
          - {{rotation}} {{quality}} {{format}}

        The default template is:
            {DEFAULT_FILE_PATH_TEMPLATE!r}

        The template may contain subdirectories, but may not use ".." path
        segments.

    --file-creation-method=<method>
        How layout files should be created; method must be one of
        {file_methods}. Default: {DEFAULT_FILE_METHOD}

    --allow-existing-dest
        Allow creating layout files in an existing destination directory. This
        risks overwriting existing files, and the possibility of failing if a
        directory that would be created already exists as a file, or similar.
"""


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


class TemplateError(ValueError):
    pass


template_chunk = re.compile(r'''
# Placeholders with invalid contents or not terminated
(?P<invalid_placeholder>{(?![\w.-]+}))|
# Valid placeholders
{(?P<placeholder>[\w.-]+)}|
# Escape sequences
(?P<escape>\\[{\\])|
# Invalid escape sequences
(?P<invalid_escape>\\.)|
# Unescaped literal text
(?P<unescaped>[^{\\]+)
''', re.VERBOSE)


def render_placeholder(name, bindings):
    value = bindings.get(name)
    if not isinstance(value, str):
        raise TemplateError(f'\
No value for {name!r} exists in bound values: {bindings}')
    return value


def render_literal(value, _):
    return value


class Template:
    def __init__(self, chunks, var_names):
        self.chunks = tuple(chunks)
        self.var_names = frozenset(var_names)

    def render(self, bindings: Dict[str, str]):
        if bindings.keys() < self.var_names:
            missing = ', '.join(f'{v!r}'
                                for v in self.var_names - bindings.keys())
            raise TemplateError(f'\
Variables for placeholders {missing} \
are missing from bound values: {bindings}')

        return ''.join(c(bindings) for c in self.chunks)


def parse_template(template):
    def append_segment(segments, offset=None, invalid_placeholder=None,
                       placeholder=None, escape=None, invalid_escape=None,
                       unescaped=None):
        assert sum(bool(x) for x in [invalid_placeholder, placeholder, escape,
                                     invalid_escape, unescaped]) == 1

        if invalid_placeholder or invalid_escape:
            thing = 'placeholder' if invalid_placeholder else 'escape sequence'
            raise TemplateError(f'''\
Invalid {thing} at offset {offset}:
    {template}
    {' ' * offset}^''')
        elif placeholder:
            return segments + (('placeholder', placeholder),)

        literal = unescaped if unescaped else escape[1]
        # Merge consecutive literals
        if segments and segments[-1][0] == 'literal':
            return segments[:-1] + (('literal', segments[-1][1] + literal),)
        return segments + (('literal', literal),)

    segments = reduce(
        lambda segments, match: append_segment(segments, offset=match.start(),
                                               **match.groupdict()),
        template_chunk.finditer(template), ())

    chunks = (partial(render_placeholder, value) if type == 'placeholder' else
              partial(render_literal, value) for (type, value) in segments)
    var_names = (value for (type, value) in segments if type == 'placeholder')
    return Template(chunks, var_names)


def get_template_bindings(tile, *, format='jpg', rotation=0,
                          quality='default'):
    """Generate a bindings dict for an image tile"""

    return {
        'region.x': str(tile['src']['x']),
        'region.y': str(tile['src']['y']),
        'region.w': str(tile['src']['width']),
        'region.h': str(tile['src']['height']),
        'region': (f"{tile['src']['x']},{tile['src']['y']},"
                   f"{tile['src']['width']},{tile['src']['height']}"),
        'size': f'''{tile['dst']['width']},{tile['dst']['height']}''',
        'size.w': str(tile['dst']['width']),
        'size.h': str(tile['dst']['height']),
        'rotation': str(rotation),
        'quality': str(quality),
        'format': str(format)
    }


class InvalidPath(ValueError):
    pass


def get_templated_dest_path(template: Template, tile, *,
                            bindings_for_tile=get_template_bindings) -> Path:
    path = Path(template.render(bindings_for_tile(tile)))

    if not path.parts:
        raise InvalidPath(f'generated path is empty')
    if path.is_absolute():
        raise InvalidPath(f'generated path is not relative: {path}')
    if '..' in path.parts:
        raise InvalidPath(f'generated path contains a ".." segment: {path}')

    return path


def create_file_via_copy(src: Path, dest: Path):
    return shutil.copyfile(str(src), str(dest), follow_symlinks=True)


def create_file_via_hardlink(src: Path, dest: Path):
    os.link(str(src), str(dest))


def create_file_via_symlink(src: Path, dest: Path):
    os.symlink(str(src), str(dest))


create_file_methods = {
    'copy': create_file_via_copy,
    'hardlink': create_file_via_hardlink,
    'symlink': create_file_via_symlink
}


# assumption: dirs we create are not removed during our runtime, hence
# memoisation is safe.
@lru_cache()
def _ensure_dir_exists(path: Path):
    path.mkdir(exist_ok=True)


def create_tile_layout(*, tiles, get_tile_path, get_dest_path, create_file,
                       target_directory: Path):
    """
    Lay out a set of tiles in a target directory for use by a static-file-
    backed IIIF Image server.

    :param tiles: A sequence of tile objects, as returned by get_layer_tiles()
    :param get_tile_path: A function which, when given a tile object, returns a
                          Path object pointing to a file containing a tile's
                          image.
    :param get_dest_path: A function which, when given a tile object, returns
                          the relative path under the target directory that the
                          tile should be exist at.
    :param create_file: A function which, when given a source and destination
                        path, will create a file at the destination path (e.g.
                        via copying, symlink, hardlink...). Any directories in
                        the destination path will already exist.
    :param target_directory: The directory which the layout files will be
                             created inside.
    """
    for tile in tiles:
        tile_path = get_tile_path(tile)
        relative_dest_path = get_dest_path(tile)
        if '..' in relative_dest_path.parts:
            raise ValueError(f'\
get_dest_path returned a path with a ".." segment: {relative_dest_path}')
        if not relative_dest_path.parts:
            raise ValueError(f'get_dest_path returned an empty path')
        if relative_dest_path.is_absolute():
            raise ValueError(f'\
get_dest_path returned an absolute path: {relative_dest_path}')

        for dir in reversed(list(relative_dest_path.parents)[:-1]):
            _ensure_dir_exists(target_directory / dir)

        final_dest_path = target_directory / relative_dest_path
        create_file(tile_path, final_dest_path)


def create_dzi_tile_layout(*, dzi_path, dzi_meta, get_dest_path, create_file,
                           target_directory):
    info_json = iiif_image_metadata_with_pow2_tiles(
        width=dzi_meta['width'], height=dzi_meta['height'],
        tile_size=dzi_meta['tile_size'])

    # image metadata created from a DZI always has just one set of tiles
    assert isinstance(info_json.get('tiles'), list)
    assert len(info_json['tiles']) == 1
    tile_spec, = info_json['tiles']
    assert tile_spec['width'] == dzi_meta['tile_size']
    assert tile_spec.get('height') in (None, dzi_meta['tile_size'])

    all_tiles = (
        tile
        for scale_factor in tile_spec['scaleFactors']
        for tile in get_layer_tiles(
            width=info_json['width'], height=info_json['height'],
            tile_size=tile_spec['width'], scale_factor=scale_factor)
    )

    if dzi_path.name[-4:].lower() != '.dzi':
        raise ValueError('dzi_path does not end in .dzi: {dzi_path}')

    dzi_tiles_path = dzi_path.parent / f'{dzi_path.name[:-4]}_files'
    get_tile_path = partial(get_dzi_tile_path, dzi_files_path=dzi_tiles_path,
                            dzi_meta=dzi_meta)

    create_tile_layout(tiles=all_tiles, get_tile_path=get_tile_path,
                       get_dest_path=get_dest_path, create_file=create_file,
                       target_directory=target_directory)


def run(args):
    # Drop None-valued args to make default handling less verbose
    args = {k: v for (k, v) in args.items() if v is not None}
    dzi_path = Path(args['<dzi-file>'])
    dest_dir = Path(args['<dest-directory>'])
    tile_path_template = args.get('--tile-path-template',
                                  DEFAULT_FILE_PATH_TEMPLATE)
    allow_existing_dest = bool(args.get('--allow-existing-dest'))
    file_creation_method_name = args.get('--file-creation-method',
                                         DEFAULT_FILE_METHOD)
    try:
        create_file = create_file_methods[file_creation_method_name]
    except KeyError:
        raise CommandError(f'\
Invalid --file-creation-method {file_creation_method_name!r}. \
Possible values are {", ".join(sorted(create_file_methods.keys()))}')

    try:
        template = parse_template(tile_path_template)
    except ValueError as e:
        raise CommandError(f'invalid --tile-path-template: {e}') from e

    if dest_dir.exists():
        if not dest_dir.is_dir():
            raise CommandError('<dest-directory> exists and is not a '
                               'directory')

        if not allow_existing_dest:
            raise CommandError(f'<dest-directory> exists, refusing to write '
                               f'into it without --allow-existing-dest')

    if not dzi_path.name[-4:].lower() == '.dzi':
        raise CommandError(f'<dzi_file> {dzi_path} does not have a .dzi '
                           f'extension')
    if not dzi_path.is_file():
        if dzi_path.exists():
            raise CommandError(f'<dzi-file> {dzi_path} exists but is not a '
                               f'regular file')
        else:
            raise CommandError(f'<dzi-file> {dzi_path} does not exist')

    try:
        with open(dzi_path, 'rb') as f:
            dzi_meta = parse_dzi_file(f)
    except Exception as e:
        raise CommandError(f'Unable to parse <dzi-file> {dzi_path} : {e}'
                           ) from e

    # Create output paths by rendering the provided template.
    get_dest_path = partial(
        get_templated_dest_path, template,
        bindings_for_tile=partial(get_template_bindings,
                                  format=dzi_meta['format']))

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise CommandError(f'Unable to create <dest-directory> {dest_dir} '
                           f'because: {e}') from e

    create_dzi_tile_layout(
        dzi_path=dzi_path, dzi_meta=dzi_meta, get_dest_path=get_dest_path,
        create_file=create_file, target_directory=dest_dir)


class CommandError(SystemExit):
    def __init__(self, message=None, code=1, prefix='Error: '):
        super().__init__(code)
        self.prefix = prefix
        self.message = message


def main(argv=None):
    args = docopt(get_usage(), argv=argv, version=__version__)

    try:
        run(args)
    except CommandError as e:
        if e.message:
            print(f'{e.prefix}{e.message}', file=sys.stderr)
            sys.exit(e.code)


if __name__ == '__main__':
    main()
