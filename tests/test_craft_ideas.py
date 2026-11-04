"""Recommendations must use ordinary qualities, signed profit and observed demand."""
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit,unquote
from albion_trade_desk import craft_ideas,craft_batch,feeds
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.storage import Store
from test_crafting import seed,add_price,STAFF,MATERIALS,NOW

AXE='T4_MAIN_AXE';HELM='T4_HEAD_PLATE_SET1';BOOK='T4_OFF_BOOK'


class CraftIdeasTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory();self.addCleanup(d.cleanup);self.store=Store(d.name);seed(self.store)
        for index,uid in enumerate((AXE,HELM,BOOK),100):
            import_catalog(self.store,[{'UniqueName':uid,'Index':index,'LocalizedNames':{'EN-US':uid,'RU-RU':uid}}])
            with self.store.connect() as db:
                db.execute('INSERT INTO recipes SELECT ?,variant,output,focus,silver,resources FROM recipes WHERE item_id=?',(uid,STAFF))
        for uid,price in zip(MATERIALS,(10,20,100)):add_price(self.store,uid,price)
        for q,price in [(1,1000),(2,900),(3,1100),(4,1050),(5,999999)]:add_price(self.store,STAFF,price,q=q)
        add_price(self.store,AXE,100);add_price(self.store,HELM,2000);add_price(self.store,BOOK,1000000,q=5)
        for q,qty in [(1,20),(2,30),(3,40),(4,50),(5,1000)]:self.history(1,q,qty)
        self.history(100,1,50);self.history(101,1,5);self.history(102,5,5000)

    def history(self,index,q,qty):
        end=NOW//3600*3600
        feeds.ingest(self.store,'markethistories.ingest',{'AlbionId':index,'LocationId':'1000','QualityLevel':q,'Timescale':1,
            'MarketHistories':[{'Timestamp':(end-21600)*10000000+621355968000000000,'ItemAmount':qty,'SilverAmount':qty*10000000}]},'east')

    def analyze(self,**kw):return craft_ideas.analyze(self.store,{'city':'1002','sale_city':'1002','show':'all',**kw},NOW)

    def large_market(self,priced=False,tier=4):
        ids=[f'T{tier}_MAIN_TEST_{i:03}' for i in range(305)]
        import_catalog(self.store,[{'UniqueName':uid,'Index':200+i,
            'LocalizedNames':{'RU-RU':f'Тест {i:03}'}} for i,uid in enumerate(ids)])
        with self.store.connect() as db:
            db.executemany('INSERT INTO recipes SELECT ?,variant,output,focus,silver,resources FROM recipes WHERE item_id=?',
                [(uid,STAFF) for uid in ids])
        if priced:
            for uid in ids:add_price(self.store,uid,1000)
        return ids

    def test_all_frames_visible_masterpiece_not_averaged_and_no_premium_fees_applied(self):
        r=next(r for r in self.analyze()['rows'] if r['item']['id']==STAFF)
        self.assertEqual(len(r['qualities']),5)
        self.assertEqual(r['overview']['known_sales'],140)
        self.assertEqual(r['qualities'][4]['liquidity']['known_sales'],1000)
        self.assertEqual(r['overview']['price_min'],900)
        self.assertEqual(r['overview']['price_max'],1100)
        self.assertEqual(r['profit'],385.5)  # 900 * (1 - 8% - 2.5%) - 420
        self.assertTrue(r['recommended']);self.assertFalse(r['overview']['sales_complete'])

    def test_signed_sort_both_directions_keeps_missing_values_last(self):
        desc=self.analyze(sort='profit_desc')['rows'];asc=self.analyze(sort='profit_asc')['rows']
        self.assertEqual([r['item']['id'] for r in desc],[HELM,STAFF,AXE,BOOK])
        self.assertEqual([r['item']['id'] for r in asc],[AXE,STAFF,HELM,BOOK])
        self.assertLess(asc[0]['profit'],0);self.assertIsNone(asc[-1]['profit'])

    def test_recommendations_require_profit_ordinary_price_and_enough_sales(self):
        data=self.analyze(show='recommended')
        self.assertEqual([r['item']['id'] for r in data['rows']],[STAFF])
        # High unit profit alone does not make a slow-selling helmet recommended.
        self.assertGreater(self.analyze()['rows'][0]['profit'],data['rows'][0]['profit'])
        self.assertEqual([r['item']['id'] for r in self.analyze(show='loss')['rows']],[AXE])

    def test_missing_ordinary_quality_cannot_recommend_a_rare_expensive_frame(self):
        add_price(self.store,BOOK,8000,q=3);self.history(102,3,500)
        row=next(r for r in self.analyze()['rows'] if r['item']['id']==BOOK)
        self.assertGreater(row['overview']['models']['no_focus']['unit_profit_min'],0)
        self.assertIsNone(row['profit']);self.assertFalse(row['recommended'])

    def test_zero_sales_or_a_share_below_one_operation_never_recommended(self):
        with self.store.connect() as db:db.execute('DELETE FROM native_history')
        self.history(1,1,0)
        row=next(r for r in self.analyze(min_sales=0)['rows'] if r['item']['id']==STAFF)
        self.assertEqual(row['known_sales'],0);self.assertFalse(row['recommended'])
        self.history(1,1,5)
        row=next(r for r in self.analyze(min_sales=0)['rows'] if r['item']['id']==STAFF)
        self.assertEqual(row['suggested_limit'],0);self.assertFalse(row['recommended'])

    def test_mixed_profit_filter_and_missing_history_are_not_zero_demand(self):
        add_price(self.store,AXE,1000,q=3)
        self.assertEqual([r['item']['id'] for r in self.analyze(show='mixed')['rows']],[AXE])
        row=next(r for r in self.analyze()['rows'] if r['item']['id']==BOOK)
        self.assertIsNone(row['known_sales'])  # Masterpiece trades cannot fill I-IV history.

    def test_source_region_tier_category_and_recipe_validity_are_respected(self):
        self.assertEqual(self.analyze(scope='public',show='recommended')['total'],0)
        self.assertEqual(self.analyze(server='west',show='recommended')['total'],0)
        self.assertEqual([r['item']['id'] for r in self.analyze(enchantment=1)['rows']],[STAFF+'@1'])
        self.assertEqual([r['item']['id'] for r in self.analyze(category='armor')['rows']],[HELM])
        with self.store.connect() as db:db.execute("UPDATE recipes SET resources='[]' WHERE item_id=?",(AXE,))
        report=self.analyze()
        self.assertEqual(len(report['unsupported_recipes']),1)
        self.assertTrue(any(r['item']['id']==STAFF for r in report['rows']))

    def test_refresh_fetches_all_five_output_qualities_and_shared_inputs_once(self):
        class Client:
            store=self.store
            def __init__(self):self.urls=[]
            def get(self,url,ttl=900):self.urls.append(url);return []
        client=Client();progress=[]
        with patch('albion_trade_desk.craft_ideas.utcnow',return_value=NOW):
            result=craft_ideas.refresh(client,{'city':'1002','category':'crystal'},progress.append)
        prices=[u for u in client.urls if '/prices/' in u]
        history=[u for u in client.urls if '/history/' in u]
        self.assertEqual(len(prices),5);self.assertEqual(len(history),10)
        self.assertEqual({parse_qs(urlsplit(u).query)['qualities'][0] for u in history},{'1','2','3','4','5'})
        self.assertEqual(sum('T4_PLANKS' in urlsplit(u).path for u in prices),1)
        self.assertEqual(progress[-1]['done'],progress[-1]['total'])
        self.assertEqual(result['candidates'],1)

    def test_full_market_returns_all_candidates_and_ranks_late_variants(self):
        ids=self.large_market(priced=True)
        add_price(self.store,ids[-1],100000)
        self.history(504,1,50)
        with self.store.connect() as db:
            # The best variant and an invalid recipe both lie beyond the former 300-recipe cutoff.
            db.execute('INSERT INTO recipes SELECT item_id,1,2,focus,silver,resources FROM recipes WHERE item_id=?',(ids[-1],))
            db.execute("UPDATE recipes SET resources='[]' WHERE item_id=?",(ids[-2],))
        report=self.analyze(limit=8)
        self.assertEqual(report['matched_recipes'],310)
        self.assertEqual(report['evaluated_recipes'],310)
        self.assertEqual(report['evaluated_items'],308)
        self.assertEqual(report['total'],308)
        self.assertEqual(len(report['rows']),308)
        best=report['rows'][0]
        self.assertEqual(best['item']['id'],ids[-1]);self.assertEqual(best['variant'],1)
        self.assertTrue(best['recommended'])
        self.assertEqual([(r['id'],r['variant']) for r in report['unsupported_recipes']],[(ids[-2],0)])
        tail=self.analyze(offset=300,limit=50,sort='profit_asc')
        self.assertEqual(tail['total'],308);self.assertEqual(len(tail['rows']),308)
        self.assertIn(ids[-1],[r['item']['id'] for r in tail['rows']])
        self.assertEqual(tail['counts'],report['counts'])

    def test_full_market_counts_unpriced_recipes_without_hiding_missing_data(self):
        ids=self.large_market()
        report=self.analyze(show='missing',offset=300,limit=50)
        self.assertEqual(report['evaluated_recipes'],309)
        self.assertEqual(report['matched_recipes'],309)
        self.assertEqual(report['counts']['missing'],306)  # All 305 unpriced items and the masterpiece-only book.
        self.assertEqual(report['total'],306)
        self.assertEqual(len(report['rows']),306)
        self.assertIn(ids[-1],[r['item']['id'] for r in report['rows']])
        self.assertTrue(all(r['profit'] is None and not r['recommended'] for r in report['rows']))

    def test_full_market_refresh_includes_late_outputs_and_deduplicates_shared_inputs(self):
        ids=self.large_market()
        class Client:
            store=self.store
            def __init__(self):self.urls=[]
            def get(self,url,ttl=900):self.urls.append(url);return []
        client=Client();progress=[]
        with patch('albion_trade_desk.craft_ideas.utcnow',return_value=NOW):
            report=craft_ideas.refresh(client,{'city':'1002'},progress.append)
        self.assertEqual(report['candidates'],309);self.assertEqual(report['matched_recipes'],309)
        self.assertEqual(report['unsupported'],0)
        for kind in ('prices','history'):
            for q in range(1,6):
                fetched=[uid for url in client.urls if f'/{kind}/' in url and parse_qs(urlsplit(url).query)['qualities']==[str(q)]
                    for uid in unquote(urlsplit(url).path.rsplit('/',1)[-1]).removesuffix('.json').split(',')]
                self.assertTrue(set(ids).issubset(fetched))
                self.assertIn(STAFF,fetched)
                if kind=='prices':
                    self.assertEqual(len(fetched),len(set(fetched)))
                    self.assertEqual(fetched.count(MATERIALS[0]),1 if q==1 else 0)
        self.assertEqual(progress[-1]['done'],progress[-1]['total'])

    def test_analysis_uses_one_snapshot_and_sees_new_prices_on_the_next_run(self):
        original=craft_batch.plan
        changed=False
        def incoming_price(store,body,now):
            nonlocal changed
            if not changed:
                add_price(self.store,HELM,100,observed=NOW)
                changed=True
            return original(store,body,now)
        with patch('albion_trade_desk.craft_ideas.craft_batch.plan',side_effect=incoming_price):
            before=self.analyze()
        self.assertEqual(before['rows'][0]['item']['id'],HELM)
        after=self.analyze()
        helmet=next(r for r in after['rows'] if r['item']['id']==HELM)
        self.assertLess(helmet['profit'],0)
        self.assertEqual(after['rows'][0]['item']['id'],STAFF)

    def test_all_quality_batch_preserves_quantities_and_exports_without_selecting_a_frame(self):
        p=craft_batch.plan(self.store,{'city':'1002','all_qualities':True,'no_focus_return':0,
            'lines':[{'item_id':STAFF,'units':10,'output_quality':3}]},NOW)
        self.assertEqual([r['quantity'] for r in p['resources']],[160,80,10])
        self.assertEqual(p['summary']['no_focus_range']['min'],3855)
        self.assertEqual(p['summary']['no_focus_range']['max'],5645)
        self.assertEqual(p['lines'][0]['overview']['known_sales'],140)


if __name__=='__main__':unittest.main()
