import enum
from functools import wraps
from os.path import expanduser, expandvars
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, List, Type, TypeVar, Union

from tilediiif.core.config.exceptions import ConfigParseError

if TYPE_CHECKING:
    from tilediiif.core.config.core import (
        ConfigProperty,
        DefaultParsers,
        NormalisedVariant,
    )


def simple_parser(parse_func: Callable[[Any], Any]):
    """
    A decorator which turns a 1 arg function (e.g. int(x), float(x)) into a parser
    ConfigProperty parser function.
    """

    @wraps(parse_func)
    def parse(value: Any, **_):
        return parse_func(value)

    return parse


def delegating_parser(
    __parse_func=None, property=False, variant=False, default_parsers=False
):
    """
    A decorator to simplify the implementation of parser functions which delegate to the
    next variant for some of their work. Decorated functions take the value and next as
    a kwarg. next is a function which (when invoked with a value) invokes the property's
    parser for the next variant.

    The decorator can be used as::

        @delegating_parser
        def parse(value, next):
            ...

    or::

        @delegating_parser(...)
        def parse(value, next, ...):
            ...

    :arg property If True, the decorated function receives the property kwarg.
    :arg variant If True, the decorated function receives the variant kwarg.
    :arg default_parsers If True, the decorated function receives the default_parsers
         kwarg.
    """
    enabled_kwargs = set(
        kwarg
        for kwarg in [
            "next",
            "property" if property else None,
            "variant" if variant else None,
            "default_parsers" if default_parsers else None,
        ]
        if kwarg is not None
    )

    def filter_parse_func_kwargs(**kwargs):
        return {arg: value for arg, value in kwargs.items() if arg in enabled_kwargs}

    def decorate(parse_func: Callable):
        @wraps(parse_func)
        def parse(
            value: str,
            *,
            property: "ConfigProperty",
            variant: "NormalisedVariant",
            default_parsers: "DefaultParsers",
        ):
            _property = property
            _variant = variant
            _default_parsers = default_parsers

            def next(value, *, property=None, variant=None, default_parsers=None):
                property = _property if property is None else property
                variant = _variant[1:] if variant is None else variant
                default_parsers = (
                    _default_parsers if default_parsers is None else default_parsers
                )
                return property.parse(
                    value, variant=variant, default_parsers=default_parsers
                )

            return parse_func(
                value,
                **filter_parse_func_kwargs(
                    next=next,
                    property=property,
                    variant=variant,
                    default_parsers=default_parsers,
                ),
            )

        return parse

    return decorate(__parse_func) if __parse_func is not None else decorate


E = TypeVar("E", bound=enum.Enum)


def enum_list_parser(enum_cls: Type[E]):
    @simple_parser
    def parse_enum_list(value: str) -> List[E]:
        return [enum_cls(v.strip()) for v in value.split(",")]

    return parse_enum_list


@simple_parser
def parse_bool_strict(value: str):
    if value not in ("true", "false"):
        raise ConfigParseError(
            f"boolean value must be 'true' or 'false', got: {value!r}"
        )
    return value == "true"


@delegating_parser
def parse_string_values(value, next):
    """
    A parser function which treats non-string values as already parsed, and delegates
    parsing of string values to the next variant's parser.
    """
    # Allow strings to be parsed further
    if isinstance(value, str):
        return next(value)
    # Assume non-string values are ready for use
    return value


@simple_parser
def parse_path(path: Union[str, Path]):
    if isinstance(path, Path):
        path = str(path)
    return expandvars(expanduser(path))
