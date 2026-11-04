"""Find craft candidates from the catalogue and observed prices, without speculative quality averages."""
from . import craft_batch
from .domain import number, utcnow

CATEGORIES={
    'weapons':('MAIN','2H','OFF'),
    'armor':('HEAD','ARMOR','SHOES'),
    'accessories':('CAPE','BAG'),
    'equipment':('MAIN','2H','OFF','HEAD','ARMOR','SHOES','CAPE','BAG'),
    'crystal':('MAIN','2H','OFF'),
    'consumables':('MEAL','POTION'),
}


def config(body):
    category=body.get('category','equipment')
    if category not in (*CATEGORIES,'all'):raise ValueError('Неизвестная категория крафта')
    tier=body.get('tier',4);enchantment=body.get('enchantment',0)
    parsed={}
    for field,v,low,high in [('tier',tier,1,8),('enchantment',enchantment,0,4)]:
        if v in ('all','',None):parsed[field]=None
        else:
            n=number(v,low,high)
            if n!=int(n):raise ValueError('Тир и зачарование должны быть целыми')
            parsed[field]=int(n)
    state=body.get('show','recommended');sort=body.get('sort','profit_desc')
    if state not in ('all','recommended','profit','loss','mixed','missing'):raise ValueError('Неизвестный фильтр результата')
    if sort not in ('profit_desc','profit_asc','sales_desc','cost_asc'):raise ValueError('Неизвестная сортировка')
    settings={k:body[k] for k in ('server','city','sale_city','scope','max_age_hours','station_per_operation','liquidity_share_pct') if k in body}
    economics=craft_batch.config({**settings,'lines':[{'item_id':'selection'}],'all_qualities':True,
        'no_focus_return':body.get('no_focus_return') if body.get('no_focus_return') not in (None,'') else 0,
        'focus_return':None,'sales_tax_pct':8,'setup_fee_pct':2.5,'buy_mode':'instant','sell_mode':'order'})
    return {'economics':economics,'category':category,**parsed,'search':str(body.get('search',''))[:150],
        'show':state,'sort':sort,'min_sales':number(body.get('min_sales',10),0,1e12),
        'min_profit':number(body.get('min_profit',0),0,1e12)}


def pool(store,cfg):
    clauses=['1=1'];params=[]
    for field in ('tier','enchantment'):
        if cfg[field] is not None:clauses.append(f'i.{field}=?');params.append(cfg[field])
    if cfg['category']!='all':
        clauses.append('('+' OR '.join('i.id GLOB ?' for _ in CATEGORIES[cfg['category']])+')')
        params.extend(f'T[1-8]_{prefix}_*' for prefix in CATEGORIES[cfg['category']])
    if cfg['category']=='crystal':clauses.append("i.id GLOB '*_CRYSTAL*'")
    if cfg['search']:
        clauses.append("instr(replace(i.search,' ',''),?)>0");params.append(''.join(cfg['search'].casefold().split()))
    where=' AND '.join(clauses)
    with store.connect() as db:
        rows=[dict(r) for r in db.execute(f'''SELECT i.id,r.variant
            FROM items i JOIN recipes r ON r.item_id=i.id WHERE {where}
            ORDER BY i.name_ru,i.id,r.variant''',params)]
    return rows,len(rows)


def computed(store,cfg,candidates,now,all_qualities=True):
    valid=[];errors=[]
    # Internal batches keep the shopping planner's payload small; every candidate is evaluated.
    for offset in range(0,len(candidates),100):
        lines=[{'item_id':r['id'],'variant':r['variant'],'units':1,'output_quality':1,'line_id':f'idea_{offset+i}'} for i,r in enumerate(candidates[offset:offset+100])]
        body={**cfg['economics'],'lines':lines,'all_qualities':all_qualities}
        try:valid.append(craft_batch.plan(store,body,now))
        except (ValueError,KeyError,TypeError):
            # A malformed/unsupported recipe must not hide the other candidates.
            for line in lines:
                try:valid.append(craft_batch.plan(store,{**body,'lines':[line]},now))
                except (ValueError,KeyError,TypeError) as exc:errors.append({'id':line['item_id'],'variant':line['variant'],'error':str(exc)})
    return valid,errors


def analyze(store,body,now=None):
    cfg=config(body);now=utcnow() if now is None else now
    with store.read_snapshot() as snapshot:
        candidates,total=pool(snapshot,cfg)
        batches,errors=computed(snapshot,cfg,candidates,now)
    best={}
    for batch in batches:
        for line in batch['lines']:
            overview=line['overview'];model=overview['models']['no_focus']
            profit=model['rank_profit'];sales=overview['known_sales']
            item=line['item'];cost=line['gross_materials_cost']
            limit=int(sales*cfg['economics']['liquidity_share_pct']/100) if sales is not None else None
            row={'item':item,'variant':line['config']['variant'],'produced':line['produced'],
                'materials_per_unit':cost/line['produced'] if cost is not None else None,
                'overview':overview,'qualities':line['quality_summary'],'profit':profit,
                'known_sales':sales,'missing_prices':line['missing_prices'],
                'recommended':profit is not None and profit>cfg['min_profit'] and sales is not None and sales>0
                    and sales>=cfg['min_sales'] and limit>=line['produced'],
                'suggested_limit':limit}
            score=(profit is not None,profit if profit is not None else float('-inf'),-(row['materials_per_unit'] or 0))
            previous=best.get(item['id'])
            if previous is None or score>previous[0]:best[item['id']]=(score,row)
    rows=[r for _,r in best.values()]
    counts={'recommended':sum(r['recommended'] for r in rows),'profit':sum(r['profit'] is not None and r['profit']>0 for r in rows),
        'loss':sum(r['profit'] is not None and r['profit']<0 for r in rows),'missing':sum(r['profit'] is None or r['known_sales'] is None for r in rows)}
    def visible(row):
        p=row['profit'];m=row['overview']['models']['no_focus'];state=cfg['show']
        return (state=='all' or state=='recommended' and row['recommended'] or state=='profit' and p is not None and p>0
            or state=='loss' and p is not None and p<0 or state=='mixed' and m['unit_profit_min'] is not None and m['unit_profit_min']<=0<m['unit_profit_max']
            or state=='missing' and (p is None or row['known_sales'] is None))
    rows=[r for r in rows if visible(r)]
    field='known_sales' if cfg['sort']=='sales_desc' else 'materials_per_unit' if cfg['sort']=='cost_asc' else 'profit'
    descending=cfg['sort'] in ('profit_desc','sales_desc')
    rows.sort(key=lambda r:(r[field] is None,(-r[field] if descending else r[field]) if r[field] is not None else 0,r['item']['id']))
    return {'rows':rows,'total':len(rows),
        'matched_recipes':total,'evaluated_recipes':len(candidates),'evaluated_items':len(best),
        'counts':counts,'unsupported_recipes':errors,
        'config':{k:v for k,v in cfg.items() if k!='economics'},'economics':cfg['economics']}


def refresh(client,body,progress=None):
    cfg=config(body);now=utcnow()
    if progress:progress({'done':0,'total':1,'label':'Собираем материалы выбранных рецептов'})
    with client.store.read_snapshot() as snapshot:
        candidates,total=pool(snapshot,cfg)
        if not candidates:raise ValueError('В каталоге нет рецептов для выбранных фильтров')
        batches,errors=computed(snapshot,cfg,candidates,now,all_qualities=False)
    if not batches:raise ValueError('Не удалось прочитать рецепты выбранной категории')
    for batch in batches:batch['config']['all_qualities']=True
    result=craft_batch.refresh_computed(client,batches,progress)
    return {**result,'candidates':len(candidates),'matched_recipes':total,'unsupported':len(errors)}


def revision(store):
    with store.connect() as db:
        return {'event':db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0],
                'catalog':db.execute('SELECT COALESCE(MAX(catalog_at),0) FROM items').fetchone()[0]}
