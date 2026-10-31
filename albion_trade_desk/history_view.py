"""Observed history for one exact quality, with non-overlapping bins and explicit gaps."""
from collections import defaultdict
from datetime import datetime, timezone
from .domain import region, location, quality, utcnow, number, timestamp
from .analytics import SCOPES, unique_hours


def bounds(query, now=None):
    now=utcnow() if now is None else now
    end=int(timestamp(query['end'])//3600)*3600 if query.get('end') else int(now//3600)*3600
    hours=number(query.get('hours',24),1,2160)
    start=int(timestamp(query['start'])//3600)*3600 if query.get('start') else end-int(hours)*3600
    if start>=end or end-start>2160*3600 or end>int(now//3600)*3600:
        raise ValueError('Выберите завершённый период от 1 часа до 90 дней')
    return start,end


def series(store, query, now=None):
    start,end=bounds(query,now)
    server,city,q=region(query.get('server','east')),location(query.get('city','1002')),quality(query.get('quality',1))
    scope=query.get('scope','all')
    if scope!='all' and scope not in SCOPES:raise ValueError('Неизвестный источник')
    step=3600 if end-start<=48*3600 else 21600 if end-start<=7*86400 else 86400
    with store.connect() as db:
        points=[dict(p) for p in db.execute('''SELECT * FROM history WHERE server=? AND location=?
            AND item_id=? AND quality=? AND start>=? AND start<?''',(server,city,query['id'],q,start,end))]
    if SCOPES.get(scope):points=[p for p in points if p['source'] in SCOPES[scope]]
    points=unique_hours(points)
    covered=set();accepted=[]
    for p in sorted(points,key=lambda p:(p['seconds'],-p['received_at'])):
        if p['start']+p['seconds']>end or p['seconds']>step:continue
        slots=set(range(int(p['start']),int(p['start']+p['seconds']),3600))
        if slots&covered:continue
        covered|=slots;accepted.append(p)
    grouped=defaultdict(list)
    for p in accepted:grouped[int(p['start']//step)*step].append(p)
    rows=[]
    for at in range(int(start//step)*step,end,step):
        left,right=max(start,at),min(end,at+step);ps=grouped[at]
        quantity=sum(p['quantity'] for p in ps);known=sum(p['seconds']//3600 for p in ps)
        expected=(right-left)//3600
        rows.append({'start':left,'end':right,'known_hours':known,'expected_hours':expected,
            'quantity':quantity if known else None,'complete':known==expected,
            'average':sum(p['average']*p['quantity'] for p in ps)/quantity if quantity else None,
            'sources':sorted({p['source'] for p in ps})})
    quantity=sum(p['quantity'] for p in accepted);known=len(covered);expected=(end-start)//3600
    return {'server':server,'location':city,'quality':q,'scope':scope,'start':start,'end':end,
        'step_hours':step//3600,'points':rows,'known_hours':known,'expected_hours':expected,
        'volume':quantity if known==expected else None,'known_quantity':quantity if known else None,
        'vwap':sum(p['average']*p['quantity'] for p in accepted)/quantity if quantity else None,
        'window_model':'completed UTC hours; start-labelled, live boundary validation pending'}


def refresh(client, query):
    from .transport import batches
    from .ingestion import history
    if query.get('scope')=='private':raise ValueError('Свои наблюдения поступают из локального клиента')
    start,end=bounds(query)
    day=lambda t:datetime.fromtimestamp(t,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    count=0
    for url in batches(region(query.get('server','east')),'history',[query['id']],
        [location(query.get('city','1002'))],[quality(query.get('quality',1))],
        {'time-scale':1,'date':day(start),'end_date':day(end)}):
        count+=history(client.store,client.get(url,ttl=3600),query.get('server','east'))
    return {'prices':0,'history':count}
