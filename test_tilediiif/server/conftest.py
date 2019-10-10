import logging
from unittest.mock import patch

import pytest
from falcon import testing

from tilediiif.server.api import get_api
from tilediiif.server.config import Config


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def client(config):
    return testing.TestClient(get_api(config))


@pytest.fixture
def logger():
    return logging.getLogger('tilediiif.server.resources')


@pytest.yield_fixture
def mock_logger_warning(logger):
    with patch.object(logger, 'warning') as mock:
        yield mock


@pytest.yield_fixture
def mock_logger_exception(logger):
    with patch.object(logger, 'exception') as mock:
        yield mock
