"""Isolated city/market rescan and open-dialog refresh regression. No game/API."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk import feeds
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server

with tempfile.TemporaryDirectory() as directory:
    store = Store(directory)
    import_catalog(store, [{'UniqueName': 'T4_PLANKS_LEVEL3@3', 'Index': 1,
                           'LocalizedNames': {'RU-RU': 'Брусья .3 · тест', 'EN-US': 'Exceptional Pine Planks'}}])
    feeds.ingest(store, 'marketorders.ingest', {'Orders': [{
        'Id': 42, 'ItemTypeId': 'T4_PLANKS_LEVEL3@3', 'LocationId': '1002',
        'QualityLevel': 1, 'EnchantmentLevel': 3, 'UnitPriceSilver': 76000000,
        'Amount': 20, 'AuctionType': 'offer', 'Expires': '2099-01-01T00:00:00Z'}]}, 'east')
    server = make_server(store, 0)
    server.private_scanner.start('east', True)
    destination = Path(directory)/'destination'
    destination.write_text(server.private_scanner.destination())
    thread = threading.Thread(target=server.serve_forever); thread.start()
    try:
        subprocess.run(['node','tests/browser_materials.cjs'], check=True, timeout=60,
            env={**os.environ, 'ALBION_SMOKE_URL': f'http://127.0.0.1:{server.server_port}',
                 'ALBION_TEST_DESTINATION': str(destination)})
    finally:
        server.shutdown(); thread.join(); server.server_close()
