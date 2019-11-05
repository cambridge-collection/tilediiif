import enum
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tilediiif.config.core import BaseConfig, ConfigParseError, ConfigValidationError
from tilediiif.config.properties import (
    BoolConfigProperty,
    EnumConfigProperty,
    IntConfigProperty,
    PathConfigProperty,
)


@pytest.fixture
def enum_cls():
    class ExampleEnum(enum.Enum):
        A = "a"
        B = "b"

    return ExampleEnum


@pytest.fixture
def example_config_cls(enum_cls):
    class ExampleConfig(BaseConfig):
        property_definitions = [
            IntConfigProperty("int"),
            BoolConfigProperty("bool"),
            EnumConfigProperty("enum", enum_cls),
            PathConfigProperty("path"),
        ]

    return ExampleConfig


def test_int_config_property(example_config_cls):
    assert example_config_cls({"int": 42}).int == 42
    assert example_config_cls.parse({"int": "42"}).int == 42


def test_int_config_property_validates(example_config_cls):
    with pytest.raises(ConfigValidationError):
        example_config_cls({"int": "abc"})


def test_int_config_property_rejects_unparsable_values(example_config_cls):
    with pytest.raises(ConfigParseError):
        example_config_cls.parse({"int": "abc"})


def test_int_config_property_extends_validation_with_provided_validator():
    validate = MagicMock()

    class ExampleConfig(BaseConfig):
        property_definitions = [IntConfigProperty("int", validator=validate)]

    ExampleConfig({"int": 42})
    with pytest.raises(ConfigValidationError):
        ExampleConfig({"int": "abc"})

    # not called with 'abc' because the default int validator fails first
    validate.assert_called_once_with(42)


def test_bool_config_property(example_config_cls):
    assert example_config_cls({"bool": True}).bool is True
    assert example_config_cls.parse({"bool": "true"}).bool is True


def test_bool_config_property_validates_values(example_config_cls):
    with pytest.raises(ConfigValidationError):
        example_config_cls({"bool": "abc"})


def test_enum_config_property(example_config_cls, enum_cls):
    assert example_config_cls({"enum": enum_cls.A}).enum is enum_cls.A
    assert example_config_cls.parse({"enum": "a"}).enum is enum_cls.A


def test_enum_config_property_validates_values(example_config_cls, enum_cls):
    with pytest.raises(ConfigValidationError):
        example_config_cls({"enum": "abc"})


def test_path_config_property(example_config_cls, monkeypatch):
    monkeypatch.setenv("HOME", "/home/foo")
    assert example_config_cls(path="/tmp/bar").path == Path("/tmp/bar")
    # Paths are only expanded when parsing
    assert example_config_cls(path=Path("~/bar")).path == Path("~/bar")
    assert example_config_cls.parse({"path": "~/bar"}).path == Path("/home/foo/bar")
    assert example_config_cls.parse({"path": Path("~/bar")}).path == Path(
        "/home/foo/bar"
    )


def test_path_config_property_validates_values(example_config_cls):
    with pytest.raises(ConfigValidationError):
        example_config_cls(path=42)
