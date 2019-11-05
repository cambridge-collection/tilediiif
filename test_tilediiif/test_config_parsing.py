import enum
from unittest.mock import MagicMock, Mock, sentinel

import pytest

from tilediiif.config import ConfigParseError, ConfigProperty
from tilediiif.config.parsing import (
    delegating_parser,
    enum_list_parser,
    parse_bool_strict,
    parse_path,
    parse_string_values,
    simple_parser,
)


def test_simple_parser_decorator():
    generic_parse = MagicMock(return_value=sentinel.result)
    parser = simple_parser(generic_parse)

    result = parser(
        sentinel.input, property=MagicMock(), variant=("foo", "bar"), default_parsers={}
    )
    assert result is sentinel.result
    generic_parse.assert_called_once_with(sentinel.input)

    # Can also just call with the value
    generic_parse.reset_mock()
    result = parser(sentinel.input)
    assert result is sentinel.result
    generic_parse.assert_called_once_with(sentinel.input)


def test_enum_list_parser():
    class Foo(enum.Enum):
        A = "a"
        B = "b"

    parser = enum_list_parser(Foo)
    assert parser("a,b,a") == [Foo.A, Foo.B, Foo.A]


def test_parse_bool_strict():
    assert parse_bool_strict("true") is True
    assert parse_bool_strict("false") is False


@pytest.mark.parametrize("value", ["True", "False", "TRUE", "YES"])
def test_parse_bool_strict_rejects_invalid_values(value):
    with pytest.raises(ConfigParseError) as exc_info:
        parse_bool_strict(value)

    assert str(exc_info.value) == (
        f"boolean value must be 'true' or 'false', got: {value!r}"
    )


@pytest.mark.parametrize(
    "path, result",
    [
        ["~", "/home/foo"],
        ["~/", "/home/foo/"],
        ["~/.bar", "/home/foo/.bar"],
        ["~/$THING1", "/home/foo/abc/def"],
        ["/${THING1}/$THING2", "/abc/def/123"],
    ],
)
def test_parse_path(path, result, monkeypatch):
    monkeypatch.setenv("HOME", "/home/foo")
    monkeypatch.setenv("THING1", "abc/def")
    monkeypatch.setenv("THING2", "123")
    assert parse_path(path) == result


def test_parse_string_values():
    foo_prop = ConfigProperty(
        "foo",
        parse=simple_parser(lambda x: ("parsed", int(x))),
        parse_structured_data=parse_string_values,
    )

    assert foo_prop.parse("42") == ("parsed", 42)
    assert foo_prop.parse("42", variant=("structured_data",)) == ("parsed", 42)
    assert foo_prop.parse(("already-parsed", 42), variant=("structured_data",)) == (
        "already-parsed",
        42,
    )


def test_delegating_parser_decorator():
    @delegating_parser
    def parse_comma_separated(value, next):
        return [next(x) for x in value.split(",")]

    foo_prop = ConfigProperty(
        "foo", parse=simple_parser(int), parse_example=parse_comma_separated
    )

    assert foo_prop.parse("1,2,3", variant="example") == [1, 2, 3]


@pytest.fixture
def delegating_parser_decorator(pass_property, pass_variant, pass_default_parsers):
    return delegating_parser(
        property=pass_property,
        variant=pass_variant,
        default_parsers=pass_default_parsers,
    )


@pytest.mark.parametrize("pass_property", [True, False])
@pytest.mark.parametrize("pass_variant", [True, False])
@pytest.mark.parametrize("pass_default_parsers", [True, False])
@pytest.mark.parametrize("sub_property", [True, False])
@pytest.mark.parametrize("sub_variant", [True, False])
@pytest.mark.parametrize("sub_default_parsers", [True, False])
def test_delegating_parser_decorator_with_optional_args(
    delegating_parser_decorator,
    sub_property,
    sub_variant,
    sub_default_parsers,
    pass_property,
    pass_variant,
    pass_default_parsers,
):
    property1 = Mock(spec=ConfigProperty)
    property2 = Mock(spec=ConfigProperty)
    property1.parse.return_value = sentinel.result
    property2.parse.return_value = sentinel.result

    def parse(value, next, **kwargs):
        return next(
            sentinel.value2,
            property=property2 if sub_property else None,
            variant=("c",) if sub_variant else None,
            default_parsers=sentinel.default_parsers2 if sub_default_parsers else None,
        )

    parse = MagicMock(side_effect=parse)
    parser = delegating_parser_decorator(parse)

    assert (
        parser(
            sentinel.value1,
            property=property1,
            variant=("a", "b"),
            default_parsers=sentinel.default_parsers1,
        )
        == sentinel.result
    )

    parse.assert_called_once()
    p_args, p_kwargs = parse.mock_calls[0][1:]
    assert p_args == (sentinel.value1,)
    assert len(p_kwargs) == 1 + pass_property + pass_variant + pass_default_parsers
    assert "next" in p_kwargs
    assert p_kwargs.get("property") == (property1 if pass_property else None)
    assert p_kwargs.get("variant") == (("a", "b") if pass_variant else None)
    assert p_kwargs.get("default_parsers") == (
        sentinel.default_parsers1 if pass_default_parsers else None
    )

    used_property, unused_property = (
        (property2, property1) if sub_property else (property1, property2)
    )
    used_property.parse.assert_called_once_with(
        sentinel.value2,
        variant=("c",) if sub_variant else ("b",),
        default_parsers=sentinel.default_parsers2
        if sub_default_parsers
        else sentinel.default_parsers1,
    )
    unused_property.parse.assert_not_called()
