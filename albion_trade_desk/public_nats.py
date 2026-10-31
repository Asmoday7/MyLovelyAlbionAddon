"""Small read-only NATS Core subscriber. No publish method and no outbound market data.

Public AODP connection settings are from its developer documentation. This is not
a JetStream client. Protocol traffic is limited to CONNECT, SUB and PONG.
"""
import json
from pathlib import Path
import socket
import threading
from .feeds import ingest
from .domain import region

HOST = "nats.albion-online-data.com"
PORTS = {"east": 24222, "west": 4222, "europe": 34222}
TOPICS = ("marketorders.deduped", "markethistories.deduped")
MAX_BODY = 16 * 1024 * 1024


def connect_public(server):
    region(server)
    if Path('/etc/codex/network-policy.json').exists():
        # Managed HTTP policy does not authorize raw TCP or bypassing its sidecar.
        raise RuntimeError("В этой облачной среде NATS требует отдельного TCP-forwarding; прямое подключение не выполняется")
    return socket.create_connection((HOST, PORTS[server]), timeout=30)


def read_messages(connection, on_message, stop):
    """Actual NATS wire protocol, exercised against a recording loopback test broker."""
    stream = connection.makefile('rb')
    try:
        info = stream.readline(16385)
        if not info.startswith(b'INFO ') or len(info) > 16384:
            raise ValueError("NATS не прислал корректный INFO")
        options = json.loads(info[5:])
        if options.get('tls_required'):
            raise ValueError("Этот подписчик не поддерживает TLS-upgrade; подключение остановлено")
        # These are AODP's documented shared PUBLIC credentials, not player credentials.
        config = {"verbose": False, "pedantic": True, "user": "public", "pass": "thenewalbiondata",
                  "name": "AlbionTradeDesk-read-only", "lang": "python", "version": "0.1", "protocol": 1}
        connection.sendall(b'CONNECT ' + json.dumps(config).encode() + b'\r\n')
        for sid, topic in enumerate(TOPICS, 1):
            connection.sendall(f'SUB {topic} {sid}\r\n'.encode())
        while not stop.is_set():
            line = stream.readline(16385)
            if not line:
                raise ConnectionError("Публичный NATS закрыл соединение")
            if len(line) > 16384:
                raise ValueError("Слишком длинная строка NATS")
            if line == b'PING\r\n':
                connection.sendall(b'PONG\r\n')
            elif line.startswith(b'MSG '):
                fields = line.split()
                if len(fields) not in (4, 5):
                    raise ValueError("Некорректный MSG")
                topic, size = fields[1].decode('ascii'), int(fields[-1])
                if topic not in TOPICS or not 0 <= size <= MAX_BODY:
                    raise ValueError("Недопустимая тема или размер NATS")
                payload = stream.read(size)
                if len(payload) != size or stream.read(2) != b'\r\n':
                    raise ValueError("Оборванный MSG")
                on_message(topic, json.loads(payload))
            elif line.startswith(b'-ERR'):
                raise ConnectionError("Публичный NATS отклонил соединение")
            elif not (line in (b'+OK\r\n', b'PONG\r\n') or line.startswith(b'INFO ')):
                raise ValueError("Неподдерживаемый ответ NATS")
    finally:
        stream.close()


class PublicNats:
    def __init__(self, store, connector=connect_public):
        self.store, self.connector = store, connector
        self.lock, self.stop_event = threading.RLock(), threading.Event()
        self.thread, self.connection = None, None
        self.state = {"status": "disabled", "records": 0, "rejected": 0, "error": None}

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self, server):
        region(server)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("Подписчик NATS уже запущен")
            self.stop_event.clear()
            self.state.update(status="connecting", server=server, records=0, rejected=0, error=None)
            self.thread = threading.Thread(target=self.run, args=(server,), daemon=True)
            self.thread.start()
        return self.status()

    def run(self, server):
        delay = 1
        while not self.stop_event.is_set():
            try:
                connection = self.connector(server)
                with self.lock:
                    self.connection = connection
                    self.state.update(status="connected", error=None)
                def receive(topic, payload):
                    try:
                        count = ingest(self.store, topic, payload, server, "aodp-nats")
                        with self.lock:
                            self.state["records"] += count
                    except (ValueError, KeyError, TypeError, OverflowError):
                        with self.lock:
                            self.state["rejected"] += 1
                read_messages(connection, receive, self.stop_event)
            except Exception as exc:
                with self.lock:
                    self.state.update(status="error", error=str(exc))
                if isinstance(exc, RuntimeError):  # A known configuration blocker: no retry loop.
                    break
            finally:
                with self.lock:
                    if self.connection:
                        self.connection.close()
                    self.connection = None
            if self.stop_event.wait(delay):
                break
            delay = min(delay * 2, 60)
        if self.stop_event.is_set():
            with self.lock:
                self.state["status"] = "disabled"

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.connection:
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self.state["status"] = "disabled"
        return self.status()
