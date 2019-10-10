import os
from pathlib import Path
from unittest.mock import patch, sentinel

import falcon
import pytest

from tilediiif.server.api import CONFIG_PATH_ENVAR, get_api
from tilediiif.server.config import Config, ConfigError


@pytest.yield_fixture
def mock_config_from_toml_file():
    with patch('tilediiif.server.config.Config.from_toml_file') as mock:
        yield mock


@pytest.yield_fixture
def mock_populate_routes():
    with patch('tilediiif.server.api._populate_routes',
               side_effect=lambda api, _: api) as mock:
        yield mock


@pytest.fixture
def config_path():
    return '/some/path'


@pytest.yield_fixture
def config_path_envar(config_path):
    with patch.dict(os.environ, {CONFIG_PATH_ENVAR: config_path}):
        yield config_path


def test_get_api_returns_falcon_api_instance():
    assert isinstance(get_api(), falcon.API)


@pytest.mark.usefixtures('config_path_envar')
def test_get_api_uses_config_if_specified(mock_config_from_toml_file,
                                          mock_populate_routes):
    config = sentinel.config
    api = get_api(config)
    mock_config_from_toml_file.assert_not_called()
    mock_populate_routes.assert_called_once_with(api, config)


def test_get_api_loads_config_from_envar_location(mock_config_from_toml_file,
                                                  mock_populate_routes,
                                                  config_path_envar):
    api = get_api()
    mock_config_from_toml_file.assert_called_once_with(config_path_envar)
    mock_populate_routes.assert_called_once_with(
        api, mock_config_from_toml_file(config_path_envar))


def test_get_api_uses_default_config_if_no_config_specified(
        mock_config_from_toml_file, mock_populate_routes):
    api = get_api()
    mock_config_from_toml_file.assert_not_called()
    mock_populate_routes.assert_called_once_with(api, Config())


@pytest.mark.parametrize('config_path', [
    str(Path(__file__).parent / 'data/invalid_toml.toml')
])
def test_get_api_throws_config_error_with_invalid_config(config_path_envar):
    with pytest.raises(ConfigError) as exc_info:
        get_api()
    assert 'Unable to parse ' in str(exc_info.value)


@pytest.mark.parametrize('config, msg', [
    [Config(info_json_path_template='{unsupported-placeholder}/info.json'),
     "info-json-path-template is invalid: template contains unexpected "
     "placeholders: 'unsupported-placeholder'"],
    [Config(info_json_path_template='foo/../../{identifier}/info.json'),
     'info-json-path-template is invalid: template contains a ".." (parent) '
     'segment'],
    [Config(info_json_path_template='foo/{identifier/info.json'),
     'info-json-path-template is invalid: Invalid placeholder at offset 4:']
])
def test_get_api_throws_config_error_with_invalid_config_values(config, msg):
    with pytest.raises(ConfigError) as exc_info:
        get_api(config)
    assert msg in str(exc_info.value)
