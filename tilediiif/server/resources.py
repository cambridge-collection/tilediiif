from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Callable

import falcon

from tilediiif.server.logic import IIIFImageRequest

LOG = getLogger(__name__)


def access_control_allow_all(
    req: falcon.Request, resp: falcon.Response, resource, params
):
    # The IIIF image API (particularly the metadata resource) is accessed via
    # browser AJAX requests, so CORS header is required.
    resp.set_header("Access-Control-Allow-Origin", "*")


class DirectFileTransmitter:
    def __call__(self, path: Path, resp: falcon.Response):
        try:
            f = open(path, "rb")
        except FileNotFoundError as e:
            raise falcon.HTTPNotFound() from e
        except OSError:
            LOG.exception("failed to open file: %s", path)
            raise falcon.HTTPInternalServerError()
        resp.stream = f
        resp.content_type = resp.options.static_media_types.get(
            path.suffix, "application/octet-stream"
        )


@dataclass
class IndirectFileTransmitter:
    sendfile_header_name: str

    def __call__(self, path: Path, resp: falcon.Response):
        resp.set_header(self.sendfile_header_name, str(path))


@dataclass
class IIIFImageMetadataResource:
    transmit_file: Callable[[str, falcon.Response], None]
    get_info_json_path: Callable[[str], str]

    @falcon.before(access_control_allow_all)
    def on_get(
        self, req: falcon.Request, resp: falcon.Response, identifier: str, resource: str
    ):
        if resource == "":
            return self.on_get_base(req, resp, identifier)
        if resource != "info.json":
            raise falcon.HTTPNotFound()

        try:
            info_json_path = self.get_info_json_path(identifier)
        except ValueError as e:
            LOG.warning(
                "rejected info.json request for invalid path; "
                "identifier=%r, cause: %s",
                identifier,
                e,
            )
            raise falcon.HTTPBadRequest() from e
        self.transmit_file(info_json_path, resp)

    @falcon.before(access_control_allow_all)
    def on_get_base(self, req: falcon.Request, resp: falcon.Response, identifier: str):
        raise falcon.HTTPSeeOther(location=f"/{identifier}/info.json")


@dataclass
class IIIFImageResource:
    transmit_file: Callable[[str, falcon.Response], None]
    get_image_path: Callable[[str, IIIFImageRequest], str]

    @falcon.before(access_control_allow_all)
    def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        identifier: str,
        resource: str,
        size: str,
        rotation: str,
        quality: str,
        format: str,
    ):
        # We have to name the segment under {identifier} as {resource} as
        # it occurs in the info.json route too, and falcon complains if
        # segments at the same position have different names...
        region = resource

        image_request_string = f"{region}/{size}/{rotation}/{quality}.{format}"
        try:
            image_request = IIIFImageRequest.parse(
                region=region,
                size=size,
                rotation=rotation,
                quality=quality,
                format=format,
            )
        except ValueError as e:
            raise falcon.HTTPBadRequest(description=str(e))

        # Only process normalised request forms
        canonical_image_request = image_request.canonical()
        normalised_image_request_string = str(canonical_image_request)

        if image_request_string != normalised_image_request_string:
            raise falcon.HTTPPermanentRedirect(
                location=f"/{identifier}/{normalised_image_request_string}"
            )

        try:
            image_path = self.get_image_path(identifier, canonical_image_request)
        except ValueError as e:
            LOG.warning(
                "rejected image request for invalid path; "
                "identifier=%r, image request=%r cause: %s",
                identifier,
                canonical_image_request,
                e,
            )
            raise falcon.HTTPBadRequest() from e
        self.transmit_file(image_path, resp)
