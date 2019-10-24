import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import toml
from jsonschema import validate, ValidationError

with open(Path(__file__).parent / "config-schema.json") as f:
    CONFIG_SCHEMA = json.load(f)


class ConfigError(ValueError):
    pass


class FileTransmissionType(Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"


@dataclass
class ConfigProperty:
    name: str
    default: Any
    validator: Callable[[Any], None] = None

    def __get__(self, instance, owner):
        if instance is None:
            return self

        return instance._properties.get(self.name, self.default)

    def __set__(self, instance, value):
        raise TypeError(f"cannot assign to {self.name}")


class ConfigMeta(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)

        for property in cls.property_definitions:
            setattr(cls, property.name, property)


class BaseConfig(metaclass=ConfigMeta):
    property_definitions = []

    def __init__(self, properties=None, **kwargs):
        properties = {**({} if properties is None else properties), **kwargs}
        if not properties.keys() <= self.property_names():
            names = ", ".join(properties.keys() - self.property_names())
            raise ValueError(f"invalid property names: {names}")
        self._properties = {k: v for (k, v) in properties.items() if v is not None}

    @classmethod
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

    def merged_with(self, other_config):
        return Config({**self._properties, **other_config._properties})

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


class Config(BaseConfig):
    property_definitions = [
        ConfigProperty(
            name="image_path_template",
            default="{identifier}/{region}-{size}-{rotation}-{quality}.{format}",
        ),
        ConfigProperty(
            name="info_json_path_template", default="{identifier}/info.json"
        ),
        ConfigProperty(name="sendfile_header_name", default="X-Accel-Redirect"),
        ConfigProperty(name="data_path", default="."),
        ConfigProperty(name="file_transmission", default=FileTransmissionType.DIRECT),
    ]

    @staticmethod
    def from_toml_file(f):
        try:
            data = toml.load(f)
        except toml.TomlDecodeError as e:
            raise ConfigError(f"Unable to parse {get_name(f)} as TOML: {e}") from e
        except OSError as e:
            raise ConfigError(f"Unable to read {get_name(f)}: {e}") from e
        return Config.from_json(data, name=get_name(f))

    @staticmethod
    def from_json(obj, name=None):
        try:
            validate(obj, schema=CONFIG_SCHEMA)
        except ValidationError as e:
            prefix = (
                "Configuration data is invalid"
                if name is None
                else f"Configuration data from {name} is invalid"
            )
            raise ConfigError(f"{prefix}: {e}") from e

        config = obj["tilediiif"]["server"]
        return Config(
            dict(
                sendfile_header_name=config.get("indirect-file-transmission", {}).get(
                    "sendfile-header-name"
                ),
                data_path=config.get("data-path"),
                file_transmission=(
                    FileTransmissionType(config["file-transmission"])
                    if "file-transmission" in config
                    else None
                ),
                image_path_template=config.get("image-path-template"),
                info_json_path_template=config.get("info-json-path-template"),
            )
        )

    @staticmethod
    def from_environ():
        file_transmission_name = os.environ.get(
            ConfigValueEnvars.FILE_TRANSMISSION.value
        )
        try:
            file_transmission = (
                None
                if file_transmission_name is None
                else (FileTransmissionType(file_transmission_name))
            )
        except ValueError as e:
            values = " or ".join(f"{ftt.value!r}" for ftt in FileTransmissionType)
            raise ConfigError(
                f"envar {ConfigValueEnvars.FILE_TRANSMISSION.value}="
                f"{file_transmission_name} "
                f"is invalid, expected {values}"
            ) from e

        properties = dict(
            file_transmission=file_transmission,
            data_path=os.environ.get(ConfigValueEnvars.DATA_PATH.value),
            sendfile_header_name=os.environ.get(
                ConfigValueEnvars.SENDFILE_HEADER_NAME.value
            ),
            image_path_template=os.environ.get(
                ConfigValueEnvars.IMAGE_PATH_TEMPLATE.value
            ),
            info_json_path_template=os.environ.get(
                ConfigValueEnvars.INFO_JSON_PATH_TEMPLATE.value
            ),
        )

        return Config(properties)


class ConfigValueEnvars(Enum):
    DATA_PATH = "TILEDIIIF_SERVER_DATA_PATH"
    FILE_TRANSMISSION = "TILEDIIIF_SERVER_FILE_TRANSMISSION"
    SENDFILE_HEADER_NAME = "TILEDIIIF_SERVER_SENDFILE_HEADER_NAME"
    IMAGE_PATH_TEMPLATE = "TILEDIIIF_SERVER_IMAGE_PATH_TEMPLATE"
    INFO_JSON_PATH_TEMPLATE = "TILEDIIIF_SERVER_INFO_JSON_PATH_TEMPLATE"


ConfigValueEnvars.envar_names = frozenset(e.name for e in ConfigValueEnvars)


def get_name(f):
    if isinstance(f, (str, Path)):
        return str(f)
    if hasattr(f, "name"):
        return f.name
    return str(f)
