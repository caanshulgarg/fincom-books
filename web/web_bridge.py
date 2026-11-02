"""Runs the unchanged app_server request handler inside the browser (Pyodide).

The browser has no sockets or file locks, so the server is built without binding a port and
each /api request is replayed through the real Handler with in-memory request/response streams.
"""
import io

import app_server


class _NoLock:
    """One browser tab owns its IndexedDB copy; there is no second process to lock out."""
    def __init__(self, path): pass
    def close(self): pass


class _NoSocketServer:
    def __init__(self, address, handler):
        self.server_port = address[1]
        self.handler = handler


app_server.StorageLock = _NoLock
app_server.BooksServer = _NoSocketServer
app_server._fetch_remote_version = lambda: None  # the web edition is always the latest

server = app_server.make_server(3543, '/data/books.sqlite3')


def handle(method, path, body=''):
    data = body.encode('utf-8') if isinstance(body, str) else bytes(body or b'')
    h = server.handler.__new__(server.handler)
    h.server, h.client_address = server, ('127.0.0.1', 0)
    h.rfile, h.wfile = io.BytesIO(data), io.BytesIO()
    h.command, h.path, h.request_version = method, path, 'HTTP/1.1'
    h.requestline = f'{method} {path} HTTP/1.1'
    h.close_connection = True
    h.headers = {'Host': f'127.0.0.1:{server.server_port}', 'Content-Length': str(len(data)),
                 'Content-Type': 'application/json'}
    getattr(h, 'do_' + method)()
    head, _, payload = h.wfile.getvalue().partition(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    headers = dict(line.split(': ', 1) for line in lines[1:] if ': ' in line)
    return int(lines[0].split()[1]), headers, payload
