import errno
from http.server import BaseHTTPRequestHandler
import json
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from albion_trade_desk.server_socket import available_server, LoopbackHTTPServer
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server


class PortTests(unittest.TestCase):
    def test_occupied_port_is_never_shared_even_on_windows(self):
        # Simulates another application that enabled SO_REUSEADDR, as Anki may do.
        first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(first.close)
        first.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        first.bind(('127.0.0.1', 0))
        first.listen()
        with self.assertRaises(OSError):
            LoopbackHTTPServer(first.getsockname(), BaseHTTPRequestHandler)

    def test_anki_stays_available_and_app_gets_its_own_port(self):
        class Anki(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"apiVersion":"AnkiConnect v.6"}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass
        anki = LoopbackHTTPServer(('127.0.0.1', 0), Anki)
        original = anki.server_port
        thread = threading.Thread(target=anki.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                app = available_server(lambda port: make_server(Store(directory), port), original)
                self.assertNotEqual(app.server_port, original)
                app_thread = threading.Thread(target=app.serve_forever, daemon=True)
                app_thread.start()
                try:
                    with urlopen(f'http://127.0.0.1:{original}') as r:
                        self.assertEqual(json.load(r)['apiVersion'], 'AnkiConnect v.6')
                    with urlopen(f'http://127.0.0.1:{app.server_port}/api/status') as r:
                        self.assertIn('items', json.load(r))
                finally:
                    app.shutdown(); app_thread.join(); app.server_close(); app.jobs.executor.shutdown()
        finally:
            anki.shutdown(); thread.join(); anki.server_close()

    def test_only_busy_errors_trigger_retry(self):
        ports = []
        def factory(port):
            ports.append(port)
            if len(ports) == 1:
                raise OSError(errno.EADDRINUSE, 'busy')
            return 'listener'
        self.assertEqual(available_server(factory, 8765), 'listener')
        self.assertEqual(ports, [8765, 8766])
        with self.assertRaises(PermissionError):
            available_server(lambda p: (_ for _ in ()).throw(PermissionError('other failure')))
