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
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "trade-desk.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

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
