import math

import pytest
from hypothesis import given, assume
from hypothesis.strategies import (
    builds, one_of, from_regex, text, composite, integers)

from test_tilediiif.test_infojson import image_dimensions
from tilediiif.tilelayout import get_layer_tiles, parse_template, Template

ints_over_zero = integers(min_value=1)

@given(width=integers(), height=integers(), tile_size=integers(),
       scale_factor=integers())
def test_get_layer_tiles_argument_validation(width, height, tile_size,
                                             scale_factor):
    assume(any(n < 1 for n in [width, height, tile_size, scale_factor]))

    with pytest.raises(ValueError):
        next(get_layer_tiles(width=width, height=height, tile_size=tile_size,
                             scale_factor=scale_factor))


@given(width=image_dimensions, height=image_dimensions,
       tile_size=ints_over_zero,
       scale_factor=integers(min_value=1, max_value=2**18))
def test_get_layer_tiles(width, height, tile_size, scale_factor):
    src_tile_size = (tile_size * scale_factor)
    has_trailing_x = bool(width % src_tile_size)
    has_trailing_y = bool(height % src_tile_size)
    tiles_x = width // src_tile_size + has_trailing_x
    tiles_y = height // src_tile_size + has_trailing_y

    # Don't bother testing ridiculously huge tile counts
    assume(tiles_x * tiles_y < 10_000)

    tiles = list(get_layer_tiles(
        width=width, height=height, tile_size=tile_size,
        scale_factor=scale_factor))

    assert len(tiles) > 0
    assert len(tiles) == tiles_x * tiles_y

    assert set(tile['index']['x'] for tile in tiles) == set(range(tiles_x))
    assert set(tile['index']['y'] for tile in tiles) == set(range(tiles_y))

    for tile in tiles:
        assert set(tile.keys()) == {'scale_factor', 'index', 'src', 'dst'}

        assert tile['scale_factor'] == scale_factor

        is_last_x = tile['index']['x'] == tiles_x - 1
        is_last_y = tile['index']['y'] == tiles_y - 1

        assert tile['src']['x'] == tile['index']['x'] * src_tile_size
        assert tile['src']['y'] == tile['index']['y'] * src_tile_size

        assert tile['dst']['x'] == tile['index']['x'] * tile_size
        assert tile['dst']['y'] == tile['index']['y'] * tile_size

        assert tile['src']['width'] == (
            (width % src_tile_size)
            if is_last_x and has_trailing_x else src_tile_size)
        assert tile['src']['height'] == (
            (height % src_tile_size)
            if is_last_y and has_trailing_y else src_tile_size)

        assert tile['dst']['width'] == (
            math.ceil((width % src_tile_size) / scale_factor)
            if is_last_x and has_trailing_x else tile_size)
        assert tile['dst']['height'] == (
            math.ceil((height % src_tile_size) / scale_factor)
            if is_last_y and has_trailing_y else tile_size)


placeholder_names = from_regex(r'\A[\w.]+\Z')
placeholder_segments = builds(
    lambda name: {'type': 'placeholder', 'name': name, 'value': f'{{{name}}}'},
    placeholder_names)
literal_segments = builds(
    lambda value: {'type': 'literal', 'raw': value,
                   'value': value.replace('\\', '\\\\').replace('{', r'\{')},
    text(min_size=1))


@composite
def template_segments(draw, chunk_count=integers(min_value=0, max_value=100)):
    """
    Generates lists of template segments in which two literal segments never
    occur consecutively.
    """
    count = draw(chunk_count)
    segments = []
    any_segment = one_of(literal_segments, placeholder_segments)
    last_was_literal = False
    for _ in range(count):
        seg = (draw(placeholder_segments) if last_was_literal else
               draw(any_segment))
        last_was_literal = seg['type'] == 'literal'
        segments.append(seg)

    return segments


templates = builds(
    lambda segments: {'segments': segments,
                      'value': ''.join(seg['value'] for seg in segments)},
    template_segments())


@composite
def populated_templates(draw, templates=templates, placeholder_values=text()):
    template = draw(templates)
    ordered_placeholders = sorted(
        {seg['name']: seg for seg in template['segments']
         if seg['type'] == 'placeholder'}.values(),
        key=lambda seg: seg['name'])

    return {
        **template,
        'bindings': {ph['name']: draw(placeholder_values)
                     for ph in ordered_placeholders}
    }


@given(templates)
def test_parse_template(template):
    compiled = parse_template(template['value'])
    assert isinstance(compiled, Template)
    assert len(compiled.chunks) == len(template['segments'])
    assert compiled.var_names == {seg['name'] for seg in template['segments']
                                  if seg['type'] == 'placeholder'}


@given(populated_templates())
def test_render_template(populated_template):
    compiled = parse_template(populated_template['value'])
    bindings = populated_template['bindings']
    expected = ''.join(
        seg['raw'] if seg['type'] == 'literal' else bindings[seg['name']]
        for seg in populated_template['segments'])

    assert compiled.render(bindings) == expected
