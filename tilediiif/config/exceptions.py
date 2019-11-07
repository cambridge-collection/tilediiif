from typing import TYPE_CHECKING

from attr import dataclass

if TYPE_CHECKING:
    from tilediiif.config import BaseConfig, ConfigProperty


class ConfigError(ValueError):
    pass


class ConfigParseError(ConfigError):
    pass


class ConfigValidationError(ConfigError):
    pass


@dataclass
class ConfigValueNotPresent(LookupError):
    config: "BaseConfig"
    property: "ConfigProperty"

    def __str__(self):
        return (
            f"No value for config property {self.property.name!r} exists in config: "
            f"{self.config}"
        )


class CLIValueNotFound(LookupError):
    pass


class InvalidCLIUsageConfigError(ConfigError):
    pass
