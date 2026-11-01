"""One-time, backed-up repair of market aliases stored by older application builds."""
from collections import defaultdict
from contextlib import closing
import sqlite3

from .domain import MARKETS, location, utcnow
from .ingestion import rebuild_order_quotes

REPAIR_KEY = 'market_location_repair_v1'
TABLES = ('orders', 'quotes', 'history', 'native_history', 'market_snapshots')


def repair_market_locations(store):
    with store.connect() as db:
        if db.execute('SELECT 1 FROM user_settings WHERE key=?', (REPAIR_KEY,)).fetchone():
            return
        aliases = {}
        for table in TABLES:
            for row in db.execute(f'SELECT DISTINCT location FROM {table}'):
                before = row['location']
                after = location(before)
                if before != after:
                    aliases[before] = after
        if aliases:
            # No write transaction is open here: sqlite.backup must precede BEGIN.
            backup = store.directory / 'before-market-location-repair-v1.sqlite3'
            if not backup.exists():
                pending = backup.with_name(backup.name+'.pending')
                pending.unlink(missing_ok=True)
                try:
                    with closing(sqlite3.connect(pending)) as target:
                        db.backup(target)
                    pending.replace(backup)
                finally:
                    pending.unlink(missing_ok=True)
        db.execute('BEGIN IMMEDIATE')
        groups = defaultdict(set)
        for old, new in aliases.items():
            for row in db.execute('SELECT * FROM orders WHERE location=?', (old,)):
                groups[(row['server'], row['source'])].add((new, row['item_id'], row['quality'], row['side']))
            # The original wire location remains in orders.raw_location and the backup.
            db.execute('UPDATE orders SET location=?,market_type=? WHERE location=?',
                       (new, 'black-market' if new == '3003' else 'city' if new in MARKETS else 'other', old))
            for table in TABLES[1:]:
                columns = [r['name'] for r in db.execute(f'PRAGMA table_info({table})')]
                keys = [r['name'] for r in db.execute(f'PRAGMA table_info({table})') if r['pk']]
                values = [c for c in columns if c not in keys]
                if table == 'market_snapshots':
                    conflict = 'DO NOTHING'
                else:
                    newer = '(excluded.observed_at,excluded.received_at)>=(quotes.observed_at,quotes.received_at)' if table == 'quotes' else f'excluded.received_at>={table}.received_at'
                    conflict = 'DO UPDATE SET '+','.join(f'{c}=excluded.{c}' for c in values)+' WHERE '+newer
                sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT ({','.join(keys)}) {conflict}"
                for row in db.execute(f'SELECT * FROM {table} WHERE location=?', (old,)).fetchall():
                    row = dict(row); row['location'] = new
                    db.execute(sql, [row[c] for c in columns])
                db.execute(f'DELETE FROM {table} WHERE location=?', (old,))
        now = utcnow()
        for (server, source), identities in groups.items():
            rebuild_order_quotes(db, server, identities, source, now)
        db.execute('INSERT INTO user_settings(key,value) VALUES(?,?)', (REPAIR_KEY, '1'))
