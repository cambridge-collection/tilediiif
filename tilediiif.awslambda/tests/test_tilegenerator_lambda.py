from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

import boto3
import pytest
from moto import mock_s3  # type: ignore
from syrupy.assertion import SnapshotAssertion
from tilediiif.core.config.exceptions import ConfigParseError

ROOT = Path(__file__).parents[2]
TEST_IMAGES = ROOT / "tilediiif.tools/integration_tests/data/images"

if TYPE_CHECKING:
    from mypy_boto3_s3 import Client

    from tilediiif.awslambda.tilegenerator_lambda import (
        GeneratedTiles,
        HandleDirectEventJson,
        SourceImageReferenceJson,
    )


@pytest.fixture
def aws_credentials(monkeypatch: pytest.MonkeyPatch):
    """Mocked AWS Credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def mock_s3_enabled(aws_credentials):
    # mock_s3() mocks the boto3 s3 APIs so that they can be used without without
    # triggering network requests. e.g. calls to store and fetch data work as
    # normal, but only with changes made in the tests being visible.
    with mock_s3():
        yield


@pytest.fixture
def handle_direct(mock_s3_enabled):
    from tilediiif.awslambda.tilegenerator_lambda import handle_direct

    return handle_direct


@pytest.fixture
def s3client(mock_s3_enabled) -> Client:
    return boto3.client("s3")


@pytest.fixture
def source_bucket(s3client: Client) -> str:
    name = "SourceBucket"
    s3client.create_bucket(Bucket=name)
    return name


@pytest.fixture
def dest_bucket(s3client: Client) -> str:
    name = "DestBucket"
    s3client.create_bucket(Bucket=name)
    return name


@pytest.fixture
def source_pears_small(s3client: Client, source_bucket: str) -> dict[str, str]:
    s3client.upload_file(
        Bucket=source_bucket,
        Filename=str(TEST_IMAGES / "pears_small_srgb.jpg"),
        Key="A123-Thing/PHOTO-42.jpg",
    )
    return {
        "bucket_name": source_bucket,
        "key": "A123-Thing/PHOTO-42.jpg",
        "identifier": "A123-Thing_42",
    }


@pytest.fixture
def source_sunset_p3(s3client: Client, source_bucket: str) -> SourceImageReferenceJson:
    s3client.upload_file(
        Bucket=source_bucket,
        Filename=str(TEST_IMAGES / "Sunset-P3.jpg"),
        Key="A123-Thing/PHOTO-55.jpg",
    )
    return {
        "bucket_name": source_bucket,
        "key": "A123-Thing/PHOTO-55.jpg",
        "identifier": "A123-Thing_55",
    }


@pytest.fixture
def input_event(
    dest_bucket: str,
    source_pears_small: SourceImageReferenceJson,
    source_sunset_p3: SourceImageReferenceJson,
) -> HandleDirectEventJson:
    return {
        "source_images": [source_pears_small, source_sunset_p3],
        "iiif_base_url": "https://iiif.testing.test/images/",
        "destination_bucket": "DestBucket",
        "destination_key_prefix": "ExcellentImages",
    }


def test_handle_direct__default_options(
    handle_direct: Callable[[HandleDirectEventJson, object], Sequence[GeneratedTiles]],
    input_event: HandleDirectEventJson,
    snapshot: SnapshotAssertion,
) -> None:
    results = handle_direct(input_event, {})

    assert [result["identifier"] for result in results] == [
        "A123-Thing_42",
        "A123-Thing_55",
    ]
    assert results == snapshot


def test_handle_direct__non_default_options(
    handle_direct: Callable[[HandleDirectEventJson, object], Sequence[GeneratedTiles]],
    input_event: HandleDirectEventJson,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    monkeypatch.setenv("DZI_TILES_DZI_TILE_SIZE", "510")  # 512 with overlap

    input_event["destination_key_prefix"] = "MyPrefix/Stuff"
    results = handle_direct(input_event, {})

    assert [result["identifier"] for result in results] == [
        "A123-Thing_42",
        "A123-Thing_55",
    ]
    assert results == snapshot


@pytest.mark.parametrize(
    "envar_name, envar_value, err_message",
    [
        (
            "DZI_TILES_JPEG_QUALITY",
            "invalid",
            (
                "Failed to parse config value for quality: Failed to parse config value"
                " for quality: invalid literal for int() with base 10: 'invalid"
            ),
        ),
        (
            "DZI_TILES_COLOUR_TRANSFORM_INTENT",
            "invalid",
            "'invalid' is not a valid RenderingIntent",
        ),
        (
            "DZI_TILES_DZI_TILE_SIZE",
            "invalid",
            (
                "Failed to parse config value for tile_size: invalid literal for int()"
                " with base 10: 'invalid'"
            ),
        ),
    ],
)
def test_handle_direct__reads_configuration_from_envars(
    envar_name: str,
    envar_value: str,
    err_message: str,
    handle_direct: Callable[[HandleDirectEventJson, object], Sequence[GeneratedTiles]],
    input_event: HandleDirectEventJson,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(envar_name, envar_value)

    with pytest.raises(ConfigParseError) as exc_info:
        handle_direct(input_event, {})

    assert err_message in str(exc_info.value)
