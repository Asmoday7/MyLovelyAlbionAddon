"""The user's cloth spreadsheet, with explicit scenario inputs and Decimal money."""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import io
import json
import xml.etree.ElementTree as ET
from .domain import number

TEMPLATES=Path(__file__).parent/'templates'
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
D=lambda x:Decimal(str(x))


def defaults():
    return json.loads((TEMPLATES/'cloth_defaults.json').read_text(encoding='utf-8'))


def config(body):
    base=defaults();out={}
    for key,low,high in [('batch',1,1000000),('return_rate',0,99.9),('tax_pct',0,99),('station',0,1e12),
        ('t3_price',0,1e12),('coefficient',0,100000),('steps',0,30),('secondary_initial',0,1000000),('secondary_rate',0,99.9)]:
        out[key]=number(body.get(key,base[key]),low,high)
    for key in ('batch','steps'):
        if out[key]!=int(out[key]):raise ValueError('Партия и число шагов должны быть целыми')
        out[key]=int(out[key])
    out['mode']=body.get('mode',base['mode'])
    out['rounding']=body.get('rounding',base['rounding'])
    if out['rounding'] not in ('integer','continuous'):raise ValueError('Неизвестное округление ресурсов')
    if out['mode'] not in ('finite','percent','coefficient'):raise ValueError('Неизвестный способ расчёта возврата')
    out['levels']={str(t):number(body.get('levels',base['levels'])[str(t)],0,100) for t in range(4,9)}
    source=body.get('rows',base['rows'])
    if not isinstance(source,list) or len(source)!=25:raise ValueError('Нужны 25 вариантов ткани T4–T8, .0–.4')
    indexed={}
    for r in source:
        key=(int(r['tier']),int(r['enchantment']))
        if key not in [(t,e) for t in range(4,9) for e in range(5)] or key in indexed:raise ValueError('Повтор или неверный тир ткани')
        indexed[key]={'tier':key[0],'enchantment':key[1],**{k:number(r[k],0,1e12) for k in ('fiber','cloth_buy','sale','legacy_focus')}}
    out['rows']=[indexed[key] for key in sorted(indexed)]
    return out


def loop(initial,rate,repeats,focus_per_unit,fiber_count=5,rounding='integer',maxrows=None):
    ratio=D(rate)/100;fiber=D(initial)*fiber_count;cloth=D(initial)
    total=Decimal(0);focus=Decimal(0);rows=[]
    floor=lambda v:v.to_integral_value(rounding='ROUND_FLOOR')
    for i in range(maxrows if maxrows is not None else repeats+1):
        capacity=min(fiber/fiber_count,cloth)
        amount=(floor(capacity) if rounding=='integer' else capacity) if i<=repeats else Decimal(0)
        returned_fiber=amount*fiber_count*ratio;returned_cloth=amount*ratio
        if rounding=='integer':returned_fiber,returned_cloth=floor(returned_fiber),floor(returned_cloth)
        input_fiber,input_cloth=fiber,cloth
        fiber=fiber-amount*fiber_count+returned_fiber;cloth=cloth-amount+returned_cloth
        capacity=min(fiber/fiber_count,cloth)
        available=floor(capacity) if rounding=='integer' else capacity
        total+=amount;used=amount*focus_per_unit;focus+=used
        rows.append({'step':i+1,'input':float(amount),'returned':float(available),'produced_total':float(total),'focus':float(used),
          'input_fiber':float(input_fiber),'input_cloth':float(input_cloth),'returned_fiber':float(returned_fiber),
          'returned_cloth':float(returned_cloth),'stock_fiber':float(fiber),'stock_cloth':float(cloth)})
    return {'rows':rows,'produced':float(total),'remaining':float(available),'focus':float(focus)}


def calculate(body):
    cfg=config(body);batch=D(cfg['batch']);rate=D(cfg['return_rate'])/100
    continuous=batch*(Decimal(1)+sum(rate**i for i in range(1,cfg['steps']+1)))
    global_fce=30*sum(cfg['levels'].values());by={(r['tier'],r['enchantment']):r for r in cfg['rows']};rows=[]
    for r in cfg['rows']:
        t,e=r['tier'],r['enchantment'];factor=min(t-2,5)
        previous=D(cfg['t3_price']) if t==4 else D(by[(t-1,e)]['cloth_buy'])
        cost=D(r['fiber'])*factor+previous;initial=cost*batch
        fce=global_fce+250*cfg['levels'][str(t)]
        focus=int(D(10*1.75**(t+e-1)*float(batch)/2**(fce/10000)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        scenario=loop(cfg['batch'],cfg['return_rate'],cfg['steps'],D(focus)/batch,factor,cfg['rounding'])
        output=batch/(1-rate) if cfg['mode']=='percent' else batch*(1+D(cfg['coefficient'])/100) if cfg['mode']=='coefficient' else D(scenario['produced'])
        total_focus=D(focus)*output/batch
        revenue=output*D(r['sale'])*(1-D(cfg['tax_pct'])/100)
        station=output*D(cfg['station']);profit=revenue-initial-station
        legacy_profit=D(r['sale'])*211-cost*100
        rows.append({**r,'fiber_count':factor,'previous_price':float(previous),'cost_per_operation':float(cost),
            'initial_cost':float(initial),'expected_output':float(output),'focus_first_batch':focus,'fce':fce,
            'focus_total':float(total_focus),'revenue':float(revenue),'station_cost':float(station),
            'profit':float(profit),'profit_per_focus':float(profit/total_focus) if total_focus else None,
            'legacy_profit':float(legacy_profit),'legacy_profit_per_focus':float(legacy_profit/D(r['legacy_focus'])) if r['legacy_focus'] else None})
    selected=next(r for r in rows if r['tier']==8 and r['enchantment']==2)
    unit=D(selected['focus_first_batch'])/batch
    return {'config':cfg,'rows':rows,'global_fce':global_fce,'expected_output':rows[0]['expected_output'],
        'additional_output':rows[0]['expected_output']-float(batch),'continuous_output':float(continuous),'main_loop':loop(cfg['batch'],cfg['return_rate'],cfg['steps'],unit,5,cfg['rounding']),
        'secondary_loop':loop(cfg['secondary_initial'],cfg['secondary_rate'],cfg['steps'],unit,5,cfg['rounding']),
        'price_source':'manual values imported from the uploaded workbook; observation dates unknown',
        'model':'finite reuse of both ingredients; integer mode floors individual returned materials as a scenario, not game rounding; original Excel focus approximation'}


def load(store):
    with store.connect() as db:row=db.execute("SELECT value FROM user_settings WHERE key='cloth'").fetchone()
    return calculate(json.loads(row['value']) if row else {})


def save(store,body):
    result=calculate(body)
    with store.connect() as db:db.execute("INSERT OR REPLACE INTO user_settings VALUES('cloth',?)",(json.dumps(result['config']),))
    return result


def workbook(body):
    data=calculate(body);cfg=data['config'];batch=cfg['batch']
    params={'B2':batch,'B3':cfg['return_rate'],'B4':cfg['tax_pct'],'B5':cfg['station'],'B6':cfg['t3_price'],
        'B7':cfg['coefficient'],'B8':cfg['mode'],'B9':cfg['steps'],'B10':cfg['secondary_initial'],'B11':cfg['secondary_rate'],'B12':cfg['rounding'],
        'E7':data['global_fce'],**{f'E{i+2}':cfg['levels'][str(t)] for i,t in enumerate(range(4,9))}}
    cells={}
    for i,r in enumerate(data['rows'],7):
        mapping={'A':r['tier'],'B':r['enchantment'],'C':r['fiber_count'],'D':r['fiber'],'E':r['cloth_buy'],
          'F':r['sale'],'G':r['previous_price'],'H':r['cost_per_operation'],'I':r['initial_cost'],'J':r['expected_output'],
          'K':r['focus_first_batch'],'L':r['revenue'],'M':r['station_cost'],'N':r['profit'],'O':r['profit_per_focus'],
          'P':r['legacy_focus'],'Q':r['legacy_profit'],'R':r['legacy_profit_per_focus']}
        cells.update({f'{col}{i}':value for col,value in mapping.items()})
    loops={};scenarios={}
    unit=D(data['rows'][22]['focus_first_batch'])/D(batch)
    for index,r in enumerate(data['rows']+[None]):
        value=loop(cfg['batch'] if r else cfg['secondary_initial'],cfg['return_rate'] if r else cfg['secondary_rate'],
            cfg['steps'],D(r['focus_first_batch'])/D(batch) if r else unit,r['fiber_count'] if r else 5,cfg['rounding'],31)
        for i,point in enumerate(value['rows']):
            at=3+index*33+i
            mapping={'B':i,'C':point['input_fiber'],'D':point['input_cloth'],'E':point['input'],
              'F':point['returned_fiber'],'G':point['returned_cloth'],'H':point['stock_fiber'],'I':point['stock_cloth'],
              'J':point['produced_total'],'K':point['focus']}
            scenarios.update({f'{col}{at}':val for col,val in mapping.items()})
        if index in (22,25):
            start=5 if index==22 else 41
            for i,point in enumerate(value['rows']):
                at=start+i
                loops.update({f'A{at}':i+1,f'B{at}':point['input'],f'C{at}':point['returned'],f'D{at}':point['produced_total'],f'E{at}':point['focus']})
            loops[f'E{start+31}']=value['focus']
    all_cells={'xl/worksheets/sheet1.xml':params,'xl/worksheets/sheet2.xml':cells,
        'xl/worksheets/sheet3.xml':loops,'xl/worksheets/sheet5.xml':scenarios}
    stream=io.BytesIO()
    with ZipFile(TEMPLATES/'cloth_calculator.xlsx') as src,ZipFile(stream,'w',ZIP_DEFLATED) as dst:
        for member in src.infolist():
            raw=src.read(member.filename)
            if member.filename in all_cells:
                root=ET.fromstring(raw)
                for cell in root.iter('{'+NS+'}c'):
                    if cell.get('r') not in all_cells[member.filename]:continue
                    value=all_cells[member.filename][cell.get('r')]
                    for child in list(cell):
                        if child.tag in ('{'+NS+'}v','{'+NS+'}is'):cell.remove(child)
                    cell.attrib.pop('t',None)
                    if value is None:continue
                    if isinstance(value,str):
                        cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,'{'+NS+'}is'),'{'+NS+'}t').text=value
                    else:ET.SubElement(cell,'{'+NS+'}v').text=str(value)
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            dst.writestr(member,raw)
    return stream.getvalue()
