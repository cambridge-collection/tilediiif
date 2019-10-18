from pathlib import Path

import falcon
import pytest
from falcon import testing

from tilediiif.server.config import Config, FileTransmissionType

TEST_DIR = Path(__file__).parent


@pytest.mark.parametrize("url", ["/foo", "/foo/"])
def test_image_resource_base_redirects_to_info_json(client: testing.TestClient, url):
    result: testing.Result = client.simulate_get(url)
    assert result.status == falcon.HTTP_SEE_OTHER
    assert result.headers["location"] == "/foo/info.json"
    assert result.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    "config, sendfile_header_name, info_json_path",
    [
        [
            Config(file_transmission=FileTransmissionType.INDIRECT),
            "X-Accel-Redirect",
            "foo/info.json",
        ],
        [
            Config(
                file_transmission=FileTransmissionType.INDIRECT,
                info_json_path_template="prefix/{identifier}/info.json",
            ),
            "X-Accel-Redirect",
            "prefix/foo/info.json",
        ],
        [
            Config(
                file_transmission=FileTransmissionType.INDIRECT,
                sendfile_header_name="x-sendfile",
            ),
            "x-sendfile",
            "foo/info.json",
        ],
        [
            Config(
                file_transmission=FileTransmissionType.INDIRECT, data_path="/var/images"
            ),
            "X-Accel-Redirect",
            "/var/images/foo/info.json",
        ],
        [
            Config(
                file_transmission=FileTransmissionType.INDIRECT,
                info_json_path_template="{identifier-shard}/{identifier}/" "info.json",
                data_path="/var/images",
            ),
            "X-Accel-Redirect",
            "/var/images/b1/71/foo/info.json",
        ],
    ],
)
def test_image_info_resource_returns_sendfile_header_to_image(
    client, sendfile_header_name, info_json_path
):
    result = client.simulate_get("/foo/info.json")
    assert result.status == falcon.HTTP_OK
    assert result.headers["Access-Control-Allow-Origin"] == "*"
    assert result.headers[sendfile_header_name] == info_json_path


@pytest.mark.parametrize(
    "config",
    [
        Config(
            file_transmission=FileTransmissionType.DIRECT,
            data_path=TEST_DIR,
            info_json_path_template="data/example-file",
        )
    ],
)
def test_direct_transmission_type_responds_with_file_content(client):
    result = client.simulate_get("/foo/info.json")
    assert result.status == falcon.HTTP_OK
    assert result.headers["Access-Control-Allow-Origin"] == "*"
    assert result.content == b"example content\n"


@pytest.mark.parametrize(
    "config",
    [
        Config(
            file_transmission=FileTransmissionType.DIRECT,
            data_path=TEST_DIR,
            info_json_path_template="data/missing-file",
        )
    ],
)
def test_direct_transmission_type_responds_with_404_for_missing_file(client):
    result = client.simulate_get("/foo/info.json")
    assert result.status == falcon.HTTP_NOT_FOUND
    assert result.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    "config",
    [
        Config(
            file_transmission=FileTransmissionType.DIRECT,
            data_path=TEST_DIR,
            info_json_path_template="data",
        )
    ],
)
def test_direct_transmission_type_responds_with_500_for_failed_file_read(
    client, mock_logger_exception
):
    result = client.simulate_get("/foo/info.json")
    assert result.status == falcon.HTTP_INTERNAL_SERVER_ERROR
    assert result.headers["Access-Control-Allow-Origin"] == "*"
    mock_logger_exception.assert_called_once()
    log_args = mock_logger_exception.mock_calls[0][1]
    assert log_args == ("failed to open file: %s", TEST_DIR / "data")


def test_encoded_slashes_in_paths_are_decoded_before_route_matching(client):
    """
    WSGI servers decode the path before passing it to the application. The
    falcon test client also does. See:
    See: https://github.com/falconry/falcon/blob/7372895e/falcon/testing/helpers.py#L129

    As a result, path segment values from the router can never contain a slash.
    """  # noqa: E501
    result = client.simulate_get("/foo%2Dbar/info.json")
    assert result.status == falcon.HTTP_NOT_FOUND


@pytest.mark.parametrize(
    "config", [Config(info_json_path_template=".{identifier}/info.json")]
)
def test_requests_resolving_to_parent_paths_are_rejected(client, mock_logger_warning):
    # This has to be a little contrived because of path slashes being decoded.
    # "." as an identifier becomes ".." when rendered in the template above,
    # which results in the path being rejected.
    result = client.simulate_get("/./info.json")
    assert result.status == falcon.HTTP_BAD_REQUEST
    assert result.headers["Access-Control-Allow-Origin"] == "*"

    mock_logger_warning.assert_called_once()
    log_args = mock_logger_warning.mock_calls[0][1]
    assert log_args[0:2] == (
        "rejected info.json request for invalid path; " "identifier=%r, cause: %s",
        ".",
    )
    assert isinstance(log_args[2], Exception)
