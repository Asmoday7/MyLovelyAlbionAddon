import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.request import Request, urlopen

from albion_trade_desk import crafting, ingestion
from albion_trade_desk.catalog import import_catalog
from albion_trade_desk.storage import Store
from albion_trade_desk.web import make_server
from albion_trade_desk.domain import utcnow

NOW=1760005800
STAFF='T4_MAIN_NATURESTAFF_CRYSTAL'
MATERIALS=['T4_PLANKS','T4_CLOTH','T4_ARTEFACT_MAIN_NATURESTAFF_CRYSTAL']


def seed(store):
    ids=[STAFF,STAFF+'@1','T5_MAIN_NATURESTAFF_CRYSTAL',*MATERIALS,'T4_PLANKS_LEVEL1@1','T4_CLOTH_LEVEL1@1','T4_MEAL_STEW']
    names=[{'UniqueName':uid,'Index':i+1,'LocalizedNames':{'RU-RU':'Кузнечный посох' if 'NATURESTAFF_CRYSTAL' in uid and 'ARTEFACT' not in uid else uid,
        'EN-US':"Adept's Forgebark Staff" if uid.startswith(STAFF) or uid.startswith('T5_MAIN') else uid}} for i,uid in enumerate(ids)]
    resources=[{'@uniquename':MATERIALS[0],'@count':'16'},{'@uniquename':MATERIALS[1],'@count':'8'},
               {'@uniquename':MATERIALS[2],'@count':'1','@maxreturnamount':'0'}]
    raw={'items':{'weapon':[{'@uniquename':STAFF,'@tier':'4','craftingrequirements':{'craftresource':resources},
        'enchantments':{'enchantment':{'@enchantmentlevel':'1','craftingrequirements':{'craftresource':[
          {'@uniquename':'T4_PLANKS_LEVEL1','@enchantmentlevel':'1','@count':'16'},
          {'@uniquename':'T4_CLOTH_LEVEL1','@enchantmentlevel':'1','@count':'8'},resources[2]]}}}},
        {'@uniquename':'T5_MAIN_NATURESTAFF_CRYSTAL','craftingrequirements':{'craftresource':resources}}],
        'consumableitem':[{'@uniquename':'T4_MEAL_STEW','craftingrequirements':{'@amountcrafted':'10','@silver':'30',
          'craftresource':[{'@uniquename':'T4_CLOTH','@count':'3'},{'@uniquename':'T4_CLOTH','@count':'1'}]}}]}}
    import_catalog(store,names,raw)


def add_price(store,uid,price,*,city='Lymhurst',server='east',q=1,observed=NOW-10,kind='sell_price_min'):
    ingestion.prices(store,[{'item_id':uid,'city':city,'quality':q,kind:price,
        kind+'_date':datetime.fromtimestamp(observed,timezone.utc).isoformat()}],server)


class CraftingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);seed(self.store)

    def plan(self,**kwargs):
        return crafting.plan(self.store,{'item_id':STAFF,'city':'1002',**kwargs},now=NOW)

    def test_real_recipe_quantities_scale_without_inventing_return_rates(self):
        p=self.plan(units=10)
        self.assertEqual([r['quantity'] for r in p['resources']],[160,80,10])
        self.assertEqual(p['resources'][-1]['returnable_quantity'],0)
        self.assertIsNone(p['materials_cost'])
        self.assertEqual(p['ready_count'],0)

    def test_enchanted_material_ids_include_level_and_at_suffix(self):
        p=self.plan(item_id=STAFF+'@1')
        self.assertEqual([r['id'] for r in p['resources']],['T4_PLANKS_LEVEL1@1','T4_CLOTH_LEVEL1@1',MATERIALS[2]])
        self.assertFalse(any(r['catalogue_missing'] for r in p['resources']))
        add_price(self.store,'T4_PLANKS',1)
        self.assertIsNone(self.plan(item_id=STAFF+'@1')['materials_cost'])

    def test_old_lost_enchantment_recipe_resolves_only_existing_unique_catalogue_id(self):
        with self.store.connect() as db:
            resources=json.loads(db.execute('SELECT resources FROM recipes WHERE item_id=?',(STAFF+'@1',)).fetchone()[0])
            resources[0]['item_id']='T4_PLANKS_LEVEL1'
            db.execute('UPDATE recipes SET resources=? WHERE item_id=?',(json.dumps(resources),STAFF+'@1'))
        self.assertEqual(self.plan(item_id=STAFF+'@1')['resources'][0]['id'],'T4_PLANKS_LEVEL1@1')

    def test_correct_server_city_input_quality_and_separate_output_quality(self):
        for uid in MATERIALS:
            add_price(self.store,uid,10,server='west')
            add_price(self.store,uid,20,city='Caerleon')
            add_price(self.store,uid,30,q=2)
        self.assertEqual(self.plan()['ready_count'],0)
        for uid in MATERIALS: add_price(self.store,uid,40)
        add_price(self.store,STAFF,500,q=1)
        p=self.plan(output_quality=5)
        self.assertEqual(p['ready_count'],3)
        self.assertTrue(all(r['quality']==1 for r in p['resources']))
        self.assertIsNone(p['output_market']['quote'])

    def test_gross_cost_and_fixed_silver_for_multi_output_round_up(self):
        add_price(self.store,'T4_CLOTH',100)
        p=self.plan(item_id='T4_MEAL_STEW',units=11)
        self.assertEqual(p['operations'],2)
        self.assertEqual(p['produced'],20)
        self.assertEqual(p['overproduction'],9)
        self.assertEqual(len(p['resources']),1)
        self.assertEqual(p['resources'][0]['quantity'],8)
        self.assertEqual(p['materials_cost'],800)
        self.assertEqual(p['recipe_silver'],60)
        self.assertEqual(p['base_batch_cost'],860)
        self.assertEqual(p['base_unit_cost'],43)

    def test_missing_or_stale_is_not_zero_and_partial_cost_not_total(self):
        add_price(self.store,MATERIALS[0],100)
        add_price(self.store,MATERIALS[1],200,observed=NOW-7200)
        p=self.plan(max_age_hours=1)
        self.assertEqual([r['status'] for r in p['resources']],['ready','stale','missing'])
        self.assertIsNone(p['materials_cost'])
        self.assertIsNone(p['base_batch_cost'])
        self.assertEqual(p['known_materials_cost'],1600)

    def test_black_market_uses_buy_order_only_for_finished_item(self):
        add_price(self.store,STAFF,10000,city='Black Market')
        self.assertIsNone(self.plan(sale_city='3003')['output_market']['quote'])
        add_price(self.store,STAFF,500,city='Black Market',kind='buy_price_max')
        p=self.plan(sale_city='3003')
        self.assertEqual(p['output_market']['kind'],'buy_price_max')
        self.assertEqual(p['output_market']['quote']['price'],500)
        with self.assertRaises(ValueError): self.plan(city='3003')

    def test_spaced_english_search_returns_family_with_all_variants(self):
        rows=crafting.search(self.store,'forge bark')['results']
        self.assertEqual(len(rows),1)
        self.assertEqual(len(rows[0]['variants']),3)
        self.assertEqual({v['tier'] for v in rows[0]['variants']},{4,5})

    def test_save_reopen_and_live_price_updates(self):
        result=crafting.save(self.store,{'item_id':STAFF,'units':3,'city':'1002','scope':'public'})
        reopened=Store(self.temp.name)
        self.assertEqual(crafting.load(reopened,result['id'])['config']['units'],3)
        self.assertIsNone(crafting.load(reopened,result['id'])['materials_cost'])
        for uid in MATERIALS: add_price(reopened,uid,100,observed=utcnow()-10)
        updated=crafting.load(reopened,result['id'])
        self.assertEqual(updated['materials_cost'],7500)
        self.assertEqual(crafting.saved(reopened)['packs'][0]['id'],result['id'])

    def test_invalid_units_variant_and_scope_rejected(self):
        for units in (0,-1,1.5,float('nan'),1000001):
            with self.assertRaises(ValueError): self.plan(units=units)
        for cfg in ({'variant':9},{'scope':'evil'},{'item_id':'MISSING'}):
            with self.assertRaises(ValueError): self.plan(**cfg)

    def test_public_request_groups_materials_q1_and_output_q5_and_no_private_publish(self):
        calls=[]
        class Client: pass
        client=Client();client.store=self.store
        def fetch(client,ids,server,cities,qualities):
            calls.append((ids,server,cities,qualities));return {'prices':1,'history':2}
        with patch('albion_trade_desk.transport.refresh_market',fetch):
            result=crafting.refresh(client,{'item_id':STAFF,'output_quality':5,'city':'1002','sale_city':'3003'})
            self.assertEqual(result,{'prices':2,'history':4})
            self.assertEqual(calls,[(MATERIALS,'east',['1002'],[1]),([STAFF],'east',['3003'],[5])])
            with self.assertRaises(ValueError): crafting.refresh(client,{'item_id':STAFF,'scope':'private'})

    def test_local_enchanted_resource_normalization_and_private_readiness(self):
        ingestion.local_orders(self.store,{'Orders':[{'Id':42,'ItemTypeId':'T4_PLANKS_LEVEL1','LocationId':'1002',
          'QualityLevel':1,'EnchantmentLevel':1,'UnitPriceSilver':1000000,'Amount':16,'AuctionType':'offer','Expires':'2099-01-01T00:00:00Z'}]},source='private-client')
        p=crafting.plan(self.store,{'item_id':STAFF+'@1','scope':'private'},now=utcnow())
        self.assertEqual(p['resources'][0]['quote']['item_id'],'T4_PLANKS_LEVEL1@1')
        self.assertEqual(p['resources'][0]['quote']['source'],'private-client')


class CraftHttpTests(unittest.TestCase):
    def test_private_packet_changes_pack_progress_and_pack_survives_reopening(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);seed(store)
            server=make_server(store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def post(path,body):
                with urlopen(Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})) as r: return json.load(r)
            cfg={'item_id':STAFF,'city':'1002','scope':'private','units':2}
            try:
                self.assertEqual(post('/api/craft/plan',cfg)['ready_count'],0)
                saved=post('/api/craft/packs',cfg)
                post('/api/private/start',{'server':'east','experimental_ack':True})
                path=server.private_scanner.destination().removeprefix(base)
                post(path+'/marketorders.ingest',{'Orders':[{'Id':i+1,'ItemTypeId':uid,'LocationId':'1002','QualityLevel':1,
                     'UnitPriceSilver':1000000,'Amount':1,'AuctionType':'offer','Expires':'2099-01-01T00:00:00Z'} for i,uid in enumerate(MATERIALS)]})
                updated=post('/api/craft/plan',cfg)
                self.assertEqual(updated['ready_count'],3)
                self.assertEqual(updated['materials_cost'],5000)
                with urlopen(base+'/api/craft/pack?id='+saved['id']) as r: self.assertEqual(json.load(r)['ready_count'],3)
                post('/api/craft/delete',{'id':saved['id']})
                self.assertEqual(store.status()['orders'],3)
                self.assertEqual(crafting.saved(Store(directory))['packs'],[])
            finally:
                server.private_scanner.stop();server.public_nats.stop();server.shutdown();thread.join();server.server_close();server.jobs.executor.shutdown()
