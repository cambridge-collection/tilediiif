import hashlib
from unittest.mock import MagicMock, call

import pytest
from hypothesis import example, given
from hypothesis.strategies import builds, composite, from_regex, integers, one_of, text

from tilediiif.core.templates import (
    Template,
    TemplateBindings,
    TemplateRenderer,
    context_value_field,
    parse_template,
    shard_prefix,
    use_context,
)

placeholder_names = from_regex(r"\A[\w.-]+\Z")
placeholder_segments = builds(
    lambda name: {"type": "placeholder", "name": name, "value": f"{{{name}}}"},
    placeholder_names,
)
literal_segments = builds(
    lambda value: {
        "type": "literal",
        "raw": value,
        "value": value.replace("\\", "\\\\").replace("{", r"\{"),
    },
    text(min_size=1),
)


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
        seg = draw(placeholder_segments) if last_was_literal else draw(any_segment)
        last_was_literal = seg["type"] == "literal"
        segments.append(seg)

    return segments


templates = builds(
    lambda segments: {
        "segments": segments,
        "value": "".join(seg["value"] for seg in segments),
    },
    template_segments(),
)


@composite
def populated_templates(draw, templates=templates, placeholder_values=text()):
    template = draw(templates)
    ordered_placeholders = sorted(
        {
            seg["name"]: seg
            for seg in template["segments"]
            if seg["type"] == "placeholder"
        }.values(),
        key=lambda seg: seg["name"],
    )

    return {
        **template,
        "bindings": {
            ph["name"]: draw(placeholder_values) for ph in ordered_placeholders
        },
    }


@given(templates)
@example(
    {
        "segments": [
            {"type": "literal", "raw": "\\", "value": "\\\\"},
            {"type": "placeholder", "name": "0", "value": "{0}"},
        ],
        "value": "\\\\{0}",
    }
)
def test_parse_template(template):
    compiled = parse_template(template["value"])
    assert isinstance(compiled, Template)
    assert len(compiled.chunks) == len(template["segments"])
    assert compiled.var_names == {
        seg["name"] for seg in template["segments"] if seg["type"] == "placeholder"
    }


@pytest.mark.parametrize(
    "template, msg",
    [
        [
            "\\x",
            """\
Invalid escape sequence at offset 0:
    \\x
    ^""",
        ],
        [
            "foo\\x",
            """\
Invalid escape sequence at offset 3:
    foo\\x
       ^""",
        ],
        [
            "abc{",
            """\
Invalid placeholder at offset 3:
    abc{
       ^""",
        ],
        [
            "abc{foo$bar}",
            """\
Invalid placeholder at offset 3:
    abc{foo$bar}
       ^""",
        ],
    ],
)
def test_parse_template_rejects_invalid_templates(template, msg):
    with pytest.raises(ValueError) as exc_info:
        parse_template(template)

    assert msg == str(exc_info.value)


@given(populated_templates())
def test_render_template(populated_template):
    compiled = parse_template(populated_template["value"])
    bindings = populated_template["bindings"]
    expected = "".join(
        seg["raw"] if seg["type"] == "literal" else bindings[seg["name"]]
        for seg in populated_template["segments"]
    )

    assert compiled.render(bindings) == expected


@pytest.fixture
def template_fields():
    return {
        "dynamic-field": lambda context: f'foo:{context["bar"]}',
        "const-field": "abc",
    }


@pytest.fixture
def template_context():
    return {"bar": 123}


@pytest.fixture
def template_string():
    return "prefix/{dynamic-field}-{const-field}"


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
    assert template_bindings.keys() == {"dynamic-field", "const-field"}


def test_template_bindings_calculated_field(template_bindings):
    assert template_bindings.get("dynamic-field") == "foo:123"


def test_template_bindings_constant_field(template_bindings):
    assert template_bindings.get("const-field") == "abc"


def test_template_bindings_missing_field(template_bindings):
    assert template_bindings.get("asdfsd") is None


def test_template_renderer_renders_template_with_bindings(
    template_renderer, template_context
):
    assert template_renderer(template_context) == "prefix/foo:123-abc"


@pytest.mark.parametrize(
    "names, expected_call",
    [
        [(), call()],
        [("a",), call(1)],
        [("a", "b"), call(1, 2)],
        [("a", "b", "c"), call(1, 2, 3)],
    ],
)
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
    hashed = hashlib.blake2b(key.encode("utf-8"), digest_size=segment_count).hexdigest()
    segments = []
    for _ in range(segment_count):
        seg, hashed = hashed[:2], hashed[2:]
        segments.append(seg)

    prefix = shard_prefix(key, segment_count=segment_count)
    assert prefix == "/".join(segments)
    assert prefix.lower() == prefix
    assert len(prefix) > 0
    assert len(prefix) == segment_count * 2 + (segment_count - 1)


def test_context_value_field(template_context):
    bar_field = context_value_field("bar")
    assert bar_field(template_context) == 123
