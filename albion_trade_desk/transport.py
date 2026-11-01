"""Serialized, bounded HTTP transport. TLS verification is never disabled."""
import gzip
import hashlib
import json
import ssl
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from .domain import SERVERS, region, utcnow
from .catalog import CATALOG_URL, RECIPES_URL, import_catalog
from . import ingestion


class HttpClient:
    def __init__(self, store, opener=None, sleep=time.sleep, clock=time.time):
        self.store, self.sleep, self.clock = store, sleep, clock
        self.opener = opener or urlopen
        self.lock, self.requests = threading.Lock(), deque()

    def get(self, url, ttl=900):
        if getattr(self, 'enabled', None) is not None and not self.enabled():
            raise ValueError('Публичные загрузки выключены. Включите их в разделе «Источники». Локальный сборщик от них не зависит.')
        with self.lock:
            with self.store.connect() as db:
                cached = db.execute("SELECT body FROM http_cache WHERE url=? AND expires>?", (url, self.clock())).fetchone()
            if cached:
                return json.loads(cached[0])
            for attempt in range(3):
                # Both 180/min and 300/5min; a single queue shared by background jobs.
                now = self.clock()
                while self.requests and self.requests[0] <= now - 300:
                    self.requests.popleft()
                waits = [0]
                if self.requests:
                    waits.append(self.requests[-1] + 1.1 - now)
                if len(self.requests) >= 300:
                    waits.append(self.requests[-300] + 300 - now)
                if len(self.requests) >= 180:
                    waits.append(self.requests[-180] + 60 - now)
                self.sleep(max(waits))
                self.requests.append(self.clock())
                request = Request(url, headers={"Accept": "application/json", "Accept-Encoding": "gzip",
                                                "User-Agent": "AlbionTradeDesk/0.1 personal-analytics"})
                try:
                    with self.opener(request, timeout=30, context=ssl.create_default_context()) as response:
                        body = response.read(64 * 1024 * 1024 + 1)
                        if len(body) > 64 * 1024 * 1024:
                            raise ValueError("Ответ слишком велик")
                        if response.headers.get("Content-Encoding", "").lower() == "gzip":
                            import io
                            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                                body = compressed.read(64 * 1024 * 1024 + 1)
                            if len(body) > 64 * 1024 * 1024:
                                raise ValueError("Распакованный ответ слишком велик")
                        value = json.loads(body)
                    with self.store.connect() as db:
                        db.execute("INSERT OR REPLACE INTO http_cache VALUES(?,?,?)",
                                   (url, json.dumps(value, ensure_ascii=False), self.clock() + ttl))
                    return value
                except HTTPError as exc:
                    if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                        raise
                    wait = 2 ** attempt
                    if exc.code == 429:
                        reset = exc.headers.get("RateLimit-Reset")
                        retry = exc.headers.get("Retry-After")
                        if reset:
                            wait = max(wait, float(reset) - self.clock())
                        elif retry:
                            try:
                                wait = max(wait, float(retry))
                            except ValueError:
                                from email.utils import parsedate_to_datetime
                                wait = max(wait, parsedate_to_datetime(retry).timestamp() - self.clock())
                    exc.close()
                    if wait > 60:
                        raise RuntimeError(f"Rate limit: повторите обновление через {math_ceil(wait)} с") from None
                    self.sleep(wait)


def math_ceil(value):
    import math
    return math.ceil(value)


def batches(server, kind, ids, cities, qualities, extra=None):
    base = SERVERS[region(server)] + "/api/v2/stats/" + kind + "/"
    query = urlencode({"locations": ",".join(cities), "qualities": ",".join(map(str, qualities)), **(extra or {})})
    chunk = []
    for uid in dict.fromkeys(ids):
        if not isinstance(uid, str) or not uid or len(uid) > 150 or not all(c.isalnum() or c in "_@-" for c in uid):
            raise ValueError("Некорректный item ID")
        candidate = base + quote(",".join(chunk + [uid]), safe=",@_") + ".json?" + query
        if len(candidate) >= 3900 or len(chunk) >= 100:
            if not chunk:
                raise ValueError("Слишком длинный URL")
            yield base + quote(",".join(chunk), safe=",@_") + ".json?" + query
            chunk = []
        chunk.append(uid)
    if chunk:
        yield base + quote(",".join(chunk), safe=",@_") + ".json?" + query


def sync_catalog(client):
    count = import_catalog(client.store, client.get(CATALOG_URL, 3600), client.get(RECIPES_URL, 3600))
    from .feeds import resolve_history
    resolve_history(client.store)
    return {"items": count}


def refresh_market(client, ids, server, cities, qualities):
    if not ids or len(ids) > 100:
        raise ValueError("Выберите от 1 до 100 предметов")
    counts = {"prices": 0, "history": 0}
    for url in batches(server, "prices", ids, cities, qualities):
        payload = client.get(url)
        counts["prices"] += ingestion.prices(client.store, payload, server)
    extra = {"time-scale": 1, "date": (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d")}
    for url in batches(server, "history", ids, cities, qualities, extra):
        payload = client.get(url, ttl=3600)
        counts["history"] += ingestion.history(client.store, payload, server)
    return counts


def probe(client, server):
    """Save real replies before claiming the regional adapter validated."""
    directory = client.store.directory / "evidence"
    directory.mkdir(exist_ok=True)
    records = []
    for kind in ("prices", "history"):
        extra = {"time-scale": 1} if kind == "history" else {}
        url = next(batches(server, kind, ["T4_BAG"], ["3005", "3003"], [1], extra))
        payload = client.get(url, ttl=0)
        if not isinstance(payload, list):
            raise ValueError("API вернул не массив")
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode()
        digest = hashlib.sha256(raw).hexdigest()
        filename = f"{server}-{kind}-{int(utcnow())}.json"
        (directory / filename).write_bytes(raw)
        records.append({"kind": kind, "url": url, "received_at": utcnow(), "sha256": digest,
                        "file": filename, "rows": len(payload), "nonempty": bool(payload)})
    (directory / f"{server}-probe.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return records
