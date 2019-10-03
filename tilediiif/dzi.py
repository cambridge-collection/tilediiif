import math
import re
import xml.etree.ElementTree as ET

from tilediiif.validation import (
    require_positive_int, require_positive_non_zero_int)

file_extension = re.compile(r'^[a-zA-Z0-9]+$')


class DZIError(ValueError):
    pass


def parse_dzi_file(file):
    return parse_dzi(ET.parse(file))


def parse_dzi(xml_doc):
    image_el = xml_doc.getroot()
    if image_el.tag != '{http://schemas.microsoft.com/deepzoom/2008}Image':
        raise DZIError(f'\
Unexpected root element, expected: \
{{http://schemas.microsoft.com/deepzoom/2008}}Image, but is: {image_el.tag}')
    size_el = image_el.find('{http://schemas.microsoft.com/deepzoom/2008}Size')

    if size_el is None:
        raise DZIError(f'{image_el}')

    format = image_el.attrib.get('Format')
    if not format:
        raise DZIError(f'\
{image_el.tag}@Format is {"missing" if format is None else "empty"}')

    attrs = {
        'tile_size': _get_attrib_as_int(image_el, 'TileSize',
                                        err_cls=DZIError),
        'format': format,
        'width': _get_attrib_as_int(size_el, 'Width', err_cls=DZIError),
        'height': _get_attrib_as_int(size_el, 'Height', err_cls=DZIError)
    }

    if 'Overlap' in image_el.attrib:
        attrs = {**attrs,
                 'overlap': _get_attrib_as_int(image_el, 'Overlap',
                                               err_cls=DZIError)}

    return attrs


def _get_attrib_as_int(el, name, err_cls=ValueError):
    value = el.attrib.get(name)

    if name is None:
        raise err_cls(f'{el.tag} has no {name!r} attribute')

    try:
        return int(value)
    except ValueError:
        raise err_cls(f'{el.tag}@{name} is not an integer: {value}')


def get_dzi_tile_path(tile, *, dzi_files_path, dzi_meta):
    width, height = dzi_meta['width'], dzi_meta['height']
    scale_factor = tile['scale_factor']
    require_positive_non_zero_int(**{"dzi_meta['width']": width,
                                     "dzi_meta['height']": height,
                                     "tile['scale_factor']": scale_factor})
    x, y = tile['index']['x'], tile['index']['y']
    require_positive_int(**{"tile['index']['x']": x,
                            "tile['index']['y']": y})
    format = dzi_meta['format']
    if type(format) != str and not file_extension.match(format):
        raise ValueError(f"\
dzi_meta['format'] does not appear to be a file extension: {format!r}")

    power = int(math.log2(scale_factor))
    if 2**power != scale_factor:
        raise ValueError(f"\
tile['scale_factor'] must be a power of 2, got: {scale_factor}")

    max_level = math.ceil(math.log2(max(width, height)))
    level = max_level - power

    if level < 0:
        raise ValueError(f'\
scale factor implies a DZI layer below zero: \
max(width, height) = {max(width, height)} \
which implies 1:1 level = {max_level}; \
scale_factor = {scale_factor} which is layer {power} \
implying level={level}')

    return dzi_files_path / f'{level}' / f'{x}_{y}.{format}'
