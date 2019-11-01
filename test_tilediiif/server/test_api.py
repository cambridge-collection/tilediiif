from pathlib import Path
from unittest.mock import patch, sentinel

import falcon
import pytest

from tilediiif.config import ConfigError
from tilediiif.server.api import CONFIG_PATH_ENVAR, get_api
from tilediiif.server.config import ConfigValueEnvars, ServerConfig


@pytest.yield_fixture
def mock_config_from_toml_file():
    with patch("tilediiif.server.config.Config.from_toml_file") as mock:
        yield mock


@pytest.yield_fixture
def mock_config_from_environ():
    with patch("tilediiif.server.config.Config.from_environ") as mock:
        yield mock


@pytest.yield_fixture
def mock_populate_routes():
    with patch(
        "tilediiif.server.api._populate_routes", side_effect=lambda api, _: api
    ) as mock:
        yield mock


@pytest.fixture
def config_path():
    return "/some/path"


@pytest.fixture
def config_path_envar(monkeypatch, config_path):
    monkeypatch.setenv(CONFIG_PATH_ENVAR, config_path)
    return config_path


@pytest.fixture
def no_config_path_envar(monkeypatch):
    monkeypatch.delenv(CONFIG_PATH_ENVAR, config_path)


@pytest.fixture
def no_config_value_envars(monkeypatch):
    for name in ConfigValueEnvars.envar_names:
        monkeypatch.delenv(name, raising=False)


def test_get_api_returns_falcon_api_instance():
    assert isinstance(get_api(), falcon.API)


@pytest.mark.usefixtures("config_path_envar")
def test_get_api_uses_config_if_specified(
    mock_config_from_toml_file, mock_config_from_environ, mock_populate_routes
):
    config = sentinel.config
    api = get_api(config)
    mock_config_from_toml_file.assert_not_called()
    mock_config_from_environ.assert_not_called()
    mock_populate_routes.assert_called_once_with(api, config)


@pytest.mark.usefixtures("no_config_value_envars")
def test_get_api_loads_config_from_envar_location_and_envar_values(
    mock_config_from_toml_file,
    mock_config_from_environ,
    mock_populate_routes,
    config_path_envar,
):
    mock_config_from_toml_file.return_value = ServerConfig(data_path="foo")
    mock_config_from_environ.return_value = ServerConfig(sendfile_header_name="bar")

    api = get_api()
    mock_config_from_toml_file.assert_called_once_with(config_path_envar)
    mock_config_from_environ.assert_called_once()
    mock_populate_routes.assert_called_once_with(
        api, ServerConfig(data_path="foo", sendfile_header_name="bar")
    )


def test_get_api_uses_default_config_if_no_config_specified(
    mock_config_from_toml_file, mock_populate_routes
):
    api = get_api()
    mock_config_from_toml_file.assert_not_called()
    mock_populate_routes.assert_called_once_with(api, ServerConfig())


def test_get_api_throws_config_error_with_invalid_config(monkeypatch):
    monkeypatch.setenv(
        CONFIG_PATH_ENVAR, str(Path(__file__).parent / "data/invalid_toml.toml")
    )

    with pytest.raises(ConfigError) as exc_info:
        get_api()
    assert "Unable to parse " in str(exc_info.value)


@pytest.mark.parametrize(
    "config, msg",
    [
        [
            ServerConfig(info_json_path_template="{unsupported-placeholder}/info.json"),
            "info-json-path-template is invalid: template contains unexpected "
            "placeholders: 'unsupported-placeholder'",
        ],
        [
            ServerConfig(info_json_path_template="foo/../../{identifier}/info.json"),
            'info-json-path-template is invalid: template contains a ".." (parent) '
            "segment",
        ],
        [
            ServerConfig(info_json_path_template="foo/{identifier/info.json"),
            "info-json-path-template is invalid: Invalid placeholder at offset 4:",
        ],
    ],
)
def test_get_api_throws_config_error_with_invalid_config_values(config, msg):
    with pytest.raises(ConfigError) as exc_info:
        get_api(config)
    assert msg in str(exc_info.value)
