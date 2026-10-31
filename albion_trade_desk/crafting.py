"""Recipe-driven scan packs and gross material budget. No game automation."""
from collections import defaultdict
from decimal import Decimal, ROUND_CEILING
import json
import re
import uuid
from .catalog import ingredient_id
from .domain import region, location, number, utcnow, MARKETS
from .analytics import SCOPES


def family(uid):
    return re.sub(r'^T[0-9]+_', '', uid).split('@')[0]


def item_info(row, uid):
    return {key: row[key] for key in ('id','name_ru','name_en','tier','enchantment')} if row else {
        'id':uid, 'name_ru':'Название ещё не загружено', 'name_en':uid,
        'tier':int(re.match(r'T([0-9]+)_',uid)[1]) if re.match(r'T([0-9]+)_',uid) else 0,
        'enchantment':int(uid.split('@')[-1]) if re.search(r'@[0-9]+$',uid) else 0}


def variants(db, key):
    # Full family options must not be limited to the tier matched by the search.
    result = []
    for row in db.execute("""SELECT i.id,i.name_ru,i.name_en,i.tier,i.enchantment FROM items i
        WHERE instr(i.id,?)>0 AND EXISTS(SELECT 1 FROM recipes r WHERE r.item_id=i.id)
        ORDER BY i.tier,i.enchantment,i.id""", (key,)):
        if family(row['id']) == key:
            result.append(dict(row))
    return result


def search(store, text='', limit=20):
    compact = ''.join(str(text).casefold().split())[:150]
    with store.connect() as db:
        rows = db.execute("""SELECT i.id FROM items i WHERE instr(replace(i.search,' ',''),?)>0
            AND EXISTS(SELECT 1 FROM recipes r WHERE r.item_id=i.id)
            ORDER BY i.tier,i.enchantment,i.name_ru LIMIT 1000""", (compact,)).fetchall()
        keys = list(dict.fromkeys(family(row['id']) for row in rows))[:limit]
        result = []
        for key in keys:
            options = variants(db, key)
            if options:
                preferred = next((v for v in options if v['tier']==4 and v['enchantment']==0), options[0])
                result.append({'family':key, **preferred, 'variants':options})
        return {'results':result}


def config(body):
    uid = body['item_id']
    if not isinstance(uid,str) or not 1 <= len(uid) <= 150:
        raise ValueError('Выберите предмет из списка')
    units = number(body.get('units',1),1,1000000)
    variant = number(body.get('variant',0),0,1000)
    output_quality = number(body.get('output_quality',1),1,5)
    if any(x != int(x) for x in (units,variant,output_quality)):
        raise ValueError('Количество, вариант и качество должны быть целыми')
    city, sale = location(body.get('city','1002')), location(body.get('sale_city',body.get('city','1002')))
    if city not in MARKETS or city == '3003' or sale not in MARKETS:
        raise ValueError('Выберите обычный город для ресурсов. Black Market можно выбрать для готового предмета')
    scope = body.get('scope','all')
    if scope != 'all' and scope not in SCOPES:
        raise ValueError('Неизвестный источник цен')
    return {'item_id':uid,'units':int(units),'variant':int(variant),'output_quality':int(output_quality),
            'city':city,'sale_city':sale,'server':region(body.get('server','east')),
            'scope':scope,'max_age_hours':number(body.get('max_age_hours',24),0,8760)}


def quote(db, cfg, uid, city, q, kind, now):
    aliases = [uid]
    if re.search(r'_LEVEL([1-4])@\1$',uid):
        raw = uid.split('@')[0]
        if not db.execute('SELECT 1 FROM items WHERE id=?',(raw,)).fetchone():
            aliases.append(raw)  # Legacy local observations before the ID fix, not enchantment .0.
    rows = db.execute('''SELECT * FROM quotes WHERE server=? AND location=? AND quality=? AND kind=?
        AND item_id IN ('''+','.join('?' for _ in aliases)+') ORDER BY observed_at DESC,received_at DESC',
        [cfg['server'],city,q,kind,*aliases]).fetchall()
    sources = SCOPES.get(cfg['scope'])
    candidates = []
    for row in rows:
        if sources and row['source'] not in sources:
            continue
        age = max(0,now-row['observed_at'])
        live = True
        if row['source'] in ('data-client','private-client','aodp-nats'):
            live = db.execute('''SELECT 1 FROM orders WHERE server=? AND location=? AND quality=?
                AND item_id=? AND source=? AND side=? AND price=? AND amount>0 AND expires>? LIMIT 1''',
                (cfg['server'],city,q,row['item_id'],row['source'],
                 'offer' if kind=='sell_price_min' else 'request',row['price'],now)).fetchone() is not None
        candidates.append({**dict(row),'fresh':bool(live and age<=cfg['max_age_hours']*3600),'age_seconds':age})
    return next((row for row in candidates if row['fresh']), candidates[0] if candidates else None)


def n(value):
    return int(value) if value == int(value) else float(value)


def plan(store, body, now=None):
    cfg, now = config(body), utcnow() if now is None else now
    with store.connect() as db:
        item = db.execute('SELECT * FROM items WHERE id=?',(cfg['item_id'],)).fetchone()
        if item is None:
            raise ValueError('Предмета пока нет в каталоге. Обновите список предметов')
        recipes = db.execute('SELECT * FROM recipes WHERE item_id=? ORDER BY variant',(cfg['item_id'],)).fetchall()
        recipe = next((r for r in recipes if r['variant']==cfg['variant']),None)
        if not recipe:
            raise ValueError('Этот вариант рецепта недоступен. Выберите другой предмет или рецепт')
        output = Decimal(str(recipe['output']))
        if not output.is_finite() or output<=0:
            raise ValueError('Некорректный выход рецепта')
        operations = int((Decimal(cfg['units'])/output).to_integral_value(rounding=ROUND_CEILING))
        resources = defaultdict(lambda: {'count':Decimal(0),'returnable_count':Decimal(0)})
        for r in json.loads(recipe['resources']):
            uid = ingredient_id(db,r['item_id'])
            count = Decimal(str(number(r['count'],0))) * operations
            if not count:
                continue
            resources[uid]['count'] += count
            if r.get('returnable',False):
                resources[uid]['returnable_count'] += count
        if not resources:
            raise ValueError('В рецепте нет поддерживаемых материалов')
        rows, known, ready = [], Decimal(0), 0
        for uid, counts in resources.items():
            info = db.execute('SELECT * FROM items WHERE id=?',(uid,)).fetchone()
            observation = quote(db,cfg,uid,cfg['city'],1,'sell_price_min',now)
            fresh = bool(observation and observation['fresh'])
            subtotal = Decimal(str(observation['price']))*counts['count'] if fresh else None
            if subtotal is not None:
                known += subtotal; ready += 1
            rows.append({**item_info(info,uid),'quantity':n(counts['count']), 'quality':1,
                         'location':cfg['city'],'quote':observation,
                         'status':'ready' if fresh else 'stale' if observation else 'missing',
                         'subtotal':n(subtotal) if subtotal is not None else None,
                         'returnable_quantity':n(counts['returnable_count']),
                         'catalogue_missing':info is None})
        produced = output*operations
        fixed = Decimal(str(recipe['silver']))*operations
        complete = ready==len(rows)
        output_kind = 'buy_price_max' if cfg['sale_city']=='3003' else 'sell_price_min'
        output_quote = quote(db,cfg,cfg['item_id'],cfg['sale_city'],cfg['output_quality'],output_kind,now)
        return {'config':cfg,'item':item_info(item,cfg['item_id']),'variants':variants(db,family(cfg['item_id'])),
                'recipe_variants':[{'variant':r['variant'],'output':r['output']} for r in recipes],
                'operations':operations,'produced':n(produced),'overproduction':n(produced-Decimal(cfg['units'])),
                'resources':rows,'ready_count':ready,'resource_count':len(rows),
                'materials_cost':n(known) if complete else None,'known_materials_cost':n(known),
                'recipe_silver':n(fixed),'base_batch_cost':n(known+fixed) if complete else None,
                'base_unit_cost':n((known+fixed)/produced) if complete else None,
                'base_focus_per_operation':recipe['focus'],
                'output_market':{'quote':output_quote,'kind':output_kind,'quality':cfg['output_quality'],'location':cfg['sale_city']},
                'catalogue_at':item['catalog_at'],
                'cost_basis':'gross inputs + recipe silver; no returns, station, transport or sales fees; depth unknown'}


def save(store, body):
    computed = plan(store,body)
    cfg, now = computed['config'],utcnow()
    uid = str(body.get('id') or uuid.uuid4().hex)
    name = str(body.get('name') or f"{computed['item']['name_ru']} · {computed['item']['tier']}.{computed['item']['enchantment']} · {cfg['units']} шт.").strip()
    if not name or len(name)>150 or not re.fullmatch(r'[a-f0-9]{32}',uid):
        raise ValueError('Некорректное название или ID набора')
    with store.connect() as db:
        db.execute('''INSERT INTO craft_packs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,config=excluded.config,updated_at=excluded.updated_at''',
            (uid,name,json.dumps(cfg),now,now))
    return {'id':uid,'name':name,**computed}


def saved(store):
    with store.connect() as db:
        return {'packs':[{'id':r['id'],'name':r['name'],'config':json.loads(r['config'])} for r in
                         db.execute('SELECT * FROM craft_packs ORDER BY updated_at DESC LIMIT 200')]}


def load(store, uid):
    with store.connect() as db:
        row=db.execute('SELECT * FROM craft_packs WHERE id=?',(uid,)).fetchone()
    if not row:
        raise ValueError('Набор не найден')
    return {'id':row['id'],'name':row['name'],**plan(store,json.loads(row['config']))}


def refresh(client, body):
    from .transport import refresh_market
    computed=plan(client.store,body)
    if computed['config']['scope']=='private':
        raise ValueError('Выбраны только свои наблюдения. Общие цены загружаются отдельно')
    groups=defaultdict(list)
    for r in computed['resources']:
        groups[(r['location'],1)].append(r['id'])
    cfg=computed['config']
    groups[(cfg['sale_city'],cfg['output_quality'])].append(cfg['item_id'])
    total={'prices':0,'history':0}
    for (city,q),ids in groups.items():
        ids=list(dict.fromkeys(ids))
        for offset in range(0,len(ids),100):
            counts=refresh_market(client,ids[offset:offset+100],cfg['server'],[city],[q])
            for key in total:
                total[key]+=counts[key]
    return total
