from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Callable

import falcon

LOG = getLogger(__name__)


class DirectFileTransmitter:
    def __call__(self, path: Path, resp: falcon.Response):
        path = str(path)
        try:
            f = open(path, 'rb')
        except FileNotFoundError as e:
            raise falcon.HTTPNotFound() from e
        except OSError:
            LOG.exception('failed to open file: %s', path)
            raise falcon.HTTPInternalServerError()
        resp.stream = f


@dataclass
class IndirectFileTransmitter:
    sendfile_header_name: str

    def __call__(self, path: Path, resp: falcon.Response):
        resp.set_header(self.sendfile_header_name, str(path))


@dataclass
class IIIFImageMetadataResource:
    transmit_file: Callable[[str, falcon.Response], None]
    get_info_json_path: Callable[[str], str]

    def on_get(self, req: falcon.Request, resp: falcon.Response,
               identifier: str, resource: str):
        if resource == '':
            return self.on_get_base(req, resp, identifier)
        if resource != 'info.json':
            raise falcon.HTTPNotFound()

        try:
            info_json_path = self.get_info_json_path(identifier)
        except ValueError as e:
            LOG.warn('rejected info.json request for invalid path; '
                     'identifier=%r, cause: %s', identifier, e)
            raise falcon.HTTPBadRequest() from e
        self.transmit_file(info_json_path, resp)

    def on_get_base(self, req: falcon.Request, resp: falcon.Response,
                    identifier: str):
        raise falcon.HTTPSeeOther(location=f'/{identifier}/info.json')
