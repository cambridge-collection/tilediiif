from collections import Counter
from typing import Iterable, Sized

from tilediiif.config.core import ConfigValidationError


def isinstance_validator(cls):
    def validate_isinstance(value):
        if not isinstance(value, cls):
            raise ConfigValidationError(
                f"expected a {cls.__qualname__} but got a {type(value).__qualname__}: "
                f"{value!r}"
            )

    return validate_isinstance


def iterable_validator(element_validator=None, iterable_type=Iterable):
    assert issubclass(iterable_type, Iterable)
    validate_iterable_type = isinstance_validator(iterable_type)

    def validate_iterable(value):
        validate_iterable_type(value)
        if element_validator is not None:
            for i, e in enumerate(value):
                try:
                    element_validator(e)
                except ConfigValidationError as e:
                    raise ConfigValidationError(f"element {i} is invalid: {e}")

    return validate_iterable


def in_validator(group):
    def validate_in(value):
        if value not in group:
            raise ConfigValidationError(f"{value!r} is not in {group}")

    return validate_in


def all_validator(*validators):
    def validate_all(value):
        for validator in validators:
            validator(value)

    return validate_all


validate_string = isinstance_validator(str)


def validate_no_duplicates(value):
    if not isinstance(value, (Iterable, Sized)):
        raise ValueError(f"{value!r} is not a Sized Iterable")
    counts = Counter(value)
    if len(set(value)) != len(value):
        duplicates = [
            f"{val!r} appears {count} times"
            for val, count in counts.most_common()
            if count > 1
        ]
        raise ConfigValidationError(
            f"duplicates are not allowed: {', '.join(duplicates)}"
        )
