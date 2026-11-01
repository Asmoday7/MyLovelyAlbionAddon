"""Clipboard JSON v1 is verified against the user's real in-game relic example."""
import json
import tempfile
import unittest

from albion_trade_desk.craft_batch import inventory_presets,loadouts
from albion_trade_desk.storage import Store
from test_crafting import seed,STAFF


def resource(uid='T4_RELIC',qty=48,remaining=None,max_stack=999):
    return {'id':uid,'quantity':qty,'remaining':qty if remaining is None else remaining,
            'max_stack':max_stack,'catalogue_missing':False}


class LoadoutCodeTests(unittest.TestCase):
    def test_real_game_example_roundtrips_exact_schema(self):
        expected={'version':1,'name':'Т4 Рекликты','icon':6,
                  'inventory':[{'item':'T4_RELIC','quality':1,'stack':48}]}
        result=inventory_presets([resource()],expected['name'])
        self.assertEqual(json.loads(result['presets'][0]['text']),expected)
        self.assertIn('Т4 Рекликты',result['presets'][0]['text'])
        self.assertEqual(result['quantity'],48)

    def test_multiple_materials_and_large_stacks_preserve_exact_total_quantities(self):
        rows=[resource('T4_PLANKS_LEVEL3@3',2500),resource('T4_CLOTH',100),resource('T4_RELIC',10)]
        result=inventory_presets(rows,entries_per_code=2)
        self.assertEqual(len(result['presets']),3)
        counts={}
        for preset in result['presets']:
            obj=json.loads(preset['text']);self.assertEqual(set(obj),{'version','name','icon','inventory'})
            self.assertLessEqual(len(obj['inventory']),2)
            for row in obj['inventory']:
                self.assertEqual(set(row),{'item','quality','stack'})
                self.assertTrue(1<=row['stack']<=999)
                self.assertEqual(row['quality'],1)
                counts[row['item']]=counts.get(row['item'],0)+row['stack']
        self.assertEqual(counts,{'T4_PLANKS_LEVEL3@3':2500,'T4_CLOTH':100,'T4_RELIC':10})

    def test_existing_purchases_are_omitted_unless_explicitly_included(self):
        rows=[resource(qty=100,remaining=40),resource('T4_CLOTH',qty=80,remaining=0)]
        result=inventory_presets(rows)
        self.assertEqual(json.loads(result['presets'][0]['text'])['inventory'],[{'item':'T4_RELIC','quality':1,'stack':40}])
        self.assertEqual(inventory_presets(rows,include_owned=True)['quantity'],180)

    def test_nonstackable_ingredients_have_one_item_per_inventory_entry(self):
        result=inventory_presets([resource('T4_CAPE',3,max_stack=1)])
        rows=json.loads(result['presets'][0]['text'])['inventory']
        self.assertEqual(len(rows),3);self.assertTrue(all(r['stack']==1 for r in rows))

    def test_invalid_quantities_ids_limits_and_unknown_catalogue_are_rejected(self):
        for row in [resource(qty=-1),resource(qty=1.5),resource('bad item'),{**resource(),'catalogue_missing':True}]:
            with self.assertRaises(ValueError):inventory_presets([row])
        for options in [{'entries_per_code':0},{'entries_per_code':49},{'max_stack':0},{'include_owned':'true'}]:
            with self.assertRaises(ValueError):inventory_presets([resource()],**options)
        with self.assertRaises(ValueError):inventory_presets([resource(qty=0)])
        with self.assertRaises(ValueError):inventory_presets([resource(qty=5000001)])

    def test_real_batch_export_uses_canonical_game_ids_and_remaining_amounts_without_prices(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d);seed(store)
            result=loadouts(store,{'lines':[{'item_id':STAFF,'units':10}],
                'materials':{'east:1002:T4_PLANKS':{'bought':100}},'city':'1002','name':'Покупка'})
            rows=json.loads(result['presets'][0]['text'])['inventory']
            self.assertEqual(rows[0],{'item':'T4_PLANKS','quality':1,'stack':60})
            self.assertEqual(rows[1]['stack'],80)
            self.assertEqual(rows[2]['stack'],10)
            self.assertNotIn('price',result['presets'][0]['text'])


if __name__=='__main__':unittest.main()
