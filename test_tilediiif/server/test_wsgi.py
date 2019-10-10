import importlib
from unittest.mock import patch, sentinel

from tilediiif.server import wsgi


def test_wsgi_module_exposes_application_attribute():
    try:
        with patch('tilediiif.server.api.get_api',
                   return_value=sentinel.api):
            importlib.reload(wsgi)
            assert wsgi.application == sentinel.api
    finally:
        importlib.reload(wsgi)
