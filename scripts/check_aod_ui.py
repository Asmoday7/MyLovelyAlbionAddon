"""Linux UI acceptance with isolated SQLite/native fixtures; no game/AOD execution."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server

if os.name == 'nt':
    raise SystemExit('This UI scenario exercises the unsupported-OS guard; run on Linux.')
with tempfile.TemporaryDirectory() as directory:
    server = make_server(Store(directory), 0)
    destination = Path(directory) / 'destination'
    original_start = server.private_scanner.start
    def start(*args, **kwargs):
        result = original_start(*args, **kwargs)
        destination.write_text(server.private_scanner.destination())
        return result
    server.private_scanner.start = start
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        env = {**os.environ, 'ALBION_SMOKE_URL': f'http://127.0.0.1:{server.server_port}',
               'ALBION_TEST_DESTINATION': str(destination)}
        subprocess.run(['node', 'tests/browser_aod.cjs'], env=env, check=True, timeout=70)
    finally:
        server.shutdown(); thread.join(); server.server_close()
