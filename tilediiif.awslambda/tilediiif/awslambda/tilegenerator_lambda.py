from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import Executor, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import BoundedSemaphore, Semaphore
from typing import TYPE_CHECKING, Optional, Sequence, TypedDict

import boto3
from boto3.s3.transfer import S3Transfer
from botocore.config import Config
from pydantic import BaseModel
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

if TYPE_CHECKING:
    import mypy_boto3_s3 as s3

MAX_CONCURRENT_SOURCES = 10


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

    # TODO: validate this value. I think 20 should be OK for our use, as we use
    # s3transfer via download_file() upload_file(), and they use 10
    # threads/connections max each.
    boto_config = Config(max_pool_connections=30)
    s3client: s3.Client = boto3.client("s3", config=boto_config)
    s3_download = S3Transfer(client=s3client)
    s3_upload = S3Transfer(client=s3client)
    event = HandleDirectEvent.parse_obj(raw_event)
    source_executor = ThreadPoolExecutor()
    tile_executor = ThreadPoolExecutor()
    concurrent_source_limit = BoundedSemaphore(MAX_CONCURRENT_SOURCES)

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
                        s3_download=s3_download,
                        s3_upload=s3_upload,
                        concurrent_source_limit=concurrent_source_limit,
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
    s3_download: S3Transfer,
    s3_upload: S3Transfer,
    concurrent_source_limit: Semaphore,
    tile_executor: Executor,
) -> Sequence[str]:
    with concurrent_source_limit, tempfile.TemporaryDirectory() as dir_string:
        working_dir = Path(dir_string)
        source_image = working_dir / "source_image"
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
            keyParts = [destination_key_prefix, source_config.identifier, relative_file]
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
