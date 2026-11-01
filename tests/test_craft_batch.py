"""Mixed batches must share purchases without sharing fictitious profit or demand."""
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit

from albion_trade_desk import craft_batch, feeds
from albion_trade_desk.storage import Store
from test_crafting import seed, add_price, STAFF, MATERIALS, NOW


class BatchTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup)
        self.store=Store(d.name);seed(self.store)
        for uid,price in zip(MATERIALS,[10,20,100]):add_price(self.store,uid,price)
        add_price(self.store,STAFF,1000);add_price(self.store,'T4_MEAL_STEW',50)
        self.body={'city':'1002','sale_city':'1002','server':'east',
            'lines':[{'item_id':STAFF,'units':10,'focus_per_operation':100},
                     {'item_id':'T4_MEAL_STEW','units':11,'focus_per_operation':300}],
            'no_focus_return':20,'focus_return':40,'station_per_operation':5,'transport':100}

    def plan(self,**kw):return craft_batch.plan(self.store,{**self.body,**kw},NOW)

    def test_shared_materials_multi_output_rounding_and_nonreturnable_artifact(self):
        p=self.plan();r={r['id']:r for r in p['resources']}
        self.assertEqual([r[uid]['quantity'] for uid in MATERIALS],[160,88,10])
        self.assertEqual(p['lines'][1]['produced'],20)
        self.assertEqual(p['lines'][1]['overproduction'],9)
        self.assertEqual(p['lines'][0]['models']['no_focus']['returned_value'],640)
        self.assertEqual(p['lines'][0]['models']['focus']['returned_value'],1280)
        self.assertEqual(p['summary']['materials_cost'],4360)
        self.assertEqual(p['summary']['cash_profit'],5265)
        self.assertEqual(p['summary']['no_focus_profit'],5937)
        self.assertEqual(p['summary']['focus_profit'],6609)
        self.assertEqual(p['summary']['focus'],1600)
        self.assertEqual(p['lines'][0]['silver_per_focus'],.64)

    def test_existing_stock_changes_purchase_budget_but_never_makes_consumed_inputs_free(self):
        p=self.plan(materials={'east:1002:T4_PLANKS':{'bought':100}})
        self.assertEqual(p['summary']['remaining_budget'],3360)
        self.assertEqual(p['summary']['materials_cost'],4360)
        self.assertEqual(p['summary']['no_focus_profit'],5937)
        self.assertEqual(next(r for r in p['resources'] if r['id']=='T4_PLANKS')['remaining'],60)

    def test_purchase_orders_and_instant_sales_use_opposite_quotes_and_correct_fees(self):
        for uid,price in zip(MATERIALS,[9,18,90]):add_price(self.store,uid,price,kind='buy_price_max')
        add_price(self.store,STAFF,1000,kind='buy_price_max')
        p=self.plan(lines=[{'item_id':STAFF,'units':1}],buy_mode='order',sell_mode='instant',
                    no_focus_return=0,focus_return=0,station_per_operation=0,transport=0)
        self.assertEqual(p['summary']['materials_cost'],378)
        self.assertEqual(p['lines'][0]['purchase_fee'],9.45)
        self.assertEqual(p['summary']['cash_profit'],532.55)

    def test_missing_prices_and_unconfigured_returns_are_not_zero_or_guessed_focus(self):
        p=self.plan(no_focus_return=None,focus_return=None)
        self.assertIsNone(p['summary']['no_focus_profit'])
        self.assertEqual(p['summary']['cash_profit'],5265)
        with self.store.connect() as db:db.execute('DELETE FROM quotes WHERE item_id=?',(MATERIALS[2],))
        p=self.plan()
        self.assertIsNone(p['summary']['materials_cost'])
        self.assertIsNone(p['summary']['focus_profit'])
        self.assertIsNone(p['lines'][0]['models']['focus']['profit'])
        # A manual price is explicit and can restore the calculation.
        p=self.plan(materials={'east:1002:'+MATERIALS[2]:{'price':100}})
        self.assertEqual(p['summary']['no_focus_profit'],5937)

    def test_quality_and_enchantment_are_exact_and_no_focus_cost_is_inferred_from_base(self):
        p=self.plan(lines=[{'item_id':STAFF,'units':1,'output_quality':5}])
        self.assertIsNone(p['lines'][0]['output_price'])
        self.assertIsNone(p['summary']['focus'])
        self.assertIsNone(p['lines'][0]['silver_per_focus'])
        with self.assertRaises(ValueError):self.plan(lines=[{'item_id':STAFF,'output_quality':'auto'}])

    def test_missing_liquidity_is_unknown_and_coarse_observations_do_not_claim_complete_history(self):
        p=self.plan();self.assertIsNone(p['lines'][0]['liquidity']['recommended_units'])
        end=NOW//3600*3600
        feeds.ingest(self.store,'markethistories.ingest',{'AlbionId':1,'LocationId':'1000',
            'QualityLevel':1,'Timescale':1,'MarketHistories':[
                {'Timestamp':(end-i*21600)*10000000+621355968000000000,'ItemAmount':1,'SilverAmount':10000000}
                for i in range(28)]},'east')
        l=self.plan()['lines'][0]['liquidity']
        self.assertEqual((l['known_sales'],l['point_count'],l['recommended_units']),(28,28,2))
        self.assertFalse(l['complete']);self.assertTrue(l['above_recommendation'])
        p=self.plan(scope='public');self.assertIsNone(p['lines'][0]['liquidity']['known_sales'])

    def test_per_station_rate_override_does_not_change_other_lines(self):
        lines=[{**self.body['lines'][0],'no_focus_return':30},self.body['lines'][1]]
        p=self.plan(lines=lines)
        self.assertEqual(p['lines'][0]['models']['no_focus']['returned_value'],960)
        self.assertEqual(p['lines'][1]['models']['no_focus']['returned_value'],32)

    def test_save_roundtrip_preserves_mixed_lines_rates_and_purchase_progress(self):
        body={**self.body,'name':'Разные крафты','materials':{'east:1002:T4_PLANKS':{'bought':100}}}
        with patch('albion_trade_desk.craft_batch.utcnow',return_value=NOW):
            result=craft_batch.save(self.store,body)
            loaded=craft_batch.load(Store(self.store.directory),result['id'])
        self.assertEqual(loaded['summary']['remaining_budget'],3360)
        self.assertEqual(loaded['config']['no_focus_return'],20)
        self.assertEqual(craft_batch.saved(self.store)['batches'][0]['name'],'Разные крафты')

    def test_crystal_set_selects_existing_weapon_variants_without_fabricating_a_recipe(self):
        p=craft_batch.crystal_set(self.store,{'tier':4,'enchantment':1})
        self.assertEqual([r['config']['item_id'] for r in p['lines']],[STAFF+'@1'])
        for body in ({'tier':4,'enchantment':4},{'tier':4.5,'enchantment':0}):
            with self.assertRaises(ValueError):craft_batch.crystal_set(self.store,body)

    def test_public_refresh_downloads_shared_inputs_once_and_both_history_resolutions(self):
        class Client:
            store=self.store
            def __init__(self):self.urls=[]
            def get(self,url,ttl=900):self.urls.append(url);return []
        client=Client();craft_batch.refresh(client,self.body)
        prices=[u for u in client.urls if '/prices/' in u]
        histories=[u for u in client.urls if '/history/' in u]
        self.assertEqual(len(prices),1)
        self.assertEqual(len(histories),2)
        self.assertEqual([parse_qs(urlsplit(u).query)['time-scale'][0] for u in histories],['1','6'])
        self.assertNotIn('T4_PLANKS',urlsplit(histories[0]).path)


if __name__=='__main__':unittest.main()
