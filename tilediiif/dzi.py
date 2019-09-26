import xml.etree.ElementTree as ET


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
