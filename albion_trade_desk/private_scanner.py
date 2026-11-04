"""Opt-in, ephemeral private market receiver. This module never opens outbound sockets."""
import hashlib
import hmac
import json
import logging
import secrets
import threading
import uuid
from pathlib import Path
from .domain import region, utcnow, MarketOrderError
from .feeds import ingest
from .aod_process import AodProcess

LOG = logging.getLogger(__name__)

WARNING = ("Эксперимент: разрешение Sandbox Interactive на приватный режим не подтверждено. "
           "Отсутствие внешней отправки с настоящим Windows-клиентом ещё не проверено. "
           "Не обходите шифрование. Включайте режим только осознанно и вручную.")


class PrivateScanner:
    def __init__(self, store, port):
        self.store, self.port = store, port
        self.lock = threading.RLock()
        self.process = AodProcess(store)
        self.token, self.session = None, None
        self.last_rejection = None
        with store.connect() as db:
            db.execute("UPDATE private_sessions SET stopped_at=? WHERE stopped_at IS NULL", (utcnow(),))

    def start(self, server, acknowledged=False):
        if acknowledged is not True:
            raise ValueError(WARNING)
        region(server)
        with self.lock:
            if self.token:
                raise ValueError("Приватная сессия уже запущена; сначала остановите её")
            if self.process.status()['active']:
                raise ValueError('Предыдущий процесс сборщика ещё не остановлен')
            self.process = AodProcess(self.store)
            self.session = uuid.uuid4().hex
            self.token = secrets.token_urlsafe(32)
            self.last_rejection = None
            with self.store.connect() as db:
                db.execute("INSERT INTO private_sessions(id,server,started_at) VALUES(?,?,?)",
                           (self.session, server, utcnow()))
            return self.status()

    def launch(self, server, acknowledged=False):
        self.start(server, acknowledged)
        try:
            self.process.start(self.destination(), self.session)
        except Exception as exc:
            self.stop()
            self.process.error = str(exc)
            raise
        return self.status()

    def stop(self):
        self.process.stop()
        with self.lock:
            if self.session:
                with self.store.connect() as db:
                    db.execute("UPDATE private_sessions SET stopped_at=? WHERE id=?", (utcnow(), self.session))
            self.token = None
            return self.status()

    def status(self):
        with self.lock, self.store.connect() as db:
            row = db.execute("SELECT * FROM private_sessions WHERE id=?", (self.session,)).fetchone() if self.session else None
            result = dict(row) if row else {}
            result.update(enabled=self.token is not None, experimental=True,
                          network_verified=False, rules_permission_confirmed=False, warning=WARNING)
            last = result.get("last_received_at")
            result["connection"] = "receiving" if self.token and last and utcnow() - last < 120 else "waiting" if self.token else "disabled"
            process = self.process.status()
            result["process"] = process
            result["client_process_known"] = bool(process.get('pid') and process['active'])
            if process['managed'] and not process['active'] and self.token:
                db.execute("UPDATE private_sessions SET stopped_at=COALESCE(stopped_at,?) WHERE id=?", (utcnow(), self.session))
                self.token = None
                result['enabled'] = False
            result['state'] = process['state'] if process['managed'] or process.get('error') else ('waiting' if self.token else 'disabled')
            if result['state'] == 'waiting' and result['connection'] == 'receiving':
                result['state'] = 'receiving'
            result['detected_server'] = process.get('detected_server')
            result['server_origin'] = 'session-selection; native AOD HTTP has no server id'
            result['db_path'] = str(self.store.path.resolve())
            result['db_bytes'] = sum(p.stat().st_size for p in (self.store.path, Path(str(self.store.path)+'-wal')) if p.exists())
            result['orders_processed'] = result.get('orders_processed', 0)
            result['unique_orders'] = db.execute("SELECT COUNT(*) FROM orders WHERE source='private-client' AND server=?", (result.get('server','east'),)).fetchone()[0]
            result['last_error'] = process.get('error')
            result['last_rejection'] = dict(self.last_rejection) if self.last_rejection else None
            result["own_orders"] = db.execute("SELECT COUNT(*) FROM orders WHERE source='private-client'").fetchone()[0]
            result["own_native_history"] = db.execute("SELECT COUNT(*) FROM native_history WHERE source='private-client'").fetchone()[0]
            result["unmapped_history"] = db.execute("SELECT COUNT(*) FROM native_history WHERE source='private-client' AND item_id IS NULL").fetchone()[0]
            return result

    def destination(self):
        with self.lock:
            if not self.token:
                raise ValueError("Сначала включите экспериментальную приватную сессию")
            return f"http://127.0.0.1:{self.port}/private/{self.status()['server']}/{self.token}"

    def launcher(self):
        # Fixed template and server-generated path only; never interpolate user filesystem text.
        script = (Path(__file__).with_name("windows") / "Start-PrivateScanner.ps1").read_text(encoding="utf-8-sig")
        policy = (Path(__file__).with_name("windows") / "PrivateNetwork.ps1").read_text(encoding="utf-8-sig")
        return (policy + "\n" + script.replace("@@DESTINATION@@", self.destination()).replace("@@SESSION_ID@@", self.session)).encode("utf-8-sig")

    def receive(self, server, token, topic, payload, observed_at=None):
        with self.lock:
            current = self.status()
            if not self.token or not hmac.compare_digest(token, self.token) or server != current["server"]:
                raise PermissionError("Приватная сессия выключена или её адрес устарел")
            # Canonical hash supports idempotent retries; no payload/log forwarding or cloud sync.
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            digest, now = hashlib.sha256(encoded).hexdigest(), utcnow()
            processed = len(payload.get('Orders', [])) if topic == 'marketorders.ingest' else 0
            key = hashlib.sha256((topic + ":" + digest).encode()).hexdigest()
            with self.store.connect() as db:
                prior = db.execute("SELECT last_received_at FROM feed_batches WHERE session_id=? AND server=? AND source=? AND digest=?",
                                   (self.session, server, "private-client", key)).fetchone()
            duplicate = bool(prior and now - prior[0] < 300)
            try:
                if not duplicate or topic == 'marketorders.ingest':
                    count = ingest(self.store, topic, payload, server, observed_at=observed_at)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                # AOD's HTTP uploader hides the response body. Keep the reason locally,
                # without logging the session URL, entire packet or arbitrary field values.
                details = exc.details if isinstance(exc,MarketOrderError) else {}
                message = str(exc) if isinstance(exc,MarketOrderError) else 'Пакет отклонён: некорректные рыночные данные'
                self.last_rejection = {'at':now,'message':message,**details}
                LOG.warning('Локальный пакет рынка отклонён: %s',message)
                with self.store.connect() as db:
                    db.execute("UPDATE private_sessions SET rejected=rejected+1 WHERE id=?", (self.session,))
                raise
            if duplicate:
                # An identical rescan still refreshes last_seen without multiplying quantities.
                with self.store.connect() as db:
                    db.execute("UPDATE private_sessions SET packets=packets+1,duplicates=duplicates+1,orders_processed=orders_processed+?,last_received_at=?,last_topic=? WHERE id=?",
                               (processed, now, topic, self.session))
                return {"accepted": 0, "duplicate": True}
            with self.store.connect() as db:
                db.execute("DELETE FROM feed_batches WHERE last_received_at<?", (now-300,))
                db.execute("INSERT OR REPLACE INTO feed_batches VALUES(?,?,?,?,?)", (self.session, server, "private-client", key, now))
                db.execute("UPDATE private_sessions SET packets=packets+1,records=records+?,orders_processed=orders_processed+?,last_received_at=?,last_topic=? WHERE id=?",
                           (count, processed, now, topic, self.session))
            return {"accepted": count, "duplicate": False}
