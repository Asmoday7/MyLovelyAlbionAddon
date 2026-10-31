import json
import logging
import mimetypes
import sqlite3
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from .server_socket import LoopbackHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from . import __version__, analytics, ingestion
from .domain import SERVERS, MARKETS, quality, region, location
from .export import csv_bytes, xlsx_bytes
from .transport import HttpClient, sync_catalog, refresh_market
from .private_scanner import PrivateScanner
from .public_nats import PublicNats

STATIC = Path(__file__).with_name("static")
LOG = logging.getLogger(__name__)


class Jobs:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-sync")
        self.lock = threading.Lock()
        self.entries = {}

    def submit(self, function):
        with self.lock:
            if any(j["status"] in ("queued", "running") for j in self.entries.values()):
                raise ValueError("Обновление уже идёт. Дождитесь его завершения")
            uid = uuid.uuid4().hex
            self.entries = dict(list(self.entries.items())[-19:])
            self.entries[uid] = {"id": uid, "status": "queued"}

        def run():
            with self.lock:
                self.entries[uid]["status"] = "running"
            try:
                result = function()
                with self.lock:
                    self.entries[uid].update(status="done", result=result)
            except Exception as exc:
                LOG.exception("Background update failed")
                with self.lock:
                    self.entries[uid].update(status="error", error=str(exc))
        self.executor.submit(run)
        return {"id": uid, "status": "queued"}

    def get(self, uid):
        with self.lock:
            return dict(self.entries.get(uid, {"status": "unknown"}))


def make_server(store, port=8765):
    jobs, client = Jobs(), HttpClient(store)
    private, nats = None, PublicNats(store)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            if self.path.startswith('/private/'):
                LOG.info("Private market receiver: HTTP %s", args[1] if len(args) > 1 else "request")
            else:
                LOG.info(format, *args)

        def respond(self, data, status=200, content_type="application/json; charset=utf-8", filename=None):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def trusted(self):
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            host = self.headers.get("Host")
            origin = self.headers.get("Origin")
            return host in allowed and (origin is None or origin in {"http://" + h for h in allowed})

        def do_GET(self):
            if not self.trusted():
                self.respond({"error": "Недопустимый Host/Origin"}, 403)
                return
            parsed = urlsplit(self.path)
            query = {k: values[-1] for k, values in parse_qs(parsed.query).items()}
            path = parsed.path
            try:
                if path == "/api/status":
                    with store.connect() as db:
                        categories = [r[0] for r in db.execute("SELECT DISTINCT category FROM items ORDER BY category")]
                    self.respond({**store.status(), "servers": list(SERVERS), "markets": MARKETS,
                                  "version": __version__, "categories": categories, "filters": store.settings(),
                                  "private_scanner": private.status(), "public_nats": nats.status()})
                elif path == "/api/private/status":
                    self.respond(private.status())
                elif path == "/api/private/launcher":
                    self.respond(private.launcher(), content_type="application/octet-stream", filename="Start-PrivateScanner.ps1")
                elif path == "/api/private/history":
                    with store.connect() as db:
                        rows = [dict(r) for r in db.execute("SELECT * FROM native_history WHERE source='private-client' ORDER BY received_at DESC LIMIT 200")]
                        for row in rows:
                            row['observed_at'] = (row['ticks'] - 621355968000000000) / 10000000
                            row['ticks'] = str(row['ticks'])  # Exact .NET ticks exceed JavaScript integer precision.
                    self.respond({"rows": rows, "limit": 200})
                elif path == "/api/market":
                    self.respond(analytics.market(store, query, min(max(int(query.get("limit", 50)), 1), 200),
                                                  max(int(query.get("offset", 0)), 0)))
                elif path == "/api/item":
                    uid = query.get("id", "")
                    records = []
                    for city in MARKETS:
                        data = analytics.market(store, {**query, "search": uid, "city": city}, 100)
                        records.extend(r for r in data["rows"] if r["id"] == uid)
                    with store.connect() as db:
                        recipes = [dict(r) for r in db.execute("SELECT * FROM recipes WHERE item_id=? ORDER BY variant", (uid,))]
                    self.respond({"markets": records, "recipes": recipes})
                elif path.startswith("/api/jobs/"):
                    self.respond(jobs.get(path.rsplit("/", 1)[-1]))
                elif path in ("/api/export.csv", "/api/export.xlsx", "/api/export.json"):
                    result = analytics.market(store, query, 100000)
                    if path.endswith("json"):
                        self.respond(result)
                    else:
                        xlsx = path.endswith("xlsx")
                        self.respond(xlsx_bytes(result["rows"]) if xlsx else csv_bytes(result["rows"]),
                                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if xlsx else "text/csv; charset=utf-8",
                                     filename="MarketPrices.xlsx" if xlsx else "MarketPrices.csv")
                elif path == "/api/backup":
                    with tempfile.TemporaryDirectory() as directory:
                        p = Path(directory) / "backup.sqlite3"
                        with store.connect() as source, sqlite3.connect(p) as target:
                            source.backup(target)
                        self.respond(p.read_bytes(), content_type="application/vnd.sqlite3", filename="trade-desk-backup.sqlite3")
                else:
                    name = {"/": "index.html", "/app.js": "app.js", "/styles.css": "styles.css"}.get(path)
                    if name:
                        self.respond((STATIC / name).read_bytes(), content_type=(mimetypes.guess_type(name)[0] or "text/plain") + "; charset=utf-8")
                    else:
                        self.respond({"error": "Не найдено"}, 404)
            except (ValueError, KeyError, TypeError) as exc:
                self.respond({"error": str(exc)}, 400)
            except Exception:
                LOG.exception("Request failed")
                self.respond({"error": "Внутренняя ошибка; подробности в журнале сервера"}, 500)

        def do_POST(self):
            if not self.trusted():
                self.respond({"error": "Недопустимый Host/Origin"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 16 * 1024 * 1024:
                    self.respond({"error": "Размер JSON должен быть от 1 байта до 16 МБ"}, 413)
                    return
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Тело запроса должно быть JSON-объектом")
                path = urlsplit(self.path).path
                if path == "/api/private/start":
                    self.respond(private.start(body.get("server", "east"), body.get("experimental_ack")))
                elif path == "/api/private/stop":
                    self.respond(private.stop())
                elif path == "/api/nats/start":
                    self.respond(nats.start(body.get("server", "east")))
                elif path == "/api/nats/stop":
                    self.respond(nats.stop())
                elif path.startswith("/private/"):
                    parts = path.strip('/').split('/')
                    if len(parts) != 4:
                        raise ValueError("Неверный адрес приватной сессии")
                    self.respond(private.receive(parts[1], parts[2], parts[3], body))
                elif path == "/api/catalog/sync":
                    self.respond(jobs.submit(lambda: sync_catalog(client)), 202)
                elif path == "/api/market/refresh":
                    ids = body["items"]
                    if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
                        raise ValueError("Выберите 1–100 предметов")
                    server = region(body.get("server", "east"))
                    cities = [location(c) for c in body.get("cities", ["3005"])]
                    qualities = [quality(q) for q in body.get("qualities", [1])]
                    if not cities or len(cities) > 20 or not qualities or len(qualities) > 5:
                        raise ValueError("Некорректный набор рынков/качеств")
                    self.respond(jobs.submit(lambda: refresh_market(client, ids, server, cities, qualities)), 202)
                elif path == "/api/import":
                    server = region(body.get("server", "east"))
                    kind = body["kind"]
                    if kind == "prices":
                        count = ingestion.prices(store, body["data"], server, "aodp-file")
                    elif kind == "history":
                        count = ingestion.history(store, body["data"], server, int(body.get("seconds", 3600)), "aodp-file")
                    else:
                        raise ValueError("Выберите prices или history")
                    self.respond({"imported": count})
                elif path == "/api/favorites":
                    with store.connect() as db:
                        if body.get("enabled"):
                            db.execute("INSERT OR IGNORE INTO favorites VALUES(?)", (body["id"],))
                        else:
                            db.execute("DELETE FROM favorites WHERE item_id=?", (body["id"],))
                    self.respond({"ok": True})
                elif path == "/api/filters":
                    name = str(body["name"]).strip()
                    if not name or len(name) > 100:
                        raise ValueError("Введите название профиля до 100 символов")
                    with store.connect() as db:
                        db.execute("INSERT OR REPLACE INTO saved_filters VALUES(?,?)", (name, json.dumps(body["filters"])))
                    self.respond({"ok": True})
                elif path.startswith("/ingest/"):
                    if private.status()["enabled"]:
                        raise PermissionError("Обычный ingest отключён во время приватной сессии")
                    parts = path.strip("/").split("/")
                    if len(parts) != 3:
                        raise ValueError("Ожидается /ingest/<server>/<topic>")
                    server = region(parts[1])
                    if parts[2] == "marketorders.ingest":
                        count = ingestion.local_orders(store, body, server)
                    elif parts[2] == "markethistories.ingest":
                        count = ingestion.local_history(store, body, server)
                    else:
                        # Official client may also send gold/festivities. Explicitly unsupported.
                        self.respond({"error": "Тема не поддерживается экспериментальным приёмником"}, 404)
                        return
                    self.respond({"imported": count})
                else:
                    self.respond({"error": "Не найдено"}, 404)
            except PermissionError as exc:
                self.respond({"error": str(exc)}, 403)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                self.respond({"error": str(exc)}, 400)
            except Exception:
                LOG.exception("Mutation failed")
                self.respond({"error": "Внутренняя ошибка; подробности в журнале сервера"}, 500)

    server = LoopbackHTTPServer(("127.0.0.1", port), Handler)
    private = PrivateScanner(store, server.server_port)
    server.jobs = jobs
    server.private_scanner, server.public_nats = private, nats
    return server
