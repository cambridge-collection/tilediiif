"""
Generate IIIF Image API info.json metadata

Usage:
    infojson from-dzi [options] <dzi-file>
    infojson (--help|-h)
    infojson --version

Options:

"""
import xml.etree.ElementTree as ET


def parse_dzi_file(file):
    return parse_dzi(ET.parse(file))


def parse_dzi(xml_doc):
    image_el = xml_doc.getroot()
    if image_el.tag != '{http://schemas.microsoft.com/deepzoom/2008}Image':
        raise ValueError(f'\
Unexpected root element, expected: \
{{http://schemas.microsoft.com/deepzoom/2008}}Image, but is: {image_el.tag}')
    size_el = image_el.find('{http://schemas.microsoft.com/deepzoom/2008}Size')

    if size_el is None:
        raise ValueError(f'{image_el}')

    format = image_el.attrib.get('Format')
    if not format:
        raise ValueError(f'\
{image_el.tag}@Format is {"missing" if format is None else "empty"}')

    attrs = {
        'tile_size': _get_attrib_as_int(image_el, 'TileSize'),
        'format': format,
        'width': _get_attrib_as_int(size_el, 'Width'),
        'height': _get_attrib_as_int(size_el, 'Height')
    }

    if 'Overlap' in image_el.attrib:
        attrs = {**attrs, 'overlap': _get_attrib_as_int(image_el, 'Overlap')}

    return attrs


def _get_attrib_as_int(el, name):
    value = el.attrib.get(name)

    if name is None:
        raise ValueError(f'{el.tag} has no {name!r} attribute')

    try:
        return int(value)
    except ValueError as e:
        raise ValueError(f'{el.tag}@{name} is not an integer: {value}')
