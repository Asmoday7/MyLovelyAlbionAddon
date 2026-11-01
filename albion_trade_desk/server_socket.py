"""Exclusive loopback listener and bounded port selection, including Windows."""
import errno
from http.server import ThreadingHTTPServer
import socket


class LoopbackHTTPServer(ThreadingHTTPServer):
    # HTTPServer defaults to SO_REUSEADDR. On Windows this can allow two servers
    # to bind the same address, so a browser may reach AnkiConnect instead of us.
    allow_reuse_address = False
    daemon_threads = False
    block_on_close = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def available_server(factory, preferred=8765, attempts=20):
    if not 0 <= preferred <= 65535:
        raise ValueError('Порт должен быть от 0 до 65535')
    candidates = (0,) if preferred == 0 else range(preferred, min(65536, preferred + attempts))
    last = None
    for candidate in candidates:
        try:
            return factory(candidate)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE and getattr(exc, 'winerror', None) not in (10048, 10013):
                raise
            last = exc
    raise OSError('Не удалось найти свободный локальный порт. Закройте другую копию Trade Desk и повторите запуск.') from last
