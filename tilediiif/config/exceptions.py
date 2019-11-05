class ConfigError(ValueError):
    pass


class ConfigParseError(ConfigError):
    pass


class ConfigValidationError(ConfigError):
    pass


class CLIValueNotFound(LookupError):
    pass


class InvalidCLIUsageConfigError(ConfigError):
    pass
