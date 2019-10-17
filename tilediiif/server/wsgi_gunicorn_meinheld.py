from meinheld import patch

from tilediiif.server.wsgi import application

__all__ = ['application']

patch.patch_all()
