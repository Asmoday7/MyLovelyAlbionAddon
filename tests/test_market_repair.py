"""City-cluster packets must reach the same cards as auction-zone packets."""
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from albion_trade_desk import analytics, feeds, history_view, ingestion
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.domain import location
from albion_trade_desk.market_repair import REPAIR_KEY, repair_market_locations
from albion_trade_desk.storage import Store
from test_core import END, NOW

UID = 'T4_PLANKS_LEVEL3@3'


def packet(city='1000', order_id=42, side='offer', price=7500):
    return {'Orders': [{'Id': order_id, 'ItemTypeId': UID, 'LocationId': city,
        'QualityLevel': 1, 'EnchantmentLevel': 3, 'UnitPriceSilver': price*10000,
        'Amount': 20, 'AuctionType': side, 'Expires': '2099-01-01T00:00:00Z'}]}


class MarketRepairTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = Store(temp.name)
        import_catalog(self.store, [{'UniqueName': UID, 'Index': 1,
            'LocalizedNames': {'EN-US': 'Exceptional Pine Planks', 'RU-RU': 'Брусья .3'}}])

    def test_market_city_aliases_preserve_black_market_and_unknown_locations(self):
        for raw, city in [('0000','7'),('1000','1002'),('2000','2004'),('3004','3008'),
                          ('4000','4002'),('5000','5003'),('1301','1002'),
                          ('3013-Auction2','3005'),('3003-HellDen','3005'),('1000-HellDen','1002')]:
            self.assertEqual(location(raw), city)
        self.assertEqual(location('3003'), '3003')
        self.assertEqual(location('9999'), '9999')

    def test_city_and_market_rescans_update_same_order_without_quality_or_enchantment_mix(self):
        for at, city, price in [(NOW-3600,'1002',8000),(NOW,'1000',7500)]:
            with patch('albion_trade_desk.ingestion.utcnow', return_value=at):
                feeds.ingest(self.store, 'marketorders.ingest', packet(city, price=price), 'east')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM orders').fetchone()
            self.assertEqual((row['location'],row['raw_location'],row['market_type']),('1002','1000','city'))
            self.assertEqual((row['enchantment'],row['quality'],row['price']),(3,1,7500))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],1)
        result = analytics.market(self.store, {'search':UID,'city':'Lymhurst','scope':'private','quality':'all'}, now=NOW)['rows'][0]
        self.assertEqual(result['by_quality'][0]['quotes']['sell_price_min']['price'],7500)
        self.assertTrue(all(not r['quotes'] for r in result['by_quality'][1:]))
        self.assertEqual(result['quotes']['sell_price_min']['age_seconds'],0)

    def legacy(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM user_settings WHERE key=?',(REPAIR_KEY,))
            for city, order_id, price in [('1000','42',7500),('1002','43',8000)]:
                db.execute('''INSERT INTO orders
                    (server,id,item_id,location,quality,side,price,amount,expires,received_at,source,
                     raw_location,market_type,enchantment,observed_at,first_seen_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    ('east',order_id,UID,city,1,'offer',price,2,4000000000,NOW,'private-client',
                     city,'other' if city=='1000' else 'city',3,NOW,NOW))
                ingestion.put_quote(db,'east',city,UID,1,'sell_price_min',price,NOW,NOW,'private-client','fixture')
            for city, received, quantity in [('1000',NOW,3),('1002',NOW-10,2)]:
                db.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?)',
                    ('east',city,UID,1,END-3600,3600,quantity,100,received,'private-client'))
                db.execute('INSERT INTO native_history VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    ('east',city,1,UID,1,1,(END-21600)*10000000+621355968000000000,
                     quantity,quantity*100,received,'private-client'))

    def test_existing_data_repaired_with_backup_newest_collision_wins_and_repeat_open_is_safe(self):
        self.legacy()
        before = analytics.market(self.store, {'search':UID,'city':'Lymhurst','scope':'private'}, now=NOW)['rows'][0]
        self.assertEqual(before['quotes']['sell_price_min']['price'],8000)
        with patch('albion_trade_desk.market_repair.utcnow', return_value=NOW):
            reopened = Store(self.store.directory)
        after = analytics.market(reopened, {'search':UID,'city':'Lymhurst','scope':'private'}, now=NOW)['rows'][0]
        self.assertEqual(after['quotes']['sell_price_min']['price'],7500)
        with reopened.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders WHERE location='1000'").fetchone()[0],0)
            self.assertEqual(db.execute("SELECT raw_location FROM orders WHERE id='42'").fetchone()[0],'1000')
            self.assertEqual(db.execute('SELECT quantity FROM history').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT quantity FROM native_history').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quotes').fetchone()[0],1)
        backup = reopened.directory/'before-market-location-repair-v1.sqlite3'
        with closing(sqlite3.connect(backup)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM orders WHERE location='1000'").fetchone()[0],1)
        repeated = Store(reopened.directory)
        self.assertEqual(repeated.status()['orders'],2)
        chart = history_view.series(repeated, {'id':UID,'city':'Lymhurst','scope':'private','quality':1,'hours':168}, NOW)
        self.assertEqual(chart['known_quantity'],3)

    def test_repair_failure_rolls_back_and_can_be_retried(self):
        self.legacy()
        with patch('albion_trade_desk.market_repair.rebuild_order_quotes', side_effect=RuntimeError('fixture')):
            with self.assertRaises(RuntimeError): repair_market_locations(self.store)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT location FROM orders WHERE id='42'").fetchone()[0],'1000')
            self.assertIsNone(db.execute('SELECT 1 FROM user_settings WHERE key=?',(REPAIR_KEY,)).fetchone())
        repair_market_locations(self.store)
        self.assertEqual(self.store.status()['orders'],2)

    def test_latest_scan_does_not_make_an_unseen_old_cheapest_order_look_new(self):
        with patch('albion_trade_desk.ingestion.utcnow',return_value=NOW-3600):
            ingestion.local_orders(self.store,packet(price=7000),source='private-client')
        with patch('albion_trade_desk.ingestion.utcnow',return_value=NOW):
            ingestion.local_orders(self.store,packet(order_id=43,price=7500),source='private-client')
        result = analytics.market(self.store, {'search':UID,'city':'Lymhurst','scope':'private'},now=NOW)['rows'][0]
        q = result['quotes']['sell_price_min']
        self.assertEqual((q['price'],q['age_seconds'],q['last_scan_age_seconds']),(7000,3600,0))


if __name__ == '__main__': unittest.main()
