import textwrap
from io import StringIO
from pathlib import Path
from unittest.mock import sentinel

import pytest

from tilediiif.config import (
    BaseConfig,
    Config,
    ConfigError,
    ConfigProperty,
    JSONConfigMixin,
)
from tilediiif.config.core import (
    ConstDefaultFactory,
    EmptyEnvar,
    EnvironmentConfigMixin,
    _parse_function_attrs,
    normalise_variant,
    simple_default_factory,
)
from tilediiif.config.exceptions import ConfigValidationError
from tilediiif.config.parsing import parse_bool_strict, simple_parser
from tilediiif.config.validation import isinstance_validator, iterable_validator


@pytest.fixture
def config_cls_a():
    class ConfigA(BaseConfig):
        property_definitions = [
            ConfigProperty("foo"),
            ConfigProperty("bar"),
        ]

    return ConfigA


@pytest.fixture
def config_cls_b():
    class ConfigB(BaseConfig):
        property_definitions = [
            ConfigProperty("foo"),
            ConfigProperty("bar"),
        ]

    return ConfigB


def test_config_equals(config_cls_a, config_cls_b):
    assert config_cls_a({"foo": 42}) == config_cls_a({"foo": 42})
    assert config_cls_a({"foo": 42}) == config_cls_b({"foo": 42})


def test_config_str(config_cls_a):
    assert str(config_cls_a({})) == "{}"
    assert str(config_cls_a({"foo": 42})) == "{'foo': 42}"
    assert str(config_cls_a({"foo": 42, "bar": "hi"})) == "{'foo': 42, 'bar': 'hi'}"


def test_config_repr(config_cls_a):
    assert repr(config_cls_a({})) == "ConfigA({})"
    assert repr(config_cls_a({"foo": 42})) == "ConfigA({'foo': 42})"
    assert repr(config_cls_a({"foo": 42, "bar": "hi"})) == (
        "ConfigA({'foo': 42, 'bar': 'hi'})"
    )


def test_config_hash(config_cls_a):
    config = config_cls_a({"foo": 123})
    assert isinstance(hash(config), int)
    assert {config: "foo"}[config] == "foo"


@pytest.mark.parametrize(
    "a, b, expected",
    [
        [{}, {}, {}],
        [{"foo": 1}, {"bar": 5}, {"foo": 1, "bar": 5}],
        [{"foo": 1}, {"foo": 2, "bar": 5}, {"foo": 2, "bar": 5}],
    ],
)
def test_merged_with(a, b, expected, config_cls_a):
    assert config_cls_a(a).merged_with(config_cls_a(b)) == config_cls_a(expected)


def test_config_non_default_values():
    class ExampleConfig(BaseConfig):
        property_definitions = [ConfigProperty("a", default=42), ConfigProperty("b")]

    config_with_values = ExampleConfig(a=1, b=2)
    assert config_with_values.non_default_values.a == 1
    assert config_with_values.non_default_values.b == 2
    assert ExampleConfig.a in config_with_values.non_default_values
    assert ExampleConfig.b in config_with_values.non_default_values

    assert len(config_with_values.non_default_values) == 2
    assert dict(config_with_values.non_default_values) == {
        ExampleConfig.a: 1,
        ExampleConfig.b: 2,
    }

    config_without_values = ExampleConfig()
    for property in [ExampleConfig.a, ExampleConfig.b]:
        assert property not in config_without_values.non_default_values
        with pytest.raises(KeyError):
            config_without_values.non_default_values[property]
        with pytest.raises(AttributeError):
            getattr(config_without_values.non_default_values, property.name)

    assert len(config_without_values.non_default_values) == 0
    assert dict(config_without_values.non_default_values) == {}


def test_config_default_values():
    class ExampleConfig(BaseConfig):
        property_definitions = [ConfigProperty("a", default=42), ConfigProperty("b")]

    config = ExampleConfig(a=1, b=2)
    assert ExampleConfig.a in config.default_values
    assert ExampleConfig.b not in config.default_values
    assert config.default_values.a == 42
    assert config.default_values["a"] == 42
    assert config.default_values[ExampleConfig.a] == 42
    assert len(config.default_values) == 1
    assert dict(config.default_values) == {ExampleConfig.a: 42}

    with pytest.raises(KeyError):
        config.default_values[ExampleConfig.b]
    with pytest.raises(AttributeError):
        config.default_values.b


def test_config_values():
    class ExampleConfig(BaseConfig):
        property_definitions = [ConfigProperty("a", default=42), ConfigProperty("b")]

    config_with_values = ExampleConfig(a=1, b=2)
    assert config_with_values.values.a == 1
    assert config_with_values.values.b == 2
    assert ExampleConfig.a in config_with_values.values
    assert ExampleConfig.b in config_with_values.values

    assert len(config_with_values.values) == 2
    assert dict(config_with_values.values) == {
        ExampleConfig.a: 1,
        ExampleConfig.b: 2,
    }

    config_without_values = ExampleConfig()
    assert ExampleConfig.a in config_without_values.values
    assert ExampleConfig.b not in config_without_values.values
    assert config_without_values.values.a == 42
    assert config_without_values.values[ExampleConfig.a] == 42
    assert len(config_without_values.values) == 1
    assert dict(config_without_values.values) == {ExampleConfig.a: 42}

    with pytest.raises(KeyError):
        config_without_values.values[ExampleConfig.b]
    with pytest.raises(AttributeError):
        config_without_values.values.b

    # values is read only
    with pytest.raises(AttributeError):
        config_without_values.values.a = 123
    with pytest.raises(TypeError):
        config_without_values.values[ExampleConfig.a] = 123

    config_without_values.b = 456
    # values is a live view
    assert config_without_values.values.b == 456
    assert config_without_values.values[ExampleConfig.b] == 456


def test_config_class_property_inheritance():
    class StandardConfig(BaseConfig):
        property_definitions = [
            ConfigProperty("foo", default=42),
            ConfigProperty("bar", default=23),
        ]

    class FancyConfig(StandardConfig):
        property_definitions = [ConfigProperty("foo", default=44)]

    assert FancyConfig().default_values.foo == 44
    assert FancyConfig().default_values.bar == 23

    assert list(StandardConfig.properties().keys()) == ["foo", "bar"]
    assert list(FancyConfig.properties().keys()) == ["foo", "bar"]


def test_json_config_classes_require_json_schema_attr():
    with pytest.raises(TypeError) as exc_info:

        class BadConfig(JSONConfigMixin, BaseConfig):
            property_definitions = []
            pass

    assert str(exc_info.value) == (
        "test_json_config_classes_require_json_schema_attr.<locals>.BadConfig must "
        "have a 'json_schema' attribute containing the schema to use in from_json()"
    )


def test_config_classes_must_have_property_definitions_attribute():
    with pytest.raises(TypeError) as exc_info:

        class BadConfig(BaseConfig):
            pass

    assert str(exc_info.value) == (
        "test_config_classes_must_have_property_definitions_attribute.<locals>"
        ".BadConfig must have a 'property_definitions' attribute containing a list of "
        "ConfigProperty instances"
    )


def test_config_classes_marked_as_abstract_dont_need_attributes():
    class EmptyConfig(Config):
        is_abstract_config_cls = True


def test_config_property_default_value():
    class ExampleConfig(BaseConfig):
        property_definitions = [ConfigProperty("foo", default=42)]

    assert ExampleConfig().foo == 42
    assert ExampleConfig({"foo": 7}).foo == 7


@pytest.mark.parametrize(
    "property",
    [
        ConfigProperty(
            "foo",
            validator=isinstance_validator(int),
            default_factory=simple_default_factory(lambda: "abc"),
        ),
        ConfigProperty("foo", validator=isinstance_validator(int), default="abc"),
    ],
)
def test_config_property_default_values_are_validated(property):
    with pytest.raises(ConfigValidationError) as exc_info:
        property.get_default(sentinel)

    assert (
        str(exc_info.value)
        == "default value for 'foo' is invalid: expected a int but got a str: 'abc'"
    )


@pytest.mark.parametrize(
    "property",
    [
        ConfigProperty(
            "foo",
            normaliser=frozenset,
            default_factory=simple_default_factory(lambda: ("a", "b")),
        ),
        ConfigProperty("foo", normaliser=frozenset, default=("a", "b")),
    ],
)
def test_config_property_default_values_are_normalised(property):
    default = property.get_default(sentinel)
    assert isinstance(default, frozenset)
    assert default == {"a", "b"}


def test_config_property_default_factory():
    def get_default(*, config, property):
        assert config is config_instance
        assert property is ExampleConfig.foo
        return 42

    class ExampleConfig(BaseConfig):
        property_definitions = [ConfigProperty("foo", default_factory=get_default)]

    config_instance = ExampleConfig()
    assert config_instance.foo == 42


def test_config_property_has_default():
    assert ConfigProperty("foo").has_default() is False
    assert ConfigProperty("foo", default=42).has_default() is True
    assert (
        ConfigProperty(
            "foo", default_factory=simple_default_factory(lambda: 42)
        ).has_default()
        is True
    )


def test_simple_default_factory():
    @simple_default_factory
    def get_default():
        return 42

    class ExampleConfig(BaseConfig):
        property_definitions = [ConfigProperty("foo", default_factory=get_default)]

    assert ExampleConfig().foo == 42


def test_config_property_validator():
    class ExampleConfig(BaseConfig):
        property_definitions = [
            ConfigProperty("foo", validator=isinstance_validator(int))
        ]

    assert ExampleConfig().foo is None
    assert ExampleConfig({"foo": 7}).foo == 7

    with pytest.raises(ConfigError) as exc_info:
        ExampleConfig({"foo": "blah"})
    assert str(exc_info.value) == (
        "value for 'foo' is invalid: expected a int but got a str: 'blah'"
    )

    config = ExampleConfig({"foo": 42})
    with pytest.raises(ConfigError) as exc_info:
        config.foo = "abc"
    assert str(exc_info.value) == (
        "value for 'foo' is invalid: expected a int but got a str: 'abc'"
    )


def test_config_property_parsing():
    class ExampleConfig(BaseConfig):
        property_definitions = [
            ConfigProperty(
                "foo", validator=isinstance_validator(int), parse=simple_parser(int)
            ),
            ConfigProperty(
                "bar",
                validator=isinstance_validator(int),
                parse_custom=simple_parser(int),
            ),
        ]

    assert ExampleConfig.parse({"foo": "42"}).foo == 42

    # bar has no default parser, so uses the string value
    with pytest.raises(ConfigError) as exc_info:
        assert ExampleConfig.parse({"bar": "42"})
    assert str(exc_info.value) == (
        "value for 'bar' is invalid: expected a int but got a str: '42'"
    )

    # But bar does have a custom parser
    config = ExampleConfig.parse({"foo": "24", "bar": "42"}, variant="custom")
    # foo uses the default parser as it has no matching parser for the variant 'custom'
    assert config.foo == 24
    assert config.bar == 42


def test_config_property_default_parsers():
    class ExampleConfig(BaseConfig):
        property_definitions = [
            ConfigProperty(
                "foo", validator=isinstance_validator(float), parse=simple_parser(float)
            ),
            ConfigProperty(
                "bar",
                validator=isinstance_validator(int),
                parse_custom=simple_parser(lambda x: int(x.decode("utf-8")[1:-1])),
            ),
        ]

    _default_parsers = None
    parse_custom_calls = 0

    def parse_custom(value, *, property, default_parsers, variant):
        nonlocal parse_custom_calls
        parse_custom_calls += 1

        assert variant == ("custom",)
        assert default_parsers == _default_parsers
        assert property == ExampleConfig.foo

        return property.parse(
            value.decode("utf-8")[1:-1],
            default_parsers=default_parsers,
            variant=variant[1:],
        )

    _default_parsers = {"parse_custom": parse_custom}
    config = ExampleConfig.parse(
        {"foo": b"[42.5]", "bar": b"[33]"},
        variant="custom",
        default_parsers=_default_parsers,
    )
    assert parse_custom_calls == 1
    assert config.foo == 42.5
    assert config.bar == 33


@pytest.mark.parametrize(
    "variant, normalised_variant",
    [
        [None, ()],
        [[], ()],
        ["foo", ("foo",)],
        [["foo"], ("foo",)],
        [["foo", "bar"], ("foo", "bar")],
    ],
)
def test_normalise_variant(variant, normalised_variant):
    assert normalise_variant(variant) == normalised_variant


@pytest.mark.parametrize(
    "variants, expected_attrs",
    [
        [(), ("parse",)],
        [("foo",), ("parse_foo", "parse")],
        [("foo", "bar"), ("parse_foo", "parse_bar", "parse")],
    ],
)
def test_parse_function_attrs(variants, expected_attrs):
    assert _parse_function_attrs(variants) == expected_attrs


def test_config_values_are_normalised():
    class ExampleConfig(BaseConfig):
        property_definitions = [
            ConfigProperty(
                "foo",
                validator=iterable_validator(isinstance_validator(str)),
                normaliser=set,
                parse=simple_parser(lambda x: x.split(",")),
            )
        ]

    assert ExampleConfig({"foo": ["a", "b", "b"]}).foo == {"a", "b"}
    assert ExampleConfig.parse({"foo": "a,b,b"}).foo == {"a", "b"}
    config = ExampleConfig()
    config.foo = ["a", "b", "b"]
    assert config.foo == {"a", "b"}


@pytest.fixture
def example_config_cls():
    class ExampleConfig(Config):
        json_schema = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "foo": {"type": "integer"},
                        "bar": {"type": "string"},
                        "is_baz": {"type": "boolean"},
                    },
                    "required": ["foo"],
                    "additionalProperties": False,
                }
            },
            "required": ["config"],
        }

        property_definitions = [
            ConfigProperty(
                "foo",
                validator=isinstance_validator(int),
                parse=simple_parser(int),
                envar_name="TEST_FOO",
                json_path="config.foo",
            ),
            ConfigProperty(
                "bar",
                default=["x", "y", "z"],
                validator=iterable_validator(isinstance_validator(str)),
                parse=simple_parser(lambda val: val.split(",")),
                parse_envar=simple_parser(lambda val: val.lower().split(",")),
                envar_name="TEST_BAR",
                json_path="config.bar",
            ),
            ConfigProperty(
                "is_baz",
                validator=isinstance_validator(bool),
                parse=parse_bool_strict,
                envar_name="TEST_BAZ",
                json_path="config.is_baz",
            ),
            ConfigProperty(
                "boz",
                validator=isinstance_validator(float),
                parse=simple_parser(float),
                envar_name="TEST_BOZ",
            ),
        ]

    return ExampleConfig


def test_config_from_json_is_disabled_if_schema_is_none():
    class ExampleConfig(JSONConfigMixin, BaseConfig):
        json_schema = None
        property_definitions = []

    with pytest.raises(TypeError) as exc_info:
        ExampleConfig.from_json({})

    assert str(exc_info.value).startswith(
        "ExampleConfig.from_json() is disabled because ExampleConfig.json_schema is "
        "None."
    )


def test_config_from_json_with_true_as_schema_accepts_any_json():
    class ExampleConfig(JSONConfigMixin, BaseConfig):
        json_schema = True
        property_definitions = [ConfigProperty("foo", default=1, json_path="abc.def")]

    assert ExampleConfig.from_json({}).foo == 1
    assert ExampleConfig.from_json(42).foo == 1
    assert ExampleConfig.from_json(None).foo == 1
    assert ExampleConfig.from_json({"abc": {"def": 42}}).foo == 42


def test_config_from_json(example_config_cls):
    config = example_config_cls.from_json(
        {
            "config": {"foo": 42, "bar": "abc,def", "is_baz": True},
            "ignored_extra_thing": {},
        }
    )
    assert config.foo == 42
    assert config.bar == ["abc", "def"]
    assert config.is_baz is True
    assert config.boz is None


def test_config_from_json_omits_missing_values(example_config_cls):
    config = example_config_cls.from_json(
        {"config": {"foo": 42}, "ignored_extra_thing": {}}
    )
    assert config.foo == 42
    assert config.bar == ["x", "y", "z"]  # default value
    assert config.is_baz is None


def test_config_from_json_validates_data_against_schema(example_config_cls):
    with pytest.raises(ConfigError) as exc_info:
        example_config_cls.from_json({})

    assert str(exc_info.value).startswith(
        "Configuration data is invalid: 'config' is a required property"
    )


def test_config_from_toml_file(example_config_cls):
    toml_file = StringIO(
        textwrap.dedent(
            """
        [config]
        foo = 42
        bar = "abc,def"
        is_baz = true

        [ignored-other-stuff]
        foo = "bar"
    """
        )
    )

    config = example_config_cls.from_toml_file(toml_file)
    assert config.foo == 42
    assert config.bar == ["abc", "def"]
    assert config.is_baz is True
    assert config.boz is None


def test_config_from_toml_file_validates_data_against_schema(example_config_cls):
    toml_file = StringIO(
        textwrap.dedent(
            """
        [config]
        foo = 42
        not-allowed = "foo"
    """
        )
    )

    with pytest.raises(ConfigError) as exc_info:
        example_config_cls.from_toml_file(toml_file, name="invalid-toml-example")

    assert str(exc_info.value).startswith(
        "Configuration data from invalid-toml-example is invalid: Additional "
        "properties are not allowed ('not-allowed' was unexpected)"
    )


def test_config_from_environ_reads_os_environ(example_config_cls, monkeypatch):
    monkeypatch.setenv("TEST_FOO", "42")
    monkeypatch.setenv("TEST_BAR", "ABC,def")
    monkeypatch.setenv("TEST_BAZ", "true")
    monkeypatch.setenv("TEST_BOZ", "3.14")

    config = example_config_cls.from_environ()
    assert config.foo == 42
    assert config.bar == ["abc", "def"]  # bar has an envar parser which lowercases
    assert config.is_baz is True
    assert config.boz == 3.14


def test_config_from_environ_can_read_manually_specified_vars(example_config_cls):
    config = example_config_cls.from_environ(envars={"TEST_FOO": "55"})
    assert config.foo == 55


@pytest.mark.parametrize(
    "envar_empty, expected",
    [
        [EmptyEnvar.UNSET, Path("abc")],
        [EmptyEnvar.NONE, None],
        [EmptyEnvar.EMPTY_STRING, Path("")],
        [None, None],
    ],
)
def test_config_from_environ_handles_empty_envars_according_to_strategy(
    envar_empty, expected, monkeypatch
):
    envar_empty_kwargs = {} if envar_empty is None else dict(envar_empty=envar_empty)

    class EnvarConfig(EnvironmentConfigMixin, BaseConfig):
        property_definitions = [
            ConfigProperty(
                "foo",
                default=Path("abc"),
                parse=simple_parser(Path),
                envar_name="TEST_FOO",
                **envar_empty_kwargs,
            ),
        ]

    monkeypatch.setenv("TEST_FOO", "")
    assert EnvarConfig.from_environ().foo == expected


def test_const_default_factory_with_hashable_value():
    a = ConstDefaultFactory((1, 2))
    assert a() == (1, 2)
    assert a.value_hashable is True
    b = ConstDefaultFactory((1, 2))
    assert a == b
    assert {a: sentinel}[a] is sentinel
    assert {a: sentinel}[b] is sentinel


def test_const_default_factory_with_unhashable_value():
    a = ConstDefaultFactory([1, 2])
    assert a() == [1, 2]
    assert a.value_hashable is False
    b = ConstDefaultFactory([1, 2])
    # with non-hashable values, equality and hash() is based on object identity
    assert a != b
    assert a.value == b.value
    # still hashable despite value not being hashable
    assert {a: sentinel}[a] is sentinel
    assert {a: sentinel}.get(b) is None
