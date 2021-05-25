from pathlib import Path

import falcon
import pytest

from tilediiif.server.config import FileTransmissionType, ServerConfig

DATA_DIR = Path(__file__).parent / "data"
PEARS_TILES = DATA_DIR / "pears_small_size512"

INDIRECT_CONFIG = ServerConfig(
    file_transmission=FileTransmissionType.INDIRECT, data_path=str(DATA_DIR)
)
DIRECT_CONFIG = ServerConfig(data_path=str(DATA_DIR))


def _assert_response_has_cors_header(result):
    assert result.headers["Access-Control-Allow-Origin"] == "*"


@pytest.fixture
def config():
    # Use indirect responses by default when testing
    return INDIRECT_CONFIG


@pytest.fixture
def response_body(response_body_path):
    with open(response_body_path, "rb") as f:
        return f.read()


@pytest.mark.parametrize(
    "url, redirect_location",
    [
        # IIIF Image spec canonicalisation applied to absolute size: 5,5 -> 5,
        ["/imgid/0,0,10,10/5,5/0/default.jpg", "/imgid/0,0,10,10/5,/0/default.jpg"],
        # Not mentioned in the spec, but real number normalisation from 0.0 -> 0
        ["/imgid/full/full/0.0/default.jpg", "/imgid/full/full/0/default.jpg"],
        # Real number normalisation: 1.1000 -> 1.1
        ["/imgid/full/full/1.1000/default.jpg", "/imgid/full/full/1.1/default.jpg"],
    ],
)
def test_non_normalised_requests_are_redirected_to_normalised(
    client, url, redirect_location
):
    result = client.simulate_get(url)
    _assert_response_has_cors_header(result)
    assert result.status == falcon.HTTP_PERMANENT_REDIRECT
    assert result.headers["location"] == redirect_location


@pytest.mark.parametrize(
    "config, url, sendfile_name, sendfile_value",
    [
        [
            INDIRECT_CONFIG.merged_with(
                ServerConfig(sendfile_header_name="X-Sendfile")
            ),
            "/imgid/full/full/0/default.jpg",
            "X-Sendfile",
            DATA_DIR / "imgid/full-full-0-default.jpg",
        ],
        [
            INDIRECT_CONFIG,
            "/imgid/full/full/0/default.jpg",
            "X-Accel-Redirect",
            DATA_DIR / "imgid/full-full-0-default.jpg",
        ],
        [
            INDIRECT_CONFIG.merged_with(
                ServerConfig(
                    image_path_template="{identifier-shard}/{identifier}/{image-shard}/"
                    "{region}-{size}-{rotation}-{quality}.{format}"
                )
            ),
            "/imgid/full/full/0/default.jpg",
            "X-Accel-Redirect",
            DATA_DIR / "03/a6/imgid/88/full-full-0-default.jpg",
        ],
    ],
)
def test_normalised_requests_receive_expected_indirect_response(
    client, url, sendfile_name, sendfile_value
):
    result = client.simulate_get(url)
    _assert_response_has_cors_header(result)
    assert result.status == falcon.HTTP_OK
    assert result.headers[sendfile_name] == str(sendfile_value)


@pytest.mark.parametrize("config", [DIRECT_CONFIG])
@pytest.mark.parametrize(
    "url, response_body_path",
    [
        [
            "/pears_small_size512/0,0,1000,750/500,/0/default.jpg",
            PEARS_TILES / "0,0,1000,750-500,-0-default.jpg",
        ],
        [
            "/pears_small_size512/0,0,512,512/512,/0/default.jpg",
            PEARS_TILES / "0,0,512,512-512,-0-default.jpg",
        ],
        [
            "/pears_small_size512/0,512,512,238/512,/0/default.jpg",
            PEARS_TILES / "0,512,512,238-512,-0-default.jpg",
        ],
        [
            "/pears_small_size512/512,0,488,512/488,/0/default.jpg",
            PEARS_TILES / "512,0,488,512-488,-0-default.jpg",
        ],
        [
            "/pears_small_size512/512,512,488,238/488,/0/default.jpg",
            PEARS_TILES / "512,512,488,238-488,-0-default.jpg",
        ],
    ],
)
def test_normalised_requests_receive_expected_direct_response(
    client, url, response_body
):
    result = client.simulate_get(url)
    _assert_response_has_cors_header(result)
    assert result.status == falcon.HTTP_OK
    assert result.headers["content-type"] == "image/jpeg"
    assert result.content == response_body
