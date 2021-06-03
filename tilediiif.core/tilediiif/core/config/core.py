import os
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache, reduce
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Tuple, Union

import toml
from jsonpath_rw import parse
from jsonpath_rw.jsonpath import DatumInContext, JSONPath
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate

from tilediiif.core.config.exceptions import (
    CLIValueNotFound,
    ConfigError,
    ConfigParseError,
    ConfigValidationError,
    ConfigValueNotPresent,
    InvalidCLIUsageConfigError,
)
from tilediiif.core.config.parsing import delegating_parser, parse_string_values

Variant = Union[None, str, Iterable[str]]
NormalisedVariant = Tuple[str]
DefaultParsers = Mapping[str, "ParserFunction"]
# ParserFunction has signature:
# def parse(value: Any, *, property: ConfigProperty, variant: NormalisedVariant,
#           default_parsers: DefaultParsers) -> Any
# It can return ParseResult.NONE to indicate no value is present (without triggering an
# error). It can raise a ValueError to indicate the the provided value is invalid.
ParserFunction = Callable


def identity(arg):
    return arg


@dataclass(frozen=True)
class ConstDefaultFactory:
    value: Any
    value_hashable: bool

    def __init__(self, value: Any, *, value_hashable=None):
        object.__setattr__(self, "value", value)

        if value_hashable is None:
            try:
                hash(value)
                value_hashable = True
            except TypeError:
                value_hashable = False
        object.__setattr__(self, "value_hashable", value_hashable)

    def __call__(self, **_):
        return self.value

    def __eq__(self, other):
        if self.value_hashable:
            return isinstance(other, ConstDefaultFactory) and self.value == other.value
        else:
            return object.__eq__(self, other)

    def __hash__(self):
        if self.value_hashable:
            return hash((self.value,))
        else:
            return object.__hash__(self)


@dataclass(frozen=True)
class SimpleDefaultFactory:
    """
    A decorator to convert a no-arg function into a default_factory function.
    """

    fn: Callable

    def __call__(self, **_):
        return self.fn()


simple_default_factory = SimpleDefaultFactory


@dataclass(frozen=True)
class FrozenMapping(Mapping):
    mapping: Mapping

    def __init__(self, mapping: Mapping):
        object.__setattr__(self, "mapping", MappingProxyType(mapping))

    def __hash__(self):
        return hash(tuple(self.items()))

    def __getitem__(self, k):
        return self.mapping[k]

    def __len__(self) -> int:
        return len(self.mapping)

    def __iter__(self):
        return iter(self.mapping)

    def __str__(self):
        return str(self.mapping)

    def __repr__(self):
        return f"{type(self).__name__}({self})"


@dataclass(frozen=True)
class ConfigProperty:
    name: str
    default_factory: Callable[..., Any]
    validator: Callable[[Any], None]
    normaliser: Callable[[Any], Any]
    attrs: Dict

    def __init__(
        self,
        name: str,
        *,
        default=None,
        default_factory=None,
        validator: Callable[[Any], None] = None,
        normaliser: Callable[[Any], Any] = None,
        attrs=None,
        **kwargs,
    ):
        if default is not None and default_factory is not None:
            raise ValueError("default and default_factory cannot both be specified")
        if default is not None:
            default_factory = ConstDefaultFactory(default)

        attrs = {**({} if attrs is None else attrs), **kwargs}
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "default_factory", default_factory)
        object.__setattr__(self, "validator", validator)
        object.__setattr__(self, "normaliser", normaliser)
        object.__setattr__(self, "attrs", FrozenMapping(attrs))

    def __get__(self, instance, owner):
        if instance is None:
            return self

        try:
            return self.get_value(instance)
        except ConfigValueNotPresent:
            return None

    def has_value(self, config: "BaseConfig", use_default=True):
        return self.name in config._property_values or (
            use_default and self.has_default()
        )

    def has_default(self):
        return self.default_factory is not None

    def get_value(self, config: "BaseConfig", use_default=True):
        try:
            return config._property_values[self.name]
        except KeyError:
            if not use_default:
                raise ConfigValueNotPresent(config=config, property=self)
            return self.get_default(config)

    def get_default(self, config: "BaseConfig"):
        if self.default_factory is None:
            raise ConfigValueNotPresent(config=config, property=self)
        default = self.default_factory(config=config, property=self)
        self.validate(default, is_default=True)
        return self.normalise(default)

    def set_value(self, config: "BaseConfig", value):
        config._property_values[self.name] = value

    def __set__(self, instance, value):
        self.validate(value)
        self.set_value(instance, self.normalise(value))

    def validate(self, value, is_default=False):
        if self.validator is not None:
            try:
                self.validator(value)
            except ConfigValidationError as e:
                value_desc = "default value" if is_default else "value"
                raise ConfigValidationError(
                    f"{value_desc} for {self.name!r} is invalid: {e}"
                )

    def normalise(self, value):
        return value if self.normaliser is None else self.normaliser(value)

    def parse(
        self,
        value,
        variant: Variant = None,
        default_parsers: Union[None, DefaultParsers] = None,
    ):
        default_parsers = {} if default_parsers is None else default_parsers
        variant = normalise_variant(variant)
        parse_function_attrs = _parse_function_attrs(variant)

        for parse_function_attr in parse_function_attrs:
            parse_func = self.attrs.get(parse_function_attr)
            if parse_func is None:
                parse_func = default_parsers.get(parse_function_attr)
            if parse_func is not None:
                try:
                    return parse_func(
                        value,
                        property=self,
                        variant=variant,
                        default_parsers=default_parsers,
                    )
                except ValueError as e:
                    raise ConfigParseError(
                        f"Failed to parse config value for {self.name}: {e}"
                    ) from e
        return value


def normalise_variant(variant) -> Tuple[str]:
    if variant is None:
        variant = ()
    if isinstance(variant, str):
        variant = (variant,)
    return tuple(variant)


@lru_cache()
def _parse_function_attrs(variants):
    if not isinstance(variants, tuple) and all(isinstance(s, str) for s in variants):
        raise TypeError(f"variants must be a tuple of strings, got: {variants!r}")
    return tuple(f"parse_{variant.replace('-', '_')}" for variant in variants) + (
        "parse",
    )


class ConfigMeta(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)
        cls._set_up_config_class(name, bases, attrs)


class ParseResult(Enum):
    NONE = 0


@dataclass(eq=False)
class BaseConfigValues(Mapping):
    config: "BaseConfig"
    config_attr_name: str

    def __init__(self, config: "BaseConfig", config_attr_name: str):
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "config_attr_name", config_attr_name)

    @abstractmethod
    def has_value(self, property: ConfigProperty):
        raise NotImplementedError()

    @abstractmethod
    def get_value(self, property: ConfigProperty):
        raise NotImplementedError()

    def _get_property(self, name_or_prop: Union[ConfigProperty, str]):
        name = name_or_prop if isinstance(name_or_prop, str) else name_or_prop.name
        property = getattr(type(self.config), name, None)
        if not isinstance(name_or_prop, str) and property is not name_or_prop:
            raise AttributeError(name_or_prop)
        return property

    def __contains__(self, name_or_prop: Union[ConfigProperty, str]):
        try:
            return self.has_value(self._get_property(name_or_prop))
        except AttributeError:
            return False

    def __getitem__(self, name_or_prop: Union[ConfigProperty, str]) -> Any:
        if name_or_prop in self:
            return self.get_value(self._get_property(name_or_prop))
        raise KeyError(property)

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, _):
        raise AttributeError(f"cannot assign to config property {name}")

    def __delattr__(self, name):
        raise AttributeError(f"cannot delete config property {name}")

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __iter__(self) -> Iterator[ConfigProperty]:
        for property in self.config.properties().values():
            if property in self:
                yield property

    def __str__(self):
        content = ", ".join(
            f"{property.name!r}: {value!r}" for property, value in self.items()
        )
        return f"{{{content}}}"

    def __repr__(self):
        return f"{self.config!r}.{self.config_attr_name}"


class DefaultConfigValues(BaseConfigValues):
    def has_value(self, property: ConfigProperty):
        return property.has_default()

    def get_value(self, property: ConfigProperty):
        return property.get_default(self.config)


class AllConfigValues(BaseConfigValues):
    def has_value(self, property: ConfigProperty):
        return property.has_value(self.config, use_default=True)

    def get_value(self, property: ConfigProperty):
        return property.get_value(self.config, use_default=True)


class NonDefaultConfigValues(BaseConfigValues):
    def has_value(self, property: ConfigProperty):
        return property.has_value(self.config, use_default=False)

    def get_value(self, property: ConfigProperty):
        return property.get_value(self.config, use_default=False)


class BaseConfig(metaclass=ConfigMeta):
    is_abstract_config_cls = True

    @classmethod
    def _set_up_config_class(cls, name, bases, attrs):
        if "is_abstract_config_cls" not in attrs:
            cls.is_abstract_config_cls = False

        if not cls.is_abstract_config_cls:
            if not isinstance(getattr(cls, "property_definitions", None), list):
                raise TypeError(
                    f"{cls.__qualname__} must have a 'property_definitions' attribute "
                    "containing a list of ConfigProperty instances"
                )

            for property in cls.property_definitions:
                setattr(cls, property.name, property)

    def __init__(self, values=None, **kwargs):
        property_values = {**({} if values is None else values), **kwargs}
        if not property_values.keys() <= self.properties().keys():
            names = ", ".join(property_values.keys() - self.properties().keys())
            raise ValueError(f"invalid property names: {names}")

        self._property_values = {}
        for prop_name, value in property_values.items():
            # This updates values in self._property_values via ConfigProperty's
            # descriptor method __set__(), which results in the value being normalised
            # and validated.
            setattr(self, prop_name, value)

    def __eq__(self, other):
        return isinstance(other, BaseConfig) and self.values == other.values

    def __hash__(self):
        # Note that the iterator order of values is deterministic (follows order of
        # properties in cls.property_definitions)
        return hash(tuple(self.values.items()))

    def __repr__(self):
        return f"{type(self).__name__}({self})"

    def __str__(self):
        return str(self.values)

    @property
    def values(self):
        return AllConfigValues(self, "values")

    @property
    def default_values(self):
        return DefaultConfigValues(self, "default_values")

    @property
    def non_default_values(self):
        return NonDefaultConfigValues(self, "non_default_values")

    def merged_with(self, other_config: "BaseConfig"):
        if type(self) != type(other_config):
            raise TypeError(
                f"cannot merge different config types {type(self)} and "
                f"{type(other_config)}"
            )
        return type(self)({**self._property_values, **other_config._property_values})

    @classmethod
    @lru_cache()
    def properties(cls) -> Mapping[str, ConfigProperty]:
        """
        Get a read-only mapping of property names to ConfigProperty instances for this
        config class.

        The iteration order of the mapping follows the definition order in
        cls.property_definitions.
        """
        return MappingProxyType(
            OrderedDict(
                (property.name, property)
                for classs in reversed(cls.mro())
                if issubclass(classs, BaseConfig)
                and hasattr(classs, "property_definitions")
                for property in classs.property_definitions
            )
        )

    @classmethod
    def parse(
        cls,
        values: Dict[str, str],
        variant: Variant = None,
        default_parsers: Union[None, DefaultParsers] = None,
    ):
        variant = normalise_variant(variant)
        default_parsers = {} if default_parsers is None else default_parsers
        property_values = {}
        available_properties = cls.properties()
        for prop_name in values:
            if prop_name not in available_properties:
                raise ValueError(f"{prop_name!r} is not a config property of {cls}")

            property = available_properties[prop_name]
            result = property.parse(
                values[prop_name], variant=variant, default_parsers=default_parsers
            )
            if result is not ParseResult.NONE:
                property_values[prop_name] = result

        return cls(property_values)


class EmptyEnvar(Enum):
    UNSET = ParseResult.NONE
    NONE = None
    EMPTY_STRING = ""


class EnvironmentConfigMixin(BaseConfig):
    is_abstract_config_cls = True

    @classmethod
    def from_environ(cls, envars=None):
        if envars is None:
            envars = os.environ

        envar_props = [
            (prop.attrs["envar_name"], property_name, prop)
            for property_name, prop in cls.properties().items()
            if "envar_name" in prop.attrs
        ]

        raw_values = {
            property_name: envars[envar]
            for (envar, property_name, prop) in envar_props
            if envar in envars
        }

        try:
            return cls.parse(
                raw_values,
                variant=("envar",),
                default_parsers={"parse_envar": cls.parse_envar_default},
            )
        except ConfigValidationError as e:
            envar_names = ", ".join(envar for envar, _, _ in envar_props)
            raise ConfigValidationError(
                f"loading config from envars {envar_names} failed: {e}"
            )

    @staticmethod
    @delegating_parser(property=True)
    def parse_envar_default(value: str, *, next, property):
        if len(value) == 0:
            empty_strategy = property.attrs.get("envar_empty", EmptyEnvar.NONE)
            if empty_strategy is not EmptyEnvar.EMPTY_STRING:
                return empty_strategy.value

        return next(value)


class JSONConfigMixin(BaseConfig):
    is_abstract_config_cls = True
    parse_json_default = parse_string_values

    @classmethod
    def _set_up_config_class(cls, name, bases, attrs):
        super()._set_up_config_class(name, bases, attrs)

        if cls.is_abstract_config_cls:
            return

        if not hasattr(cls, "json_schema"):
            raise TypeError(
                f"{cls.__qualname__} must have a 'json_schema' attribute containing "
                "the schema to use in from_json()"
            )

    @classmethod
    def from_json(cls, obj, name=None):
        if cls.json_schema is None:
            raise TypeError(
                f"{cls.__name__}.from_json() is disabled because {cls.__name__}"
                ".json_schema is None. Set json_schema to True to enable from_json() "
                "without schema validation."
            )
        try:
            validate(obj, schema=cls.json_schema)
        except JSONSchemaValidationError as e:
            prefix = (
                "Configuration data is invalid"
                if name is None
                else f"Configuration data from {name} is invalid"
            )
            raise ConfigError(f"{prefix}: {e}") from e

        property_values = {}
        for name, _, extractor in cls.json_properties():
            try:
                property_values[name] = extractor.find(obj)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to extract JSON value for {cls}.{name}: {e}"
                ) from e

        return cls.parse(
            property_values,
            variant=("jsonpath", "json"),
            default_parsers={
                "parse_json": cls.parse_json_default,
                "parse_jsonpath": cls.parse_jsonpath_default,
            },
        )

    @staticmethod
    @delegating_parser(property=True)
    def parse_jsonpath_default(
        value: List[DatumInContext],
        *,
        next,
        property: ConfigProperty,
    ):
        if len(value) == 0:
            return ParseResult.NONE
        if len(value) > 1:
            path = property.attrs["json_path"]
            raise ConfigParseError(
                f"'json_path' matched multiple times: path={path}, matches={value}"
            )

        try:
            return next(value[0].value)
        except ValueError as e:
            raise ConfigParseError(
                f"Invalid JSON value at {value[0].full_path}: {e}"
            ) from e

    @classmethod
    def json_properties(cls) -> List[Tuple[str, ConfigProperty, JSONPath]]:
        return [
            (p.name, p, cls.get_json_value_extractor(p))
            for p in cls.properties().values()
            if "json_path" in p.attrs
        ]

    @classmethod
    def get_json_value_extractor(cls, property) -> JSONPath:
        path = property.attrs["json_path"]

        if isinstance(path, JSONPath):
            return path
        if not isinstance(path, str):
            raise TypeError(
                f"Unsupported 'json_path': type={type(path)} value={path!r}"
            )

        try:
            return parse(path)
        except Exception as e:
            raise ValueError(
                f"Failed to parse 'json_path' attribute of {cls}{property.name} as a "
                f"JSON Path: {e}"
            )


class TOMLConfigMixin(JSONConfigMixin):
    is_abstract_config_cls = True

    @classmethod
    def from_toml_file(cls, f, name=None):
        try:
            data = toml.load(f)
        except toml.TomlDecodeError as e:
            raise ConfigError(f"Unable to parse {get_name(f)} as TOML: {e}") from e
        except OSError as e:
            raise ConfigError(f"Unable to read {get_name(f)}: {e}") from e
        return cls.from_json(data, name=get_name(f) if name is None else name)


class BaseCLIValue(ABC):
    @abstractmethod
    def extract(self, args: Mapping[str, Any]) -> Any:
        pass

    @staticmethod
    def _normalise_names(names, label="names"):
        input = names
        if names is None:
            names = ()
        if isinstance(names, str):
            names = (names,)
        try:
            if not isinstance(names, tuple):
                names = tuple(names)
            if all(isinstance(n, str) for n in names):
                return names
        except TypeError:
            pass
        raise ValueError(f"{label} must be strings, got: {input}")

    @staticmethod
    def _extract(names, args):
        values = [
            (name, args[name])
            for name in names
            if name in args and args[name] is not None
        ]
        if not values:
            raise CLIValueNotFound(names, args)
        elif len(values) > 1:
            values_found = ", ".join(f"{name} = {value!r}" for name, value in values)
            raise InvalidCLIUsageConfigError(
                "conflicting arguments, at most one can be specified of: "
                f"{values_found}"
            )
        return values[0]

    def is_present(self, args: Mapping[str, Any]):
        try:
            self.extract(args)
            return True
        except CLIValueNotFound:
            return False


@dataclass(frozen=True)
class CLIValue(BaseCLIValue):
    names: Tuple[str]

    def __init__(self, names: Union[Iterable[str], str] = None):
        object.__setattr__(self, "names", self._normalise_names(names))

        if len(self.names) == 0:
            raise ValueError("At least one name must be specified")

    def extract(self, args: Mapping[str, Any]) -> Any:
        _, value = self._extract(self.names, args)
        return value


@dataclass(frozen=True)
class CLIFlag(BaseCLIValue):
    enable_names: Tuple[str]
    disable_names: Tuple[str]

    def __init__(
        self,
        enable_names: Union[Iterable[str], str] = None,
        disable_names: Union[Iterable[str], str] = None,
    ):
        _enable_names = self._normalise_names(enable_names, label="enable_names")
        _disable_names = self._normalise_names(disable_names, label="disable_names")
        if len(_enable_names) + len(_disable_names) == 0:
            raise ValueError("at least one enable or disable name must be specified")
        if disable_names is None:
            assert _enable_names
            _disable_names = tuple(self.generate_disable_names(_enable_names))
        object.__setattr__(self, "enable_names", _enable_names)
        object.__setattr__(self, "disable_names", _disable_names)

    @staticmethod
    def generate_disable_names(names: Tuple[str]):
        for name in names:
            match = re.match(r"\A--(.*)\Z", name)
            if match:
                yield f"--no-{match.group(1)}"

    def extract(self, args: Mapping[str, Any]) -> Any:
        try:
            positive = self._extract(self.enable_names, args)
        except CLIValueNotFound:
            positive = None
        try:
            negative = self._extract(self.disable_names, args)
        except CLIValueNotFound:
            negative = None

        for opt, value in (o_v for o_v in [positive, negative] if o_v is not None):
            if not (value is None or isinstance(value, bool)):
                raise ValueError(
                    f"args contains invalid value for boolean flag: {opt}: {value!r}"
                )

        if positive and negative:
            raise InvalidCLIUsageConfigError(
                f"conflicting arguments: {positive[0]} and its disabled form "
                f"{negative[0]} cannot be specified together"
            )
        if positive:
            return True
        if negative:
            return False
        raise CLIValueNotFound(self.enable_names + self.disable_names, args)


class CommandLineArgConfigMixin(BaseConfig):
    is_abstract_config_cls = True
    parse_cli_arg_default = parse_string_values

    @classmethod
    def drop_undefined_args(cls, args: Dict[str, Any]):
        return {
            arg: value
            for arg, value in args.items()
            if not cls.is_undefined_arg_value(value)
        }

    @staticmethod
    def is_undefined_arg_value(value):
        return value is None or value is False or value == []

    @classmethod
    def from_cli_args(cls, args: Dict[str, Any]):
        stripped_args = cls.drop_undefined_args(args)
        cli_properties = cls.get_cli_properties()

        property_values = {}
        for property, cli_value in cli_properties:
            try:
                property_values[property.name] = cli_value.extract(stripped_args)
            except CLIValueNotFound:
                pass

        return cls.parse(
            property_values,
            variant=("cli-arg",),
            default_parsers={"parse_cli_arg": cls.parse_cli_arg_default},
        )

    @classmethod
    def get_cli_properties(cls):
        return [
            (property, cls.get_cli_value(property.attrs["cli_arg"]))
            for property in cls.properties().values()
            if "cli_arg" in property.attrs
        ]

    @classmethod
    def get_cli_value(cls, cli_value):
        if isinstance(cli_value, str):
            return cls.parse_cli_value(cli_value)
        if isinstance(cli_value, BaseCLIValue):
            return cli_value
        raise ValueError(f"unsupported cli_value: {cli_value!r}")

    @classmethod
    def parse_cli_value(cls, cli_value_expr: str):
        match = re.match(r"\A(<\S*>)|(-[^-=\s]|--[^=\s]+)(=)?\Z", cli_value_expr)
        if not match:
            raise ValueError(
                f"Unable to parse cli_value expression: {cli_value_expr!r}"
            )
        arg, opt, is_value = match.groups()

        if arg or is_value:
            return CLIValue(arg or opt)
        return CLIFlag(opt)


class Config(
    CommandLineArgConfigMixin,
    EnvironmentConfigMixin,
    TOMLConfigMixin,
    BaseConfig,
):
    is_abstract_config_cls = True

    @classmethod
    def from_merged_sources(
        cls, cli_args=None, toml_file=None, envars=None, toml_file_name=None
    ):
        file_config = (
            None
            if toml_file is None
            else cls.from_toml_file(toml_file, name=toml_file_name)
        )
        envar_config = cls.from_environ(envars=envars)
        cli_config = None if cli_args is None else cls.from_cli_args(args=cli_args)

        configs = [c for c in [file_config, envar_config, cli_config] if c is not None]
        return reduce(lambda conf, next_conf: conf.merged_with(next_conf), configs)


def get_name(f):
    if isinstance(f, (str, Path)):
        return str(f)
    if hasattr(f, "name"):
        return f.name
    return str(f)
