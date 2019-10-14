from pathlib import Path
from unittest.mock import patch

import pytest
import toml

from tilediiif.server.config import Config, ConfigError, FileTransmissionType

DATA_DIR = Path(__file__).parent / 'data'


@pytest.fixture
def config_toml_path():
    return DATA_DIR / 'config.toml'


@pytest.fixture
def config_toml_expected_config():
    return Config(
        sendfile_header_name='X-File',
        data_path='/var/my-images',
        file_transmission=FileTransmissionType.INDIRECT,
        image_path_template=(
            'foo-{identifier-shard}/{identifier}/'
            '{image-shard}/{region}-{size}-{rotation}-{quality}.{format}'),
        info_json_path_template='foo-{identifier-shard}/{identifier}/info.json'
    )


def test_config_creation_from_kwargs(config_toml_expected_config):
    c = config_toml_expected_config
    assert c.sendfile_header_name == 'X-File'
    assert c.data_path == '/var/my-images'
    assert c.file_transmission == FileTransmissionType.INDIRECT
    assert c.image_path_template == (
        'foo-{identifier-shard}/{identifier}/'
        '{image-shard}/{region}-{size}-{rotation}-{quality}.{format}')
    assert c.info_json_path_template == (
        'foo-{identifier-shard}/{identifier}/info.json')


def test_config_from_toml_file(config_toml_path, config_toml_expected_config):
    assert (Config.from_toml_file(config_toml_path) ==
            config_toml_expected_config)


def test_config_from_toml_uses_from_json(config_toml_path):
    with patch('tilediiif.server.config.Config.from_json') as from_json:
        Config.from_toml_file(config_toml_path)

    from_json.assert_called_once_with(toml.load(config_toml_path),
                                      name=str(config_toml_path))


@pytest.mark.parametrize('path, msg', [
    [DATA_DIR / 'missing.toml',
     f"Unable to read {DATA_DIR / 'missing.toml'}: "],
    [DATA_DIR / 'invalid_toml.toml',
     f"Unable to parse {DATA_DIR / 'invalid_toml.toml'} as TOML: "]
])
def test_config_from_toml_file_rejects_invalid_config_files(path, msg):
    with pytest.raises(ConfigError) as exc_info:
        Config.from_toml_file(path)
    assert msg in str(exc_info.value)


@pytest.mark.parametrize('config, name, msg', [
    [{'foo': 123}, None,
     "Configuration data is invalid: 'tilediiif' is a required property"],
    [{'foo': 123}, '/some/file',
     "Configuration data from /some/file is invalid: "
     "'tilediiif' is a required property"],
    [{'tilediiif': {'server': {'unknown': 'foo'}}}, None,
     "Configuration data is invalid: Additional properties are not allowed "
     "('unknown' was unexpected)"],
    [{'tilediiif': {'server': {
        'indirect-file-transmission': {
            'unknown': 'foo'
        }
    }}}, None,
        "Configuration data is invalid: Additional properties are not allowed "
        "('unknown' was unexpected)"],
])
def test_config_from_json_rejects_invalid_config_data(config, name, msg):
    with pytest.raises(ConfigError) as exc_info:
        Config.from_json(config, name=name)
    assert msg in str(exc_info.value)
