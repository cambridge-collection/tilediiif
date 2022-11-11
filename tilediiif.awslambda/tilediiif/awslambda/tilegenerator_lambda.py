from __future__ import annotations

import logging
import os

if os.environ.get("LOGLEVEL"):
    logging.getLogger().setLevel(level=os.environ["LOGLEVEL"])
    logging.getLogger(__name__).debug(
        "configured root logger to level %s", os.environ["LOGLEVEL"]
    )

import json
import tempfile
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import BoundedSemaphore, Semaphore
from typing import TYPE_CHECKING, Mapping, Optional, Sequence, TypedDict

import boto3
from boto3.s3.transfer import S3Transfer
from botocore.config import Config
from mypy_boto3_s3 import S3Client
from pydantic import BaseModel
from tilediiif.core.config.core import Config as TilediiifConfig
from tilediiif.core.config.core import ConfigProperty
from tilediiif.core.config.exceptions import ConfigValidationError
from tilediiif.core.config.parsing import simple_parser
from tilediiif.core.config.properties import IntConfigProperty
from tilediiif.core.config.validation import in_validator
from tilediiif.core.templates import Template, parse_template
from tilediiif.tools.dzi import parse_dzi_file
from tilediiif.tools.dzi_generation import ColourConfig, DZIConfig, JPEGConfig, save_dzi
from tilediiif.tools.infojson import get_id_url, info_json_from_dzi
from tilediiif.tools.tilelayout import (
    DEFAULT_FILE_PATH_TEMPLATE,
    create_dzi_tile_layout,
    create_file_via_hardlink,
    get_template_bindings,
    get_templated_dest_path,
    normalise_output_format,
)

from tilediiif.awslambda.capacitylock import CapacityLock

if TYPE_CHECKING:
    import mypy_boto3_s3 as s3

ENVAR_PREFIX = "TILEDIIIF_LAMBDA"
# As well as limiting access by disk capacity, we impose an overall concurrency
# limit, so that we can manage TCP connection pool size, and not consume
# excessive resources if individual requests use small amounts of disk capacity.
DEFAULT_CONCURRENT_SOURCES = 10
# A multiplier used to estimate disk capacity needed to process a source image.
# The size of the source image is multiplied by this to give an upper bound on
# space required.
DEFAULT_SOURCE_SIZE_DISK_CAPACITY_RATIO = 1.8
# Lambdas have 512MB of space in /tmp by default
DEFAULT_DISK_CAPACITY = 512 * 1024 * 1024


def in_interval_validator(lower: Optional[float] = None, upper: Optional[float] = None):
    if lower is None and upper is None:
        raise ValueError("at least one of lower and upper must be specified")

    def validate_in_interval(value: float) -> None:
        if lower is not None and lower > value:
            raise ConfigValidationError(f"value out of range: {value=} be >= {lower}")
        if upper is not None and upper >= value:
            raise ConfigValidationError(f"value out of range: {value=} be <= {upper}")

    return validate_in_interval


class LambdaConfig(TilediiifConfig):
    max_concurrent_sources: int
    source_size_disk_capacity_ratio: float
    max_capacity: int

    json_schema: Mapping[str, object] = {}
    property_definitions = [
        IntConfigProperty(
            "max_concurrent_sources",
            default=DEFAULT_CONCURRENT_SOURCES,
            validate=in_validator(range(1, 101)),
            envar_name=f"{ENVAR_PREFIX}_MAX_CONCURRENT_SOURCES",
        ),
        ConfigProperty(
            "source_size_disk_capacity_ratio",
            default=DEFAULT_SOURCE_SIZE_DISK_CAPACITY_RATIO,
            validate=in_interval_validator(lower=1.0, upper=10.0),
            parse=simple_parser(float),
            envar_name=f"{ENVAR_PREFIX}_SOURCE_SIZE_DISK_CAPACITY_RATIO",
        ),
        IntConfigProperty(
            "max_capacity",
            default=DEFAULT_DISK_CAPACITY,
            validate=in_validator(range(1, 101)),
            envar_name=f"{ENVAR_PREFIX}_MAX_CONCURRENT_SOURCES",
        ),
    ]


class SourceImageReference(BaseModel):
    bucket_name: str
    key: str
    identifier: str


class HandleDirectEvent(BaseModel):
    source_images: Sequence[SourceImageReference]
    iiif_base_url: str
    """The URL that IIIF images will be served under.

    e.g. a iiif_base_url of "https://iiif.example.com/images/" will result in
    an image with identifier "abc1" having URLs such as:

    - https://iiif.example.com/images/abc1/info.json
    - https://iiif.example.com/images/abc1/0,0,510,510/510,/0/default.jpeg
    """
    destination_bucket: str
    destination_key_prefix: Optional[str]


class SourceImageReferenceJson(TypedDict):
    bucket_name: str
    key: str
    identifier: str


class HandleDirectEventJson(TypedDict):
    source_images: Sequence[SourceImageReferenceJson]
    iiif_base_url: str
    destination_bucket: str
    destination_key_prefix: Optional[str]


class GeneratedTiles(TypedDict):
    identifier: str
    keys: Sequence[str]


def handle_direct(
    raw_event: HandleDirectEventJson, context: object
) -> Sequence[GeneratedTiles]:
    """Run the tile generator with domain-specific arguments.

    This handler is used to call the tilediiif tile generator when the caller
    has control over the arguments. For example, from a Step Function workflow,
    or manually from the AWS Console.
    """
    lambda_config = LambdaConfig.from_environ()
    dzi_config = DZIConfig.from_environ()
    tile_encoding_config = JPEGConfig.from_environ()
    colour_config = ColourConfig.from_environ()

    raw_tile_path_template = os.environ.get(
        "TILE_PATH_TEMPLATE", DEFAULT_FILE_PATH_TEMPLATE
    )
    try:
        tile_path_template = parse_template(raw_tile_path_template)
    except ValueError as e:
        raise ValueError(f"invalid TILE_PATH_TEMPLATE: {e}") from e

    # TODO: validate this value. I think 20 should be the lower bound for our
    # use, as we use s3transfer via download_file() upload_file(), and they use
    # 10 threads/connections max each.
    boto_config = Config(max_pool_connections=30)
    s3_client: s3.Client = boto3.client("s3", config=boto_config)
    s3_download = S3Transfer(client=s3_client)
    s3_upload = S3Transfer(client=s3_client)
    event = HandleDirectEvent.parse_obj(raw_event)
    source_executor = ThreadPoolExecutor()
    tile_executor = ThreadPoolExecutor()
    concurrent_source_limit = BoundedSemaphore(lambda_config.max_concurrent_sources)
    disk_capacity_limit = CapacityLock(lambda_config.max_capacity)

    return [
        {"identifier": src.identifier, "keys": keys}
        for (src, keys) in source_executor.map(
            (
                lambda src: (
                    src,
                    fetch_generate_and_upload(
                        source_config=src,
                        id_base_url=event.iiif_base_url,
                        dzi_config=dzi_config,
                        tile_encoding_config=tile_encoding_config,
                        colour_config=colour_config,
                        tile_path_template=tile_path_template,
                        destination_bucket=event.destination_bucket,
                        destination_key_prefix=event.destination_key_prefix,
                        s3_client=s3_client,
                        s3_download=s3_download,
                        s3_upload=s3_upload,
                        concurrent_source_limit=concurrent_source_limit,
                        disk_capacity_limit=disk_capacity_limit,
                        source_size_disk_capacity_ratio=lambda_config.source_size_disk_capacity_ratio,  # noqa: B950
                        tile_executor=tile_executor,
                    ),
                )
            ),
            event.source_images,
        )
    ]


def fetch_generate_and_upload(
    *,
    source_config: SourceImageReference,
    id_base_url: str,
    dzi_config: DZIConfig,
    tile_encoding_config: JPEGConfig,
    colour_config: ColourConfig,
    tile_path_template: Template,
    destination_bucket: str,
    destination_key_prefix: Optional[str],
    s3_client: S3Client,
    s3_download: S3Transfer,
    s3_upload: S3Transfer,
    concurrent_source_limit: Semaphore,
    disk_capacity_limit: CapacityLock,
    source_size_disk_capacity_ratio: float,
    tile_executor: Executor,
) -> Sequence[str]:
    with concurrent_source_limit, tempfile.TemporaryDirectory() as dir_string:
        working_dir = Path(dir_string)
        source_image = working_dir / "source_image"
        source_meta = s3_client.head_object(
            Bucket=source_config.bucket_name,
            Key=source_config.key,
        )
        source_size = max(1, source_meta.get("ContentLength"))
        capacity_required = int(source_size * source_size_disk_capacity_ratio)
        assert capacity_required > 0
        with disk_capacity_limit.acquire(capacity_required):
            s3_download.download_file(
                bucket=source_config.bucket_name,
                key=source_config.key,
                filename=str(source_image),
            )

            iiif_tiles_dir = generate_tiles(
                source_config=source_config,
                source_image=source_image,
                id_base_url=id_base_url,
                dzi_config=dzi_config,
                tile_encoding_config=tile_encoding_config,
                colour_config=colour_config,
                tile_path_template=tile_path_template,
                working_dir=working_dir,
            )

            def upload(file: Path) -> str:
                relative_file = file.relative_to(iiif_tiles_dir)
                keyParts = [
                    destination_key_prefix,
                    source_config.identifier,
                    relative_file,
                ]
                destination_key = str(Path(*[x for x in keyParts if x is not None]))
                s3_upload.upload_file(
                    bucket=destination_bucket, key=destination_key, filename=str(file)
                )
                return destination_key

            return list(tile_executor.map(upload, sorted(iiif_tiles_dir.glob("**/*"))))


def generate_tiles(
    *,
    source_config: SourceImageReference,
    source_image: Path,
    id_base_url: str,
    dzi_config: DZIConfig,
    tile_encoding_config: JPEGConfig,
    colour_config: ColourConfig,
    tile_path_template: Template,
    working_dir: Path,
) -> Path:
    dest_dzi = working_dir / "image"
    save_dzi(
        src_image=source_image,
        dest_dzi=dest_dzi,
        dzi_config=dzi_config,
        tile_encoding_config=tile_encoding_config,
        colour_config=colour_config,
    )

    try:
        with open(f"{dest_dzi}.dzi", "rb") as f:
            dzi_meta = parse_dzi_file(f)
    except Exception as e:
        raise RuntimeError(f"Failed to parse generated .dzi file: {e}") from e

    get_dest_path = partial(
        get_templated_dest_path,
        tile_path_template,
        bindings_for_tile=partial(
            get_template_bindings, format=normalise_output_format(dzi_meta["format"])
        ),
    )

    iiif_tiles_dir = working_dir / "iiif-tiles"
    iiif_tiles_dir.mkdir()
    create_dzi_tile_layout(
        dzi_path=Path(f"{dest_dzi}.dzi"),
        dzi_meta=dzi_meta,
        get_dest_path=get_dest_path,
        create_file=create_file_via_hardlink,
        target_directory=iiif_tiles_dir,
    )

    id_url = get_id_url(id_base_url, source_config.identifier)
    json_meta = info_json_from_dzi(dzi_meta, id_url=id_url)
    info_json_file = iiif_tiles_dir / "info.json"
    info_json_file.write_text(json.dumps(json_meta))

    return iiif_tiles_dir
