import json
from enum import Enum
from pathlib import Path

from tilediiif.core.config import Config, ConfigProperty
from tilediiif.core.config.properties import EnumConfigProperty

with open(Path(__file__).parent / "config-schema.json") as f:
    CONFIG_SCHEMA = json.load(f)


class FileTransmissionType(Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"


class ConfigValueEnvars(Enum):
    DATA_PATH = "TILEDIIIF_SERVER_DATA_PATH"
    FILE_TRANSMISSION = "TILEDIIIF_SERVER_FILE_TRANSMISSION"
    SENDFILE_HEADER_NAME = "TILEDIIIF_SERVER_SENDFILE_HEADER_NAME"
    IMAGE_PATH_TEMPLATE = "TILEDIIIF_SERVER_IMAGE_PATH_TEMPLATE"
    INFO_JSON_PATH_TEMPLATE = "TILEDIIIF_SERVER_INFO_JSON_PATH_TEMPLATE"


ConfigValueEnvars.envar_names = frozenset(e.name for e in ConfigValueEnvars)


class ServerConfig(Config):
    json_schema = CONFIG_SCHEMA

    property_definitions = [
        ConfigProperty(
            name="image_path_template",
            default="{identifier}/{region}-{size}-{rotation}-{quality}.{format}",
            envar_name=ConfigValueEnvars.IMAGE_PATH_TEMPLATE.value,
            json_path="tilediiif.server.image-path-template",
        ),
        ConfigProperty(
            name="info_json_path_template",
            default="{identifier}/info.json",
            envar_name=ConfigValueEnvars.INFO_JSON_PATH_TEMPLATE.value,
            json_path="tilediiif.server.info-json-path-template",
        ),
        ConfigProperty(
            name="sendfile_header_name",
            default="X-Accel-Redirect",
            envar_name=ConfigValueEnvars.SENDFILE_HEADER_NAME.value,
            json_path=(
                "tilediiif.server.indirect-file-transmission.sendfile-header-name"
            ),
        ),
        ConfigProperty(
            name="data_path",
            default=".",
            envar_name=ConfigValueEnvars.DATA_PATH.value,
            json_path="tilediiif.server.data-path",
        ),
        EnumConfigProperty(
            name="file_transmission",
            enum_cls=FileTransmissionType,
            default=FileTransmissionType.DIRECT,
            envar_name=ConfigValueEnvars.FILE_TRANSMISSION.value,
            json_path="tilediiif.server.file-transmission",
        ),
    ]
