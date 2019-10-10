import os
from pathlib import Path

import falcon

from .config import Config, ConfigError, FileTransmissionType
from .logic import (
    get_info_json_path_renderer)
from .resources import (
    DirectFileTransmitter, IIIFImageMetadataResource,
    IndirectFileTransmitter)
from .uris import IIIF_IMAGE_INFO, IIIF_IMAGE_INFO_BASE
from ..tilelayout import TemplateError

CONFIG_PATH_ENVAR = 'TILEDIIIF_SERVER_CONFIG'


def get_api(config: Config = None):
    if config is None:
        config_path = os.environ.get(CONFIG_PATH_ENVAR)
        if config_path is not None:
            config = Config.from_toml_file(config_path)
        else:
            config = Config()
    api = falcon.API()

    return _populate_routes(api, config)


def _populate_routes(api, config: Config):
    if config.file_transmission == FileTransmissionType.DIRECT:
        transmit_file = DirectFileTransmitter()
    else:
        transmit_file = IndirectFileTransmitter(config.sendfile_header_name)

    base_path = Path(config.data_path)
    try:
        get_info_json_path = get_info_json_path_renderer(
            base_path, config.info_json_path_template)
    except TemplateError as e:
        raise ConfigError(f'info-json-path-template is invalid: {e}') from e

    image_metadata = IIIFImageMetadataResource(
        transmit_file=transmit_file,
        get_info_json_path=get_info_json_path)
    api.add_route(IIIF_IMAGE_INFO, image_metadata)
    api.add_route(IIIF_IMAGE_INFO_BASE, image_metadata, suffix='base')

    return api
