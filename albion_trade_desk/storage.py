import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
 id TEXT PRIMARY KEY, numeric_id INTEGER, name_ru TEXT NOT NULL, name_en TEXT NOT NULL,
 tier INTEGER NOT NULL, enchantment INTEGER NOT NULL, category TEXT NOT NULL DEFAULT '',
 subcategory TEXT NOT NULL DEFAULT '', weight REAL, search TEXT NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}', catalog_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS items_numeric ON items(numeric_id);
CREATE TABLE IF NOT EXISTS recipes (
 item_id TEXT NOT NULL, variant INTEGER NOT NULL, output REAL NOT NULL,
 focus REAL, silver REAL NOT NULL, resources TEXT NOT NULL,
 PRIMARY KEY(item_id,variant));
CREATE TABLE IF NOT EXISTS quotes (
 server TEXT NOT NULL, location TEXT NOT NULL, item_id TEXT NOT NULL, quality INTEGER NOT NULL,
 kind TEXT NOT NULL, price REAL NOT NULL, observed_at REAL NOT NULL, received_at REAL NOT NULL,
 source TEXT NOT NULL, limitation TEXT NOT NULL,
 PRIMARY KEY(server,location,item_id,quality,kind,source));
CREATE INDEX IF NOT EXISTS quotes_identity ON quotes(server,item_id,location,quality);
CREATE TABLE IF NOT EXISTS market_snapshots (
 server TEXT NOT NULL, location TEXT NOT NULL, item_id TEXT NOT NULL, quality INTEGER NOT NULL,
 kind TEXT NOT NULL, price REAL NOT NULL, observed_at REAL NOT NULL, received_at REAL NOT NULL,
 source TEXT NOT NULL, limitation TEXT NOT NULL,
 PRIMARY KEY(server,location,item_id,quality,kind,observed_at,price,source));
CREATE TABLE IF NOT EXISTS history (
 server TEXT NOT NULL, location TEXT NOT NULL, item_id TEXT NOT NULL, quality INTEGER NOT NULL,
 start REAL NOT NULL, seconds INTEGER NOT NULL, quantity INTEGER NOT NULL, average REAL NOT NULL,
 received_at REAL NOT NULL, source TEXT NOT NULL,
 PRIMARY KEY(server,location,item_id,quality,start,seconds));
CREATE INDEX IF NOT EXISTS history_identity ON history(server,item_id,location,quality,start);
CREATE TABLE IF NOT EXISTS orders (
 server TEXT NOT NULL, id TEXT NOT NULL, item_id TEXT NOT NULL, location TEXT NOT NULL,
 quality INTEGER NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, amount INTEGER NOT NULL,
 expires REAL NOT NULL, received_at REAL NOT NULL, PRIMARY KEY(server,id));
CREATE TABLE IF NOT EXISTS favorites (item_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS saved_filters (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS http_cache (url TEXT PRIMARY KEY, body TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at REAL NOT NULL, server TEXT NOT NULL,
 source TEXT NOT NULL, kind TEXT NOT NULL, count INTEGER NOT NULL, detail TEXT NOT NULL);
"""

FEED_SCHEMA = """
CREATE TABLE IF NOT EXISTS private_sessions (
 id TEXT PRIMARY KEY, server TEXT NOT NULL, started_at REAL NOT NULL, stopped_at REAL,
 packets INTEGER NOT NULL DEFAULT 0, records INTEGER NOT NULL DEFAULT 0,
 duplicates INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
 last_received_at REAL, last_topic TEXT);
CREATE TABLE IF NOT EXISTS feed_batches (
 session_id TEXT NOT NULL, server TEXT NOT NULL, source TEXT NOT NULL, digest TEXT NOT NULL,
 last_received_at REAL NOT NULL, PRIMARY KEY(session_id,server,source,digest));
CREATE TABLE IF NOT EXISTS native_history (
 server TEXT NOT NULL, location TEXT NOT NULL, numeric_id INTEGER NOT NULL, item_id TEXT,
 quality INTEGER NOT NULL, timescale INTEGER NOT NULL, ticks INTEGER NOT NULL,
 quantity INTEGER NOT NULL, silver REAL NOT NULL, received_at REAL NOT NULL, source TEXT NOT NULL,
 PRIMARY KEY(server,location,numeric_id,quality,timescale,ticks,source));
CREATE TABLE IF NOT EXISTS user_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS craft_packs (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL);
"""


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "trade-desk.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            # v1 history had no source in its key: a local upload could overwrite public data.
            history_pk = [r["name"] for r in db.execute("PRAGMA table_info(history)") if r["pk"]]
            if "source" not in history_pk:
                backup = self.directory / "before-private-scanner-v2.sqlite3"
                if not backup.exists():
                    target = sqlite3.connect(backup)
                    try:
                        db.backup(target)
                    finally:
                        target.close()
                db.execute("ALTER TABLE history RENAME TO history_v1")
                db.execute("""CREATE TABLE history (
                    server TEXT NOT NULL, location TEXT NOT NULL, item_id TEXT NOT NULL, quality INTEGER NOT NULL,
                    start REAL NOT NULL, seconds INTEGER NOT NULL, quantity INTEGER NOT NULL, average REAL NOT NULL,
                    received_at REAL NOT NULL, source TEXT NOT NULL,
                    PRIMARY KEY(server,location,item_id,quality,start,seconds,source))""")
                db.execute("INSERT INTO history SELECT * FROM history_v1")
                db.execute("DROP TABLE history_v1")
                db.execute("CREATE INDEX history_identity ON history(server,item_id,location,quality,start)")
            columns = {r["name"] for r in db.execute("PRAGMA table_info(orders)")}
            if "source" not in columns:
                db.execute("ALTER TABLE orders RENAME TO orders_v1")
                db.execute("""CREATE TABLE orders (
                    server TEXT NOT NULL, id TEXT NOT NULL, item_id TEXT NOT NULL, location TEXT NOT NULL,
                    quality INTEGER NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, amount INTEGER NOT NULL,
                    expires REAL NOT NULL, received_at REAL NOT NULL, source TEXT NOT NULL,
                    PRIMARY KEY(server,id,source))""")
                db.execute("INSERT INTO orders SELECT *, 'data-client' FROM orders_v1")
                db.execute("DROP TABLE orders_v1")
            db.execute("PRAGMA user_version=2")
        with self.connect() as db:
            db.executescript(FEED_SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self):
        with self.connect() as db:
            result = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("items", "recipes", "quotes", "history", "orders")}
            result["events"] = [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 15")]
            result["catalog_at"] = db.execute("SELECT MAX(catalog_at) FROM items").fetchone()[0]
            return result

    def settings(self):
        with self.connect() as db:
            return {r["name"]: json.loads(r["value"]) for r in db.execute("SELECT * FROM saved_filters")}
