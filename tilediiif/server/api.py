import os
from pathlib import Path

import falcon

from tilediiif.config import ConfigError
from tilediiif.server.config import FileTransmissionType, ServerConfig
from tilediiif.server.resources import (
    DirectFileTransmitter,
    IIIFImageMetadataResource,
    IIIFImageResource,
    IndirectFileTransmitter,
)
from tilediiif.server.uris import IIIF_IMAGE, IIIF_IMAGE_INFO, IIIF_IMAGE_INFO_BASE
from tilediiif.templates import (
    TemplateError,
    get_image_path_renderer,
    get_info_json_path_renderer,
)

CONFIG_PATH_ENVAR = "TILEDIIIF_SERVER_CONFIG"


def get_api(config: ServerConfig = None):
    if config is None:
        config_path = os.environ.get(CONFIG_PATH_ENVAR)
        if config_path is not None:
            config = ServerConfig.from_toml_file(config_path)
        else:
            config = ServerConfig()

        config = config.merged_with(ServerConfig.from_environ())
    api = falcon.API()

    return _populate_routes(api, config)


def _populate_routes(api, config: ServerConfig):
    if config.file_transmission == FileTransmissionType.DIRECT:
        transmit_file = DirectFileTransmitter()
    else:
        transmit_file = IndirectFileTransmitter(config.sendfile_header_name)

    base_path = Path(config.data_path)
    try:
        get_info_json_path = get_info_json_path_renderer(
            base_path, config.info_json_path_template
        )
    except TemplateError as e:
        raise ConfigError(f"info-json-path-template is invalid: {e}") from e

    image_metadata = IIIFImageMetadataResource(
        transmit_file=transmit_file, get_info_json_path=get_info_json_path
    )
    api.add_route(IIIF_IMAGE_INFO, image_metadata)
    api.add_route(IIIF_IMAGE_INFO_BASE, image_metadata, suffix="base")

    try:
        get_image_path = get_image_path_renderer(base_path, config.image_path_template)
    except TemplateError as e:
        raise ConfigError(f"image-path-template is invalid: {e}") from e

    image = IIIFImageResource(
        transmit_file=transmit_file, get_image_path=get_image_path
    )
    api.add_route(IIIF_IMAGE, image)

    return api
