from enum import Enum

import docopt
import pytest

from tilediiif.core.config.core import (
    BaseConfig,
    CLIFlag,
    CLIValue,
    CLIValueNotFound,
    CommandLineArgConfigMixin,
    ConfigProperty,
    InvalidCLIUsageConfigError,
)
from tilediiif.core.config.properties import (
    BoolConfigProperty,
    EnumConfigProperty,
    IntConfigProperty,
)


def test_cli_value_requires_at_least_one_name():
    with pytest.raises(ValueError) as exc_info:
        CLIValue(())
    assert str(exc_info.value) == "At least one name must be specified"


@pytest.mark.parametrize(
    "cli_value, args, expected",
    [
        [CLIValue("--foo"), {"--foo": "abc"}, "abc"],
        [CLIValue(["--foo"]), {"--foo": "abc"}, "abc"],
        [CLIValue(["--foo", "-f"]), {"--foo": "abc"}, "abc"],
        [CLIValue(["--foo", "-f"]), {"-f": "abc"}, "abc"],
    ],
)
def test_cli_value(cli_value, args, expected):
    assert cli_value.is_present(args)
    assert cli_value.extract(args) == expected


@pytest.mark.parametrize(
    "cli_value, args",
    [[CLIValue("--foo"), {}], [CLIValue(["--foo", "-f"]), {"--bar": "abc"}]],
)
def test_cli_value_raises_not_found_if_no_names_are_present(cli_value, args):
    assert not cli_value.is_present(args)
    with pytest.raises(CLIValueNotFound) as exc_info:
        cli_value.extract(args)

    assert exc_info.value.args == (cli_value.names, args)


@pytest.mark.parametrize(
    "names, msg",
    [
        [42, "names must be strings, got: 42"],
        [[42], "names must be strings, got: [42]"],
    ],
)
def test_cli_value_names_must_be_strings(names, msg):
    with pytest.raises(ValueError) as exc_info:
        CLIValue(names)
    assert str(exc_info.value) == msg


def test_cli_value_raises_usage_error_on_conflicting_arguments():
    cli_value = CLIValue(["--foo", "-f"])
    with pytest.raises(InvalidCLIUsageConfigError) as exc_info:
        cli_value.extract({"--foo": "a", "-f": "b"})

    assert (
        str(exc_info.value)
        == f"conflicting arguments, at most one can be specified of: --foo = 'a', -f = 'b'"
    )


@pytest.mark.parametrize(
    "enable_names, disable_names, msg",
    [
        [None, 42, "disable_names must be strings, got: 42"],
        [None, [42], "disable_names must be strings, got: [42]"],
        [42, None, "enable_names must be strings, got: 42"],
        [[42], None, "enable_names must be strings, got: [42]"],
    ],
)
def test_cli_flag_names_must_be_strings(enable_names, disable_names, msg):
    with pytest.raises(ValueError) as exc_info:
        CLIFlag(enable_names, disable_names)
    assert str(exc_info.value) == msg


@pytest.mark.parametrize(
    "args, msg",
    [
        [
            {"--enable": "yes"},
            "args contains invalid value for boolean flag: --enable: 'yes'",
        ],
        [
            {"--disable": "yes"},
            "args contains invalid value for boolean flag: --disable: 'yes'",
        ],
    ],
)
def test_cli_flag_args_must_be_booleans(args, msg):
    with pytest.raises(ValueError) as exc_info:
        CLIFlag("--enable", "--disable").extract(args)
    assert str(exc_info.value) == msg


@pytest.mark.parametrize(
    "cli_flag, args, expected",
    [
        [CLIFlag("--foo"), {"--foo": True}, True],
        [CLIFlag(("--foo", "--bar")), {"--bar": True}, True],
        [CLIFlag("--foo"), {"--no-foo": True}, False],
        [CLIFlag("--foo", "--not-foo"), {"--not-foo": True}, False],
        [CLIFlag("--foo", ()), {"--no-foo": True}, None],
        [CLIFlag("--foo", ("--no-foo", "--no-bar")), {"--no-bar": True}, False],
    ],
)
def test_cli_flag(cli_flag, args, expected):
    if expected is None:
        assert not cli_flag.is_present(args)
        with pytest.raises(CLIValueNotFound) as exc_info:
            cli_flag.extract(args)
        assert exc_info.value.args == (
            cli_flag.enable_names + cli_flag.disable_names,
            args,
        )
    else:
        assert cli_flag.is_present(args)
        assert cli_flag.extract(args) is expected


@pytest.fixture
def example_usage():
    return """\
Usage:
    foo [options] <a> [<b>...]

Options:
    --force=<n>          How hard?

    --count=<n>, -c=<n>  How many times?

    --squash             Squash
    --no-squash          Don't squash

    --flatten            Flatten
    -f                   Flatten
    --dont-flatten       Disable flattening
    -F                   Disable flattening

    --no-squish          Don't squish things
"""


class Force(Enum):
    LOTS = "lots"
    SOME = "some"


@pytest.fixture
def example_config_cls():
    class ExampleConfig(CommandLineArgConfigMixin, BaseConfig):
        property_definitions = [
            ConfigProperty("a", cli_arg="<a>"),
            ConfigProperty("b", cli_arg=CLIValue(names=["<b>"])),
            EnumConfigProperty("force", Force, cli_arg="--force="),
            IntConfigProperty("count", cli_arg=CLIValue(["--count", "-c"])),
            BoolConfigProperty("squash", cli_arg="--squash"),
            BoolConfigProperty(
                "flatten",
                cli_arg=CLIFlag(
                    enable_names=["--flatten", "-f"],
                    disable_names=["--dont-flatten", "-F"],
                ),
            ),
            BoolConfigProperty(
                "squish", cli_arg=CLIFlag(disable_names=["--no-squish"])
            ),
        ]

    return ExampleConfig


@pytest.mark.parametrize(
    "argv, expected",
    [
        [["abc"], {"a": "abc"}],
        [["abc", "--force", "lots"], {"a": "abc", "force": Force.LOTS}],
        [["abc", "--count", "3"], {"a": "abc", "count": 3}],
        [["abc", "-c", "5"], {"a": "abc", "count": 5}],
        [["abc", "--squash"], {"a": "abc", "squash": True}],
        [["abc", "--no-squash"], {"a": "abc", "squash": False}],
        [["abc", "--flatten"], {"a": "abc", "flatten": True}],
        [["abc", "-f"], {"a": "abc", "flatten": True}],
        [["abc", "--dont-flatten"], {"a": "abc", "flatten": False}],
        [["abc", "-F"], {"a": "abc", "flatten": False}],
        [["abc", "--no-squish"], {"a": "abc", "squish": False}],
        [
            ["--count", "3", "-f", "--no-squish", "abc", "foo", "bar"],
            {
                "a": "abc",
                "b": ["foo", "bar"],
                "squish": False,
                "count": 3,
                "flatten": True,
            },
        ],
    ],
)
def test_from_cli_args(example_config_cls, example_usage, argv, expected):
    args = docopt.docopt(example_usage, argv)
    assert example_config_cls.from_cli_args(args) == example_config_cls(expected)


@pytest.mark.parametrize("enable_names", [None, []])
@pytest.mark.parametrize("disable_names", [None, []])
def test_cli_flag_must_have_at_least_one_name(enable_names, disable_names):
    with pytest.raises(ValueError) as exc_info:
        CLIFlag(enable_names, disable_names)
    assert (
        str(exc_info.value) == "at least one enable or disable name must be specified"
    )


@pytest.mark.parametrize(
    "argv, exc_type, exc_msg",
    [
        [
            ["abc", "--squash", "--no-squash"],
            InvalidCLIUsageConfigError,
            "conflicting arguments: --squash and its disabled form --no-squash cannot "
            "be specified together",
        ]
    ],
)
def test_from_cli_args_reports_invalid_arg_usage(
    example_config_cls, example_usage, argv, exc_type, exc_msg
):
    args = docopt.docopt(example_usage, argv)
    with pytest.raises(exc_type) as exc_info:
        example_config_cls.from_cli_args(args)

    assert str(exc_info.value) == exc_msg


@pytest.fixture
def config_cls_with_cli_arg(cli_arg):
    class ExampleConfig(CommandLineArgConfigMixin, BaseConfig):
        property_definitions = [
            ConfigProperty("a", cli_arg=cli_arg),
        ]

    return ExampleConfig


@pytest.mark.parametrize(
    "cli_arg, msg",
    [
        ["blah", "Unable to parse cli_value expression: 'blah'"],
        [42, "unsupported cli_value: 42"],
    ],
)
def test_from_cli_args_reports_invalid_cli_arg_attrs(config_cls_with_cli_arg, msg):
    with pytest.raises(ValueError) as exc_info:
        config_cls_with_cli_arg.from_cli_args({"<a>": "foo"})

    assert str(exc_info.value) == msg
