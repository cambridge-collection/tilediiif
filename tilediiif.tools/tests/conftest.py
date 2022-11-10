import warnings

import pytest

from tilediiif.tools.dzi_generation import (
    DZIGenerationWarning,
    register_default_warnings_filters,
)


@pytest.fixture(autouse=True)
def default_warnings_filters():
    assert not [
        filter for filter in warnings.filters if filter[2] == DZIGenerationWarning
    ]
    register_default_warnings_filters()
