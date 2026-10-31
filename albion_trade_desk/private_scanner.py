"""Opt-in, ephemeral private market receiver. This module never opens outbound sockets."""
import hashlib
import hmac
import json
import secrets
import threading
import uuid
from pathlib import Path
from .domain import region, utcnow
from .feeds import ingest

WARNING = ("Эксперимент: разрешение Sandbox Interactive на приватный режим не подтверждено. "
           "Отсутствие внешней отправки с настоящим Windows-клиентом ещё не проверено. "
           "Не обходите шифрование. Включайте режим только осознанно и вручную.")


class PrivateScanner:
    def __init__(self, store, port):
        self.store, self.port = store, port
        self.lock = threading.RLock()
        self.token, self.session = None, None
        with store.connect() as db:
            db.execute("UPDATE private_sessions SET stopped_at=? WHERE stopped_at IS NULL", (utcnow(),))

    def start(self, server, acknowledged=False):
        if acknowledged is not True:
            raise ValueError(WARNING)
        region(server)
        with self.lock:
            if self.token:
                raise ValueError("Приватная сессия уже запущена; сначала остановите её")
            self.session = uuid.uuid4().hex
            self.token = secrets.token_urlsafe(32)
            with self.store.connect() as db:
                db.execute("INSERT INTO private_sessions(id,server,started_at) VALUES(?,?,?)",
                           (self.session, server, utcnow()))
            return self.status()

    def stop(self):
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
            result["client_process_known"] = False  # Packets do not prove a running client or firewall.
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
        return script.replace("@@DESTINATION@@", self.destination()).replace("@@SESSION_ID@@", self.session).encode("utf-8-sig")

    def receive(self, server, token, topic, payload):
        with self.lock:
            if not self.token or not hmac.compare_digest(token, self.token) or server != self.status()["server"]:
                raise PermissionError("Приватная сессия выключена или её адрес устарел")
            # Canonical hash supports idempotent retries; no payload/log forwarding or cloud sync.
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            digest, now = hashlib.sha256(encoded).hexdigest(), utcnow()
            key = hashlib.sha256((topic + ":" + digest).encode()).hexdigest()
            with self.store.connect() as db:
                prior = db.execute("SELECT last_received_at FROM feed_batches WHERE session_id=? AND server=? AND source=? AND digest=?",
                                   (self.session, server, "private-client", key)).fetchone()
            if prior and now - prior[0] < 300:
                with self.store.connect() as db:
                    db.execute("UPDATE private_sessions SET packets=packets+1,duplicates=duplicates+1,last_received_at=?,last_topic=? WHERE id=?",
                               (now, topic, self.session))
                return {"accepted": 0, "duplicate": True}
            try:
                count = ingest(self.store, topic, payload, server)
            except (ValueError, KeyError, TypeError, OverflowError):
                with self.store.connect() as db:
                    db.execute("UPDATE private_sessions SET rejected=rejected+1 WHERE id=?", (self.session,))
                raise
            with self.store.connect() as db:
                db.execute("INSERT OR REPLACE INTO feed_batches VALUES(?,?,?,?,?)", (self.session, server, "private-client", key, now))
                db.execute("UPDATE private_sessions SET packets=packets+1,records=records+?,last_received_at=?,last_topic=? WHERE id=?",
                           (count, now, topic, self.session))
            return {"accepted": count, "duplicate": False}
