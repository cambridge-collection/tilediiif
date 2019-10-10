import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import toml
from jsonschema import validate, ValidationError

with open(Path(__file__).parent / 'config-schema.json') as f:
    CONFIG_SCHEMA = json.load(f)


class ConfigError(ValueError):
    pass


class FileTransmissionType(Enum):
    DIRECT = 'direct'
    INDIRECT = 'indirect'


@dataclass
class Config:
    image_path_template: str = (
        '{identifier-shard}/{identifier}/'
        '{image-shard}/{region}-{size}-{rotation}-{quality}.{format}')
    info_json_path_template: str = '{identifier}/info.json'
    sendfile_header_name: str = 'X-Accel-Redirect'
    data_path: str = '.'
    file_transmission: FileTransmissionType = FileTransmissionType.DIRECT

    @staticmethod
    def from_toml_file(f):
        try:
            data = toml.load(f)
        except toml.TomlDecodeError as e:
            raise ConfigError(f'Unable to parse {get_name(f)} as TOML: {e}'
                              ) from e
        except OSError as e:
            raise ConfigError(f'Unable to read {get_name(f)}: {e}') from e
        return Config.from_json(data, name=get_name(f))

    @staticmethod
    def from_json(obj, name=None):
        try:
            validate(obj, schema=CONFIG_SCHEMA)
        except ValidationError as e:
            prefix = ('Configuration data is invalid' if name is None else
                      f'Configuration data from {name} is invalid')
            raise ConfigError(f'{prefix}: {e}') from e

        config = obj['tilediiif']['server']
        return Config(
            sendfile_header_name=config.get('indirect-file-transmission', {})
            .get('sendfile-header-name'),
            data_path=config.get('data-path'),
            file_transmission=(
                FileTransmissionType(config['file-transmission'])
                if 'file-transmission' in config else None),
            image_path_template=config.get('image-path-template'),
            info_json_path_template=config.get('info-json-path-template')
        )


def get_name(f):
    if isinstance(f, (str, Path)):
        return str(f)
    if hasattr(f, 'name'):
        return f.name
    return str(f)
