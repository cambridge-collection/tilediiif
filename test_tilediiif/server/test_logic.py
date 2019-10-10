import hashlib
from unittest.mock import call, MagicMock

import pytest
from hypothesis import given
from hypothesis.strategies import integers, text

from tilediiif.server.logic import (
    context_value_field, shard_prefix, TemplateBindings, TemplateRenderer,
    use_context)
from tilediiif.tilelayout import parse_template


@pytest.fixture
def template_fields():
    return {
        'dynamic-field': lambda context: f'foo:{context["bar"]}',
        'const-field': 'abc'
    }


@pytest.fixture
def template_context():
    return {'bar': 123}


@pytest.fixture
def template_string():
    return 'prefix/{dynamic-field}-{const-field}'


@pytest.fixture
def template(template_string):
    return parse_template(template_string)


@pytest.fixture
def template_renderer(template, template_fields):
    return TemplateRenderer(template=template, fields=template_fields)


@pytest.fixture
def template_bindings(template_fields, template_context):
    return TemplateBindings(template_fields, template_context)


def test_template_bindings_keys(template_bindings):
    assert template_bindings.keys() == {'dynamic-field', 'const-field'}


def test_template_bindings_calculated_field(template_bindings):
    assert template_bindings.get('dynamic-field') == 'foo:123'


def test_template_bindings_constant_field(template_bindings):
    assert template_bindings.get('const-field') == 'abc'


def test_template_bindings_missing_field(template_bindings):
    assert template_bindings.get('asdfsd') is None


def test_template_renderer_renders_template_with_bindings(template_renderer,
                                                          template_context):
    assert template_renderer(template_context) == 'prefix/foo:123-abc'


@pytest.mark.parametrize('names, expected_call', [
    [(), call()],
    [('a',), call(1)],
    [('a', 'b'), call(1, 2)],
    [('a', 'b', 'c'), call(1, 2, 3)],
])
def test_use_context_single(names, expected_call):
    context = dict(a=1, b=2, c=3)
    func = MagicMock()

    @use_context(*names)
    def decorated(*args, **kwargs):
        func(*args, **kwargs)

    decorated(context)
    assert func.mock_calls == [expected_call]


@given(key=text(), segment_count=integers(min_value=1, max_value=64))
def test_shard_prefix_1(key, segment_count):
    hashed = hashlib.blake2b(key.encode('utf-8'),
                             digest_size=segment_count).hexdigest()
    segments = []
    for i in range(segment_count):
        seg, hashed = hashed[:2], hashed[2:]
        segments.append(seg)

    prefix = shard_prefix(key, segment_count=segment_count)
    assert prefix == '/'.join(segments)
    assert prefix.lower() == prefix
    assert len(prefix) > 0
    assert len(prefix) == segment_count * 2 + (segment_count - 1)


def test_context_value_field(template_context):
    bar_field = context_value_field('bar')
    assert bar_field(template_context) == 123
