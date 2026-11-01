"""Mixed recipe batches, a shared shopping list, and explicit economic scenarios."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import json
import re
import uuid

from . import crafting, history_view, ingestion
from .domain import number, utcnow


def output_qualities(uid):
    """Known commodities have no equipment quality distribution."""
    return (1,) if re.match(r'^T\d+_(?:MEAL_|POTION_|PLANKS(?:_|$)|CLOTH(?:_|$)|METALBAR(?:_|$)|LEATHER(?:_|$)|STONEBLOCK(?:_|$))',uid) else (1,2,3,4,5)


def liquidity_stats(history, produced, cfg):
    known=history['known_quantity']
    cap=int((dec(known)*dec(cfg['liquidity_share_pct'])/100).to_integral_value(rounding=ROUND_FLOOR)) if known is not None else None
    return {'known_sales':known,'complete':history.get('volume') is not None,
        'known_hours':history['known_hours'],'expected_hours':168,'point_count':history.get('point_count'),
        'recommended_units':cap,'above_recommendation':cap is not None and produced>cap,
        'estimated_days':value(produced*7/dec(known)) if known and history.get('volume') is not None else None}


def frame_overview(frames):
    regular=[q for q in frames if q['quality']<5 and q['applicable']]
    priced=[q for q in regular if q['price'] is not None]
    known=[q['liquidity']['known_sales'] for q in regular if q['liquidity']['known_sales'] is not None]
    result={'price_min':min((q['price'] for q in priced),default=None),
        'price_max':max((q['price'] for q in priced),default=None),
        'priced_qualities':len(priced),'applicable_qualities':len(regular),
        'ordinary_price_known':any(q['quality']==1 for q in priced),
        'known_sales':sum(known) if known else None,
        'sales_complete':all(q['liquidity']['complete'] for q in regular),
        'sales_qualities_known':len(known),'models':{}}
    for model in ('no_focus','focus'):
        profits=[q['models'][model]['profit'] for q in regular if q['models'][model]['profit'] is not None]
        units=[q['models'][model]['unit_profit'] for q in regular if q['models'][model]['unit_profit'] is not None]
        low=min(units,default=None)
        result['models'][model]={'profit_min':min(profits,default=None),'profit_max':max(profits,default=None),
            'unit_profit_min':low,'unit_profit_max':max(units,default=None),
            'rank_profit':low if result['ordinary_price_known'] else None}
    return result


def quality_frames(store, db, cfg, line, produced, costs, refundable_cost, missing, purchase_fee, fixed, now):
    frames=[]
    kind='buy_price_max' if cfg['sale_city']=='3003' or cfg['sell_mode']=='instant' else 'sell_price_min'
    fees=(dec(cfg['sales_tax_pct'])+(dec(cfg['setup_fee_pct']) if kind=='sell_price_min' else 0))/100
    applicable=output_qualities(line['item_id'])
    for q in range(1,6):
        quote=crafting.quote(db,cfg,line['item_id'],cfg['sale_city'],q,kind,now) if q in applicable else None
        manual=line['sale_price'] if q==line['output_quality'] else None
        price=manual if manual is not None else quote['price'] if quote and quote['fresh'] else None
        revenue=produced*dec(price)*(1-fees) if price is not None else None
        cash=revenue-costs-purchase_fee-fixed if revenue is not None and not missing else None
        models={}
        for model in ('no_focus','focus'):
            rate=line[model+'_return'] if line[model+'_return'] is not None else cfg[model+'_return']
            returned=refundable_cost*dec(rate)/100 if rate is not None and not missing else None
            profit=cash+returned if cash is not None and returned is not None else None
            models[model]={'profit':value(profit),'unit_profit':value(profit/produced) if profit is not None else None}
        if q in applicable:
            history=history_view.series(store,{'id':line['item_id'],'server':cfg['server'],'city':cfg['sale_city'],
                'quality':q,'scope':cfg['scope'],'hours':168},now)
            liquidity=liquidity_stats(history,produced,cfg)
        else:
            liquidity={'known_sales':None,'complete':False,'known_hours':0,'point_count':None,'recommended_units':None}
        frames.append({'quality':q,'applicable':q in applicable,'price':price,'quote':quote,'models':models,'liquidity':liquidity})
    return frames


def optional(value, maximum=1e12):
    return None if value in (None, '') else number(value, 0, maximum)


def config(body):
    lines = body.get('lines')
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise ValueError('Добавьте от 1 до 100 рецептов в партию')
    buy, sell = body.get('buy_mode', 'instant'), body.get('sell_mode', 'order')
    all_qualities=body.get('all_qualities',False)
    if type(all_qualities) is not bool: raise ValueError('all_qualities должен быть boolean')
    if buy not in ('instant', 'order') or sell not in ('instant', 'order'):
        raise ValueError('Неизвестный способ закупки или продажи')
    cfg = {k: body[k] for k in ('server','city','sale_city','scope','max_age_hours') if k in body}
    result, seen = [], set()
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError('Некорректная строка партии')
        parsed = crafting.config({**cfg, **{k: line[k] for k in ('item_id','units','variant','output_quality') if k in line}})
        if parsed['output_quality'] == 'auto':
            raise ValueError('Для сравнения прибыли выберите конкретное качество готового предмета')
        key = line.get('line_id') or uuid.uuid4().hex
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', key) or key in seen:
            raise ValueError('Повторный или некорректный идентификатор строки')
        seen.add(key)
        result.append({**{k: parsed[k] for k in ('item_id','units','variant','output_quality')},
            'line_id': key, 'no_focus_return': optional(line.get('no_focus_return'),99.9),
            'focus_return': optional(line.get('focus_return'),99.9),
            'focus_per_operation': optional(line.get('focus_per_operation')),
            'station_per_operation': optional(line.get('station_per_operation')),
            'sale_price': optional(line.get('sale_price'))})
    context = crafting.config({**cfg, 'item_id': result[0]['item_id']})
    stocks = body.get('materials', {})
    if not isinstance(stocks, dict) or len(stocks) > 2000:
        raise ValueError('Некорректный список купленных материалов')
    materials = {}
    for key, value in stocks.items():
        if not isinstance(key, str) or len(key) > 200 or not isinstance(value, dict):
            raise ValueError('Некорректная строка материала')
        materials[key] = {'bought': number(value.get('bought',0),0,1e12), 'price': optional(value.get('price'))}
    return {**{k: context[k] for k in ('server','city','sale_city','scope','max_age_hours')},
        'lines': result, 'materials': materials, 'buy_mode': buy, 'sell_mode': sell,'all_qualities':all_qualities,
        'sales_tax_pct': number(body.get('sales_tax_pct',8),0,100),
        'setup_fee_pct': number(body.get('setup_fee_pct',2.5),0,100),
        'no_focus_return': optional(body.get('no_focus_return'),99.9),
        'focus_return': optional(body.get('focus_return'),99.9),
        'station_per_operation': number(body.get('station_per_operation',0),0,1e12),
        'transport': number(body.get('transport',0),0,1e12),
        'liquidity_share_pct': number(body.get('liquidity_share_pct',10),0,100)}


def dec(value):
    return Decimal(str(value))


def value(value):
    return None if value is None else crafting.n(value)


def plan(store, body, now=None):
    cfg, now = config(body), utcnow() if now is None else now
    totals = defaultdict(lambda: Decimal(0))
    material_rows, line_rows = {}, []
    for line in cfg['lines']:
        recipe = crafting.plan(store, {**cfg, **line}, now)
        costs, return_value, missing = Decimal(0), Decimal(0), 0
        with store.connect() as db:
            for resource in recipe['resources']:
                key = f"{cfg['server']}:{cfg['city']}:{resource['id']}"
                choice = cfg['materials'].get(key, {})
                quote = crafting.quote(db,cfg,resource['id'],cfg['city'],1,
                    'sell_price_min' if cfg['buy_mode']=='instant' else 'buy_price_max',now)
                manual = choice.get('price')
                price = manual if manual is not None else quote['price'] if quote and quote['fresh'] else None
                quantity, refundable = dec(resource['quantity']), dec(resource['returnable_quantity'])
                if key not in material_rows:
                    stored = db.execute('SELECT metadata FROM items WHERE id=?',(resource['id'],)).fetchone()
                    metadata = json.loads(stored['metadata']) if stored else {}
                    stack = metadata.get('max_stack')
                    # Equipment ingredients (e.g. a cape) cannot be stacked like resources.
                    stack = min(999,int(number(stack,1,1e9))) if stack is not None else 1 if metadata.get('kind') in ('weapon','equipmentitem','mount','mountskin','skin') else 999
                    material_rows[key] = {**{k:resource[k] for k in ('id','name_ru','name_en','tier','enchantment','catalogue_missing')},
                        'key':key, 'quantity':Decimal(0), 'quality':1, 'location':cfg['city'],
                        'bought':dec(choice.get('bought',0)), 'quote':quote, 'price':price,
                        'manual_price':manual, 'max_stack':stack, 'status':'manual' if manual is not None else 'ready' if price is not None else 'stale' if quote else 'missing'}
                material_rows[key]['quantity'] += quantity
                if price is None:
                    missing += 1
                else:
                    costs += quantity*dec(price)
                    return_value += refundable*dec(price)
            out_kind = 'buy_price_max' if cfg['sale_city']=='3003' or cfg['sell_mode']=='instant' else 'sell_price_min'
            out_quote = crafting.quote(db,cfg,line['item_id'],cfg['sale_city'],line['output_quality'],out_kind,now)
        sale_price = line['sale_price'] if line['sale_price'] is not None else out_quote['price'] if out_quote and out_quote['fresh'] else None
        produced = dec(recipe['produced'])
        revenue = produced*dec(sale_price) if sale_price is not None else None
        sale_fees = (dec(cfg['sales_tax_pct'])+(dec(cfg['setup_fee_pct']) if cfg['sell_mode']=='order' and cfg['sale_city']!='3003' else 0))/100
        net_revenue = revenue*(Decimal(1)-sale_fees) if revenue is not None else None
        purchase_fee = costs*dec(cfg['setup_fee_pct'])/100 if cfg['buy_mode']=='order' else Decimal(0)
        station = line['station_per_operation'] if line['station_per_operation'] is not None else cfg['station_per_operation']
        fixed = dec(recipe['recipe_silver'])+dec(station)*recipe['operations']
        complete = not missing and net_revenue is not None
        cash_profit = net_revenue-costs-purchase_fee-fixed if complete else None
        models = {}
        for name in ('no_focus','focus'):
            rate = line[name+'_return'] if line[name+'_return'] is not None else cfg[name+'_return']
            returned = return_value*dec(rate)/100 if rate is not None and not missing else None
            profit = cash_profit+returned if cash_profit is not None and returned is not None else None
            net_cost = costs+purchase_fee+fixed-returned if returned is not None and not missing else None
            models[name] = {'return_pct':rate, 'returned_value':value(returned), 'profit':value(profit),
                'unit_profit':value(profit/produced) if profit is not None else None,
                'net_cost':value(net_cost), 'roi_pct':value(profit/net_cost*100) if profit is not None and net_cost else None}
        focus = dec(line['focus_per_operation'])*recipe['operations'] if line['focus_per_operation'] is not None else None
        delta = dec(models['focus']['profit'])-dec(models['no_focus']['profit']) if all(models[n]['profit'] is not None for n in models) else None
        history = history_view.series(store, {'id':line['item_id'],'server':cfg['server'],'city':cfg['sale_city'],
            'quality':line['output_quality'],'scope':cfg['scope'],'hours':168},now)
        liquidity=liquidity_stats(history,produced,cfg)
        line_rows.append({'config':line, 'item':recipe['item'], 'operations':recipe['operations'],
            'produced':recipe['produced'],'overproduction':recipe['overproduction'],
            'gross_materials_cost':value(costs) if not missing else None,'known_materials_cost':value(costs),
            'purchase_fee':value(purchase_fee),'recipe_and_station_cost':value(fixed),
            'output_quote':out_quote,'output_price':sale_price,'net_revenue':value(net_revenue),
            'cash_profit':value(cash_profit),'models':models,'focus':value(focus),
            'base_focus_per_operation':recipe['base_focus_per_operation'],
            'silver_per_focus':value(delta/focus) if delta is not None and focus else None,
            'missing_prices':missing+int(sale_price is None),'liquidity':liquidity})
        if cfg['all_qualities']:
            with store.connect() as db:
                frames=quality_frames(store,db,cfg,line,produced,costs,return_value,missing,purchase_fee,fixed,now)
            line_rows[-1]['quality_summary']=frames
            line_rows[-1]['overview']=frame_overview(frames)
        if net_revenue is not None: totals['net_revenue'] += net_revenue
        if complete: totals['cash_profit'] += cash_profit
        if not complete: totals['incomplete_lines'] += 1
        if focus is None: totals['unknown_focus'] += 1
        else: totals['focus_spent'] += focus
    rows=[];ready=0
    for row in material_rows.values():
        row['remaining'] = max(Decimal(0),row['quantity']-row['bought'])
        if row['price'] is not None:
            totals['materials_cost'] += row['quantity']*dec(row['price'])
            totals['remaining_budget'] += row['remaining']*dec(row['price'])*(1+dec(cfg['setup_fee_pct'])/100 if cfg['buy_mode']=='order' else 1)
            ready += 1
        for field in ('quantity','bought','remaining'): row[field] = value(row[field])
        rows.append(row)
    for name in ('no_focus','focus'):
        profits = [r['models'][name]['profit'] for r in line_rows]
        totals[name] = sum((dec(p) for p in profits),Decimal(0))-dec(cfg['transport']) if all(p is not None for p in profits) else None
    summary = {'materials_cost':value(totals['materials_cost']) if ready==len(rows) else None,
        'known_materials_cost':value(totals['materials_cost']),
        'remaining_budget':value(totals['remaining_budget']) if all(r['price'] is not None or not r['remaining'] for r in rows) else None,
        'ready_materials':ready,'total_materials':len(rows),
        'cash_profit':value(totals['cash_profit']-dec(cfg['transport'])) if not totals['incomplete_lines'] else None,
        'no_focus_profit':value(totals['no_focus']),'focus_profit':value(totals['focus']),
        'focus':value(totals['focus_spent']) if not totals['unknown_focus'] else None,
        'transport':cfg['transport']}
    if cfg['all_qualities']:
        for model in ('no_focus','focus'):
            lows=[r['overview']['models'][model]['profit_min'] for r in line_rows]
            highs=[r['overview']['models'][model]['profit_max'] for r in line_rows]
            summary[model+'_range']={'min':value(sum(map(dec,lows))-dec(cfg['transport'])) if all(p is not None for p in lows) else None,
                'max':value(sum(map(dec,highs))-dec(cfg['transport'])) if all(p is not None for p in highs) else None}
    return {'config':cfg,'lines':line_rows,'resources':rows,'summary':summary,
        'basis':'gross shopping; expected returns remain inventory; selected output quality is an assumption; observed history is not guaranteed demand'}


def inventory_presets(resources, name='Закупка крафта', *, include_owned=False, entries_per_code=10, max_stack=999):
    """Game clipboard schema v1, supplied by the user from an actual exported loadout.

    Chunking is a configurable convenience, not a claim about the game's live
    Marketplace limit. Game acceptance must still be checked in the client.
    """
    if type(include_owned) is not bool:
        raise ValueError('include_owned должен быть boolean')
    count, limit = number(entries_per_code,1,48), number(max_stack,1,999)
    if count!=int(count) or limit!=int(limit): raise ValueError('Лимиты набора должны быть целыми')
    count, limit = int(count), int(limit)
    title = str(name).strip()[:50] or 'Закупка крафта'
    entries=[];quantity=0
    for row in resources:
        amount = dec(row['quantity'] if include_owned else row['remaining'])
        if amount < 0 or amount!=int(amount): raise ValueError('Игровой набор требует целое неотрицательное количество')
        if not amount: continue
        if row.get('catalogue_missing'): raise ValueError('Для экспорта сначала загрузите каталог всех материалов')
        uid = row['id']
        if not isinstance(uid,str) or not re.fullmatch(r'[A-Za-z0-9_@-]{1,150}',uid): raise ValueError('Неверный игровой ID материала')
        per_stack = min(limit,int(number(row.get('max_stack',999),1,999)))
        amount=int(amount)
        if len(entries)+(amount+per_stack-1)//per_stack>5000:
            raise ValueError('Слишком большая партия для кодов комплектов. Уменьшите количество крафта')
        quantity+=amount
        while amount:
            stack=min(amount,per_stack)
            entries.append({'item':uid,'quality':1,'stack':stack});amount-=stack
    if not entries: raise ValueError('Все материалы отмечены купленными. Включите уже купленное для повторного набора')
    total=(len(entries)+count-1)//count
    presets=[]
    for index, offset in enumerate(range(0,len(entries),count),1):
        suffix=f' · {index}/{total}' if total>1 else ''
        obj={'version':1,'name':title[:50-len(suffix)]+suffix,'icon':6,'inventory':entries[offset:offset+count]}
        presets.append({'name':obj['name'],'entries':len(obj['inventory']),
                        'text':json.dumps(obj,ensure_ascii=False,separators=(',',':'))})
    return {'presets':presets,'quantity':quantity,'entries':len(entries),'schema_version':1}


def loadouts(store, body):
    computed=plan(store,body)
    return inventory_presets(computed['resources'],body.get('name','Закупка крафта'),
        include_owned=body.get('loadout_include_owned',False),
        entries_per_code=body.get('loadout_entries',10),max_stack=body.get('loadout_stack',999))


def crystal_set(store, body):
    tier, enchant = number(body.get('tier',4),1,8), number(body.get('enchantment',0),0,4)
    if tier!=int(tier) or enchant!=int(enchant): raise ValueError('Тир и зачарование должны быть целыми')
    tier, enchant = int(tier), int(enchant)
    families = crafting.search(store,'CRYSTAL',limit=100)['results']
    lines = []
    for family in families:
        if not re.fullmatch(r'(MAIN|2H)_.+_CRYSTAL',family['family']): continue
        item = next((v for v in family['variants'] if v['tier']==tier and v['enchantment']==enchant),None)
        if item: lines.append({'item_id':item['id'],'units':1,'variant':0,'output_quality':1})
    if not lines: raise ValueError('В каталоге нет кристального оружия выбранного тира и зачарования')
    return plan(store,{**body,'lines':lines})


def saved(store):
    with store.connect() as db:
        return {'batches':[{'id':r['id'],'name':r['name']} for r in db.execute('SELECT id,name FROM craft_batches ORDER BY updated_at DESC LIMIT 200')]}


def save(store, body):
    computed = plan(store,body)
    uid, name, now = str(body.get('id') or uuid.uuid4().hex), str(body.get('name') or 'Партия крафта').strip(), utcnow()
    if not re.fullmatch(r'[a-f0-9]{32}',uid) or not 1<=len(name)<=150: raise ValueError('Некорректное имя или ID партии')
    with store.connect() as db:
        db.execute('''INSERT INTO craft_batches VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,config=excluded.config,updated_at=excluded.updated_at''',
            (uid,name,json.dumps(computed['config']),now,now))
    return {'id':uid,'name':name,**computed}


def load(store, uid):
    with store.connect() as db:
        row = db.execute('SELECT * FROM craft_batches WHERE id=?',(uid,)).fetchone()
    if row is None: raise ValueError('Партия не найдена')
    return {'id':row['id'],'name':row['name'],**plan(store,json.loads(row['config']))}


def refresh_computed(client, computed_batches, progress=None):
    from .transport import batches
    cfg=computed_batches[0]['config'];total={'prices':0,'history':0}
    groups=defaultdict(set);history_groups=defaultdict(set)
    for computed in computed_batches:
        for r in computed['resources']: groups[(cfg['city'],1)].add(r['id'])
        for line in computed['config']['lines']:
            qs=output_qualities(line['item_id']) if computed['config']['all_qualities'] else (line['output_quality'],)
            for q in qs:
                groups[(cfg['sale_city'],q)].add(line['item_id'])
                history_groups[q].add(line['item_id'])
    tasks=[]
    for (city,q),ids in groups.items():
        for url in batches(cfg['server'],'prices',sorted(ids),[city],[q]):
            tasks.append(('prices',url,0))
    end = int(utcnow()//3600)*3600
    date = lambda t: datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m-%d')
    for q,ids in history_groups.items():
        for scale in (1,6):
            for url in batches(cfg['server'],'history',sorted(ids),[cfg['sale_city']],[q],
                {'time-scale':scale,'date':date(end-7*86400),'end_date':date(end+86400)}):
                tasks.append(('history',url,scale*3600))
    for index,(kind,url,seconds) in enumerate(tasks):
        if progress:progress({'done':index,'total':len(tasks),'label':'Получаем цены' if kind=='prices' else 'Получаем продажи по всем рамкам'})
        payload=client.get(url,ttl=3600 if kind=='history' else 900)
        total[kind] += ingestion.history(client.store,payload,cfg['server'],seconds=seconds) if kind=='history' else ingestion.prices(client.store,payload,cfg['server'])
    if progress:progress({'done':len(tasks),'total':len(tasks),'label':'Данные загружены'})
    return total


def refresh(client, body, progress=None):
    return refresh_computed(client,[plan(client.store,body)],progress)
