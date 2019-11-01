import enum
from unittest.mock import MagicMock, sentinel

import pytest

from tilediiif.config import ConfigParseError
from tilediiif.config.parsing import enum_list_parser, parse_bool_strict, simple_parser


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
