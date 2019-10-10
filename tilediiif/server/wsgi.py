from tilediiif.server.api import get_api

__all__ = ['application']

application = get_api()

if __name__ == '__main__':
    from wsgiref import simple_server
    httpd = simple_server.make_server('127.0.0.1', 8000, application)
    httpd.serve_forever()
