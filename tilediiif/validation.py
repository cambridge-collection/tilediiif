from functools import partial


def require(validator, **kwargs):
    for name, value in kwargs.items():
        validator(value, name)


def positive_int(value, name):
    if int(value) != value or value < 0:
        raise ValueError(f'{name} must be an int >=0; got: {value!r}')


def positive_non_zero_int(value, name):
    if int(value) != value or value < 1:
        raise ValueError(f'{name} must be an int >=1; got: {value!r}')


require_positive_int = partial(require, positive_int)
require_positive_non_zero_int = partial(require, positive_non_zero_int)
