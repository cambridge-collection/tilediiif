import enum
from functools import wraps
from typing import Any, Callable, List, Type, TypeVar

from tilediiif.config.exceptions import ConfigParseError


def simple_parser(parse_func: Callable[[Any], Any]):
    @wraps(parse_func)
    def parse(value: Any, **_):
        return parse_func(value)

    return parse


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
