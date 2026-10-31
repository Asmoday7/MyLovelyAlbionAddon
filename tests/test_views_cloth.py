import io
import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from albion_trade_desk import analytics,ingestion,refining,history_view,crafting
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.storage import Store
from albion_trade_desk.export import records
from test_core import names,quote,history,NOW,END


class QualityHistoryTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.store=Store(d.name);import_catalog(self.store,names())

    def row(self,**kw):return analytics.market(self.store,{'quality':'auto',**kw},now=NOW)['rows'][0]

    def test_quality_fallback_prefers_ordinary_through_excellent_and_labels_masterpiece(self):
        ingestion.prices(self.store,quote(100,q=2)+quote(1,q=5))
        row=self.row();self.assertEqual(row['quotes']['sell_price_min']['quality'],2)
        self.assertEqual(len(row['by_quality']),5)
        self.assertEqual(self.row(quality=5)['quotes']['sell_price_min']['price'],1)
        with self.store.connect() as db:db.execute('DELETE FROM quotes WHERE quality=2')
        q=self.row()['quotes']['sell_price_min'];self.assertEqual(q['quality'],5);self.assertTrue(q['masterpiece_fallback'])

    def test_all_frames_fetchable_priced_filter_and_no_cross_quality_spread(self):
        values=quote(100,q=2)+quote(200,q=4);values[0]['buy_price_max']=0;values[1]['buy_price_max']=90
        ingestion.prices(self.store,values)
        row=self.row(priced='true');self.assertEqual(row['quotes']['sell_price_min']['quality'],2)
        self.assertEqual(row['quotes']['buy_price_max']['quality'],4);self.assertIsNone(row['spread'])
        self.assertEqual(self.row(quality=2)['quotes']['sell_price_min']['price'],100)
        exported=list(records([row]));self.assertEqual([r[5] for r in exported],[1,2,3,4,5])

    def test_fresh_masterpiece_precedes_stale_normal_but_never_changes_exact_quality(self):
        ingestion.prices(self.store,quote(100,q=1,when=END-172800)+quote(300,q=5))
        self.assertEqual(self.row()['quotes']['sell_price_min']['quality'],5)
        self.assertFalse(self.row(quality=1)['quotes']['sell_price_min']['fresh'])

    def test_history_exact_quality_and_source_and_gap_not_zero(self):
        ingestion.history(self.store,history(24,qty=3,q=2))
        ingestion.history(self.store,history(24,qty=99,q=5))
        q={'id':'T4_BAG','city':'3005','quality':2,'hours':24}
        data=history_view.series(self.store,q,NOW);self.assertEqual(data['volume'],72)
        self.assertIsNone(history_view.series(self.store,{**q,'scope':'private'},NOW)['volume'])
        self.assertIsNone(history_view.series(self.store,{**q,'hours':168},NOW)['volume'])
        self.assertEqual(history_view.series(self.store,{**q,'hours':168},NOW)['known_quantity'],72)

    def test_history_coarse_hourly_sources_not_double_counted(self):
        data=history(6,qty=2);ingestion.history(self.store,data)
        ingestion.history(self.store,data,source='private-client')
        coarse=history(1,qty=10000);coarse[0]['data'][0]['timestamp']=END//21600*21600-21600
        ingestion.history(self.store,coarse,seconds=21600)
        q={'id':'T4_BAG','city':'3005','quality':1,'hours':168}
        s=history_view.series(self.store,q,NOW)
        # Coarse bin overlaps at least one fine hour, so cannot add its full volume.
        fine=history_view.series(self.store,{**q,'hours':6},NOW)
        self.assertEqual(fine['volume'],12)
        self.assertEqual(s['known_quantity'],12)
        # Exact same 24 hourly intervals in two sources still count just once.
        self.assertEqual(sum(p['quantity'] or 0 for p in fine['points']),12)

    def test_zero_observed_sales_are_not_missing_history(self):
        ingestion.history(self.store,history(24,qty=0))
        data=history_view.series(self.store,{'id':'T4_BAG','city':'3005','quality':1,'hours':24},NOW)
        self.assertEqual(data['volume'],0)
        self.assertEqual(data['known_hours'],24)
        self.assertIsNone(data['vwap'])
        self.assertTrue(all(p['quantity']==0 for p in data['points']))

    def test_history_custom_closed_window_and_invalid_ranges(self):
        ingestion.history(self.store,history(24,qty=3))
        q={'id':'T4_BAG','city':'3005','start':END-12*3600,'end':END,'quality':1}
        self.assertEqual(history_view.series(self.store,q,NOW)['volume'],36)
        for cfg in ({'end':END+3600},{'start':END},{'hours':2161},{'quality':'all'}):
            with self.assertRaises(ValueError):history_view.series(self.store,{**q,**cfg},NOW)


class ClothTests(unittest.TestCase):
    def test_all_25_original_variants_and_original_profits_preserved(self):
        data=refining.calculate({});self.assertEqual(len(data['rows']),25)
        r=data['rows'][0];self.assertEqual(r['cost_per_operation'],430)
        self.assertEqual(r['legacy_profit'],17768)
        self.assertAlmostEqual(r['legacy_profit_per_focus'],17768/971)
        self.assertEqual(data['global_fce'],13650)
        self.assertEqual(r['focus_first_batch'],368)

    def test_percent_and_explicit_coefficient_models_are_different(self):
        p=refining.calculate({});m=refining.calculate({'mode':'coefficient'})
        self.assertAlmostEqual(p['expected_output'],211.6007191767699)
        self.assertAlmostEqual(p['main_loop']['focus'],35079.16722512491)
        self.assertAlmostEqual(refining.calculate({'steps':4})['additional_output'],107.0514270441)
        self.assertEqual(m['expected_output'],211)
        self.assertEqual(m['rows'][0]['profit'],17768)

    def test_next_tier_same_enchantment_input_and_tax_station(self):
        base=refining.calculate({});rows=base['config']['rows'];rows[0]['cloth_buy']=999
        data=refining.calculate({'rows':rows,'tax_pct':10,'station':5,'return_rate':0})
        r=data['rows'][5];self.assertEqual(r['previous_price'],999)
        self.assertEqual(r['profit'],100*1000*.9-100*(430*3+999)-500)

    def test_all_steps_focus_and_unprocessed_residual_are_separate(self):
        d=refining.calculate({'batch':100,'return_rate':50,'steps':3})
        loop=d['main_loop'];self.assertEqual(loop['produced'],187.5)
        self.assertEqual(loop['remaining'],6.25)
        self.assertAlmostEqual(loop['focus'],sum(r['focus'] for r in loop['rows']))
        self.assertEqual(d['expected_output'],187.5)

    def test_integer_material_stock_stops_when_a_full_recipe_is_unavailable(self):
        d=refining.calculate({'batch':1,'rounding':'integer'})
        self.assertEqual(d['expected_output'],1)
        self.assertEqual(d['main_loop']['rows'][1]['input'],0)
        self.assertTrue(all(r['input']%1==0 for r in d['main_loop']['rows']))
        self.assertEqual(refining.calculate({'steps':0})['expected_output'],100)
        self.assertEqual(refining.calculate({'rounding':'integer'})['expected_output'],208)

    def test_settings_persist_and_levels_change_focus(self):
        with tempfile.TemporaryDirectory() as path:
            store=Store(path);before=refining.load(store)
            refining.save(store,{'batch':77,'levels':{str(t):0 for t in range(4,9)}})
            after=refining.load(Store(path));self.assertEqual(after['config']['batch'],77)
            self.assertGreater(after['rows'][0]['focus_first_batch'],before['rows'][0]['focus_first_batch'])

    def test_invalid_rates_steps_prices_and_duplicate_rows(self):
        for body in ({'return_rate':100},{'return_rate':float('nan')},{'steps':-1},{'batch':1.2},{'mode':'bad'},{'tax_pct':-1}):
            with self.assertRaises(ValueError):refining.calculate(body)
        rows=refining.defaults()['rows'];rows[1]=rows[0]
        with self.assertRaises(ValueError):refining.calculate({'rows':rows})

    def test_xlsx_has_formulas_updated_inputs_and_cached_results_without_external_links(self):
        body={'batch':77,'return_rate':50,'steps':3};computed=refining.calculate(body)
        ns={'m':refining.NS}
        with ZipFile(io.BytesIO(refining.workbook(body))) as z:
            self.assertFalse(any('externalLink' in n for n in z.namelist()))
            p=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(float(p.find(".//m:c[@r='B2']/m:v",ns).text),77)
            c=ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
            self.assertIsNotNone(c.find(".//m:c[@r='N7']/m:f",ns))
            self.assertAlmostEqual(float(c.find(".//m:c[@r='N7']/m:v",ns).text),computed['rows'][0]['profit'])
            self.assertIn('Исходная таблица',z.read('xl/workbook.xml').decode())
