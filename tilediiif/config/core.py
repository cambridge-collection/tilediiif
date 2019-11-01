import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple, Union

import toml
from jsonpath_rw import parse
from jsonpath_rw.jsonpath import DatumInContext, JSONPath
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate

Variant = Union[None, str, Iterable[str]]
NormalisedVariant = Tuple[str]
DefaultParsers = Dict[str, "ParserFunction"]
# ParserFunction has signature:
# def parse(value: Any, *, property: ConfigProperty, variant: NormalisedVariant,
#           default_parsers: DefaultParsers) -> Any
# It can return ParseResult.NONE to indicate no value is present (without triggering an
# error). It can raise a ValueError to indicate the the provided value is invalid.
ParserFunction = Callable


class ConfigError(ValueError):
    pass


class ConfigParseError(ConfigError):
    pass


class ConfigValidationError(ConfigError):
    pass


class ConfigProperty:
    def __init__(
        self,
        name: str,
        *,
        default=None,
        validator: Callable[[Any], None] = None,
        normaliser: Callable[[Any], Any] = None,
        attrs=None,
        **kwargs,
    ):
        attrs = {**({} if attrs is None else attrs), **kwargs}
        self.name = name
        self.default = default
        self.validator = validator
        self.normaliser = normaliser
        self.attrs = attrs

    def __get__(self, instance, owner):
        if instance is None:
            return self

        return self.get_value(instance)

    def get_value(self, config: "BaseConfig"):
        return config._properties.get(self.name, self.default)

    def set_value(self, config: "BaseConfig", value):
        config._properties[self.name] = value

    def __set__(self, instance, value):
        self.validate(value)
        self.set_value(instance, self.normalise(value))

    def validate(self, value):
        if self.validator is not None:
            try:
                self.validator(value)
            except ConfigValidationError as e:
                raise ConfigValidationError(f"value for {self.name!r} is invalid: {e}")

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
    return tuple(f"parse_{variant}" for variant in variants) + ("parse",)


class ConfigMeta(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)
        cls._set_up_config_class(name, bases, attrs)


class ParseResult(Enum):
    NONE = 0


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
                    f"containing a list of ConfigProperty instances"
                )

            for property in cls.property_definitions:
                setattr(cls, property.name, property)

    def __init__(self, properties=None, **kwargs):
        properties = {**({} if properties is None else properties), **kwargs}
        if not properties.keys() <= self.property_names():
            names = ", ".join(properties.keys() - self.property_names())
            raise ValueError(f"invalid property names: {names}")
        self._properties = {}
        for prop_name, value in properties.items():
            setattr(self, prop_name, value)

    @classmethod
    def _validate_config_class(cls):
        pass

    @classmethod
    @lru_cache()
    def property_names(cls):
        return frozenset(
            prop.name
            for c in cls.mro()
            if issubclass(c, BaseConfig) and hasattr(c, "property_definitions")
            for prop in c.property_definitions
        )

    @classmethod
    def properties(cls):
        return {name: getattr(cls, name) for name in cls.property_names()}

    @classmethod
    def ordered_property_names(cls):
        return sorted(cls.property_names())

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
            return cls.parse(raw_values, variant=("envar",))
        except ConfigValidationError as e:
            envar_names = ", ".join(envar for envar, _, _ in envar_props)
            raise ConfigValidationError(
                f"loading config from envars {envar_names} failed: {e}"
            )

    def merged_with(self, other_config):
        if type(self) != type(other_config):
            raise TypeError(
                f"cannot merge different config types {type(self)} and "
                f"{type(other_config)}"
            )
        return type(self)({**self._properties, **other_config._properties})

    def _values(self):
        return tuple(
            self._properties.get(name) for name in self.ordered_property_names()
        )

    def __repr__(self):
        props = ", ".join(
            f"{name}={self._properties[name]!r}"
            for name in self.ordered_property_names()
            if name in self._properties
        )
        return f"Config({props})"

    def __eq__(self, other):
        return self._values() == other._values()

    def __hash__(self):
        return hash(self._values())


class JSONConfigMixin(BaseConfig):
    is_abstract_config_cls = True

    @classmethod
    def _set_up_config_class(cls, name, bases, attrs):
        super()._set_up_config_class(name, bases, attrs)

        if cls.is_abstract_config_cls:
            return

        if not hasattr(cls, "json_schema"):
            raise TypeError(
                f"{cls.__qualname__} must have a 'json_schema' attribute containing "
                f"the schema to use in from_json()"
            )

    @classmethod
    def from_json(cls, obj, name=None):
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

    @classmethod
    def parse_json_default(
        cls,
        value,
        *,
        property: ConfigProperty,
        variant: NormalisedVariant,
        default_parsers: DefaultParsers,
    ):
        assert variant[0] == "json"

        # Allow strings to be parsed further
        if isinstance(value, str):
            return property.parse(
                value, variant=variant[1:], default_parsers=default_parsers
            )
        # Assume non-string values are ready for use
        return value

    @classmethod
    def parse_jsonpath_default(
        cls,
        value: List[DatumInContext],
        *,
        property: ConfigProperty,
        variant: NormalisedVariant,
        default_parsers: DefaultParsers,
    ):
        assert variant[0:2] == ("jsonpath", "json")

        if len(value) == 0:
            return ParseResult.NONE
        if len(value) > 1:
            path = property.attrs["json_path"]
            raise ConfigParseError(
                f"'json_path' matched multiple times: path={path}, matches={value}"
            )

        try:
            return property.parse(
                value[0].value, variant=variant[1:], default_parsers=default_parsers
            )
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


class Config(EnvironmentConfigMixin, TOMLConfigMixin, BaseConfig):
    is_abstract_config_cls = True


def get_name(f):
    if isinstance(f, (str, Path)):
        return str(f)
    if hasattr(f, "name"):
        return f.name
    return str(f)
