from unittest.mock import MagicMock, sentinel

import pytest

from tilediiif.core.config.core import ConfigValidationError
from tilediiif.core.config.validation import (
    all_validator,
    in_validator,
    isinstance_validator,
    iterable_validator,
    length_validator,
    validate_no_duplicates,
)


def test_isinstance_validator():
    validator = isinstance_validator(int)
    validator(3)
    with pytest.raises(ConfigValidationError) as exc_info:
        validator("abc")
    assert str(exc_info.value) == "expected int but got str: 'abc'"


def test_isinstance_validator_multiple_cls():
    validator = isinstance_validator((int, float))
    validator(3)
    validator(3.5)
    with pytest.raises(ConfigValidationError) as exc_info:
        validator("abc")
    assert str(exc_info.value) == "expected int or float but got str: 'abc'"


@pytest.mark.parametrize("value", [[], [1], [1, 2, 3]])
def test_validate_no_duplicates_accepts_valid_values(value):
    validate_no_duplicates(value)


@pytest.mark.parametrize(
    "value, msg",
    [
        [[1, 1], "duplicates are not allowed: 1 appears 2 times"],
        [
            [0, 1, "a", "a", 1, "a"],
            "duplicates are not allowed: 'a' appears 3 times, 1 appears 2 times",
        ],
    ],
)
def test_validate_no_duplicates_rejects_invalid_values(value, msg):
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_no_duplicates(value)

    assert str(exc_info.value) == msg


def test_all_validator():
    b = MagicMock()
    a = MagicMock(side_effect=lambda _: b.assert_not_called())
    validator = all_validator(a, b)
    validator(sentinel)
    a.assert_called_once_with(sentinel)
    b.assert_called_once_with(sentinel)


def test_in_validator():
    validator = in_validator(range(3, 5))

    validator(3)
    validator(4)
    with pytest.raises(ConfigValidationError) as exc_info:
        validator(8)
    assert str(exc_info.value) == "8 is not in range(3, 5)"


def test_iterable_validator_validates_value_against_iterable_type():
    validator = iterable_validator(iterable_type=set)

    validator({1, 2})
    with pytest.raises(ConfigValidationError) as exc_info:
        validator([1, 2])
    assert str(exc_info.value) == "expected set but got list: [1, 2]"


def test_iterable_validator_validates_elements():
    validator = iterable_validator(isinstance_validator(int))

    validator([1, 2, 3])
    with pytest.raises(ConfigValidationError) as exc_info:
        validator([1, 2, 2.5])
    assert (
        str(exc_info.value) == "element 2 is invalid: expected int but got float: 2.5"
    )


@pytest.mark.parametrize(
    "validator, input, err",
    [
        [length_validator(at_least=1), "a", None],
        [length_validator(at_least=1), "", "length must be >= 1 but was 0"],
        [length_validator(greater_than=1), "aa", None],
        [length_validator(greater_than=1), "a", "length must be > 1 but was 1"],
        [length_validator(greater_than=1), "", "length must be > 1 but was 0"],
        [length_validator(at_most=3), "aaa", None],
        [length_validator(at_most=3), "aaaa", "length must be <= 3 but was 4"],
        [length_validator(less_than=3), "aa", None],
        [length_validator(less_than=3), "aaa", "length must be < 3 but was 3"],
    ],
)
def test_length_validator(validator, input, err):
    try:
        validator(input)
        assert err is None
    except ConfigValidationError as e:
        assert str(e) == err


@pytest.mark.parametrize(
    "kwargs, msg",
    [
        [{}, "at least one constraint must be specified"],
        [
            dict(at_least=1, greater_than=0),
            "at_least and greater_than cannot be specified together",
        ],
        [
            dict(at_most=9, less_than=10),
            "less_than and at_most cannot be specified together",
        ],
    ],
)
def test_length_validator_rejects_invalid_bounds(kwargs, msg):
    with pytest.raises(ValueError) as exc_info:
        length_validator(**kwargs)
    assert str(exc_info.value) == msg
