from meinheld import patch
patch.patch_all()
from tilediiif.server.wsgi import application

__all__ = ['application']
