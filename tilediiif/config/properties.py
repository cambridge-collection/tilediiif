import enum
from pathlib import Path
from typing import Type

from tilediiif.config.core import ConfigProperty
from tilediiif.config.parsing import parse_bool_strict, parse_path, simple_parser
from tilediiif.config.validation import all_validator, isinstance_validator


class IntConfigProperty(ConfigProperty):
    def __init__(self, name, validator=None, **kwargs):
        _validator = isinstance_validator(int)
        if validator is not None:
            _validator = all_validator(_validator, validator)
        super().__init__(
            name, **{"parse": simple_parser(int), **kwargs, "validator": _validator},
        )


class BoolConfigProperty(ConfigProperty):
    def __init__(self, name, **kwargs):
        super().__init__(
            name,
            **{
                "parse": parse_bool_strict,
                "validator": isinstance_validator(bool),
                **kwargs,
            },
        )


class EnumConfigProperty(ConfigProperty):
    def __init__(self, name, enum_cls: Type[enum.Enum], **kwargs):
        super().__init__(
            name,
            **{
                "validator": isinstance_validator(enum_cls),
                "parse": simple_parser(enum_cls),
                **kwargs,
            },
        )


class PathConfigProperty(ConfigProperty):
    def __init__(self, name, **kwargs):
        super().__init__(
            name,
            **{
                "normaliser": Path,
                "validator": isinstance_validator((Path, str)),
                "parse": parse_path,
                **kwargs,
            },
        )
