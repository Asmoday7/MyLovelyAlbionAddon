import {qualitySummary,profitRange,salesText,signed} from './craft_summary.js';
export function createCraftBatch({api,el,fmt,notice,showError,job,copy,context,applyContext}) {
  const $=id=>document.getElementById(id);
  const storageKey='albion-craft-batch-v1';
  const s={cfg:{lines:[],materials:{},buy_mode:'instant',sell_mode:'order',sales_tax_pct:8,setup_fee_pct:2.5,
    station_per_operation:0,transport:0,liquidity_share_pct:10,no_focus_return:0,focus_return:null,all_qualities:true},
    data:null,id:null,key:null,sequence:0,initialized:false,presets:[],presetIndex:0,publicEnabled:false,downloading:false};
  const fields={'batch-no-focus':'no_focus_return','batch-focus':'focus_return','batch-buy-mode':'buy_mode',
    'batch-sell-mode':'sell_mode','batch-tax':'sales_tax_pct','batch-setup':'setup_fee_pct','batch-station':'station_per_operation',
    'batch-transport':'transport','batch-share':'liquidity_share_pct'};
  const on=(id,fn)=>$(id).addEventListener('click',async()=>{try{await fn();}catch(e){showError(e);$('batch-feedback').textContent=e.detail||e.message;}});
  function persist(){localStorage.setItem(storageKey,JSON.stringify({config:s.cfg,id:s.id,name:$('batch-name').value,key:s.key}));}
  function invalidateCodes(){s.presets=[];$('batch-loadout-result').hidden=true;}
  function codeSignature(){return JSON.stringify([$('batch-name').value,s.data?.resources.map(r=>[r.id,r.quantity,r.remaining,r.max_stack,r.catalogue_missing])]);}
  function drawCode(){
    const preset=s.presets[s.presetIndex];if(!preset)return;
    $('batch-loadout-result').hidden=false;$('batch-loadout-code').value=preset.text;
    $('batch-loadout-counter').textContent=`Код ${s.presetIndex+1} из ${s.presets.length} · ${preset.name} · строк ${preset.entries}`;
    $('batch-loadout-next').disabled=s.presetIndex+1>=s.presets.length;
  }
  function name(r){return $('batch-language').value==='ru'?r.name_ru:r.name_en;}
  function queue(){return s.data?.resources.filter(r=>r.remaining>0)||[];}
  function active(){const rows=queue();return rows.find(r=>r.key===s.key)||rows[0];}
  function input(value,change,label,placeholder=''){
    const node=el('input');node.type='number';node.min='0';node.step='any';node.value=value??'';node.placeholder=placeholder;node.setAttribute('aria-label',label);
    node.onchange=async()=>{try{await change(node.value);}catch(e){showError(e);$('batch-feedback').textContent=e.detail||e.message;}};return node;
  }
  function money(value){return value==null?'Нужны данные':fmt(value)+' серебра';}
  function drawQueue(){
    const row=active(),rows=queue();
    $('batch-queue-counter').textContent=row?`Материал ${rows.findIndex(r=>r.key===row.key)+1} из ${rows.length}`:'Все материалы отмечены купленными';
    $('batch-queue-name').textContent=row?name(row):'Закупка завершена';
    $('batch-queue-variant').textContent=row?`Тир ${row.tier}.${row.enchantment} · обычное качество · ${row.name_ru}`:'Отметки закупки сохранены отдельно от сканирования цен.';
    $('batch-queue-quantity').textContent=row?`Докупить ${fmt(row.remaining)} шт.`:'';
    for(const id of ['batch-copy-name','batch-copy-quantity','batch-done','batch-next'])$(id).disabled=!row;
  }
  function validateUnits(value){if(!Number.isInteger(Number(value))||Number(value)<1||Number(value)>1000000)throw new Error('Количество готовых предметов: целое число от 1 до 1 000 000.');}
  async function editLine(id,field,v){
    if(field==='units')validateUnits(v);
    const row=s.cfg.lines.find(r=>r.line_id===id);row[field]=v===''?null:Number(v);persist();await refresh(true);
  }
  function drawLines(){
    const filter=$('batch-filter').value,sort=$('batch-sort').value;
    const rows=s.data.lines.filter(r=>{
      const m=r.overview.models.no_focus,a=m.unit_profit_min,b=m.unit_profit_max;
      return filter==='all'||filter==='profit'&&a>0||filter==='loss'&&a!=null&&a<0||filter==='mixed'&&a!=null&&a<=0&&b>0||filter==='missing'&&a==null;
    });
    if(sort!=='original')rows.sort((a,b)=>{
      const metric=r=>sort==='sales'?r.overview.known_sales:sort.startsWith('no_focus_unit')?r.overview.models.no_focus.rank_profit:r.overview.ordinary_price_known?r.overview.models.no_focus.profit_min:null;
      const x=metric(a),y=metric(b);return x==null?(y==null?0:1):y==null?-1:sort.endsWith('_asc')?x-y:y-x;
    });
    $('batch-lines').replaceChildren();
    for(const row of rows){
      const line=row.config,card=el('article',null,'craft-opportunity');card.dataset.lineId=line.line_id;
      const info=el('div',null,'opportunity-info');info.append(el('h3',`${row.item.name_ru} · ${row.item.tier}.${row.item.enchantment}`),el('small',row.item.name_en));
      const stats=el('div',null,'opportunity-stats');
      for(const [label,text] of [['Прибыль I–IV / шт.',profitRange(row.overview,fmt)],['Продано I–IV / 7 дн.',salesText(row.overview,fmt)]]){
        const stat=el('div');stat.append(el('small',label),el('strong',text,row.overview.models.no_focus.unit_profit_min<0?'loss':'gain'));stats.append(stat);
      }
      info.append(stats);
      const actions=el('div',null,'opportunity-actions'),remove=el('button','Убрать','quiet');
      remove.onclick=async()=>{s.cfg.lines=s.cfg.lines.filter(r=>r.line_id!==line.line_id);persist();await refresh(true);};
      actions.append(el('span','Готовых, шт.'),input(line.units,v=>editLine(line.line_id,'units',v),'Количество '+row.item.name_en),remove);info.append(actions);
      if(row.overproduction)info.append(el('small',`Получится ${fmt(row.produced)}, излишек ${fmt(row.overproduction)}`));
      if(row.overview.known_sales!=null){
        const cap=Math.floor(row.overview.known_sales*s.cfg.liquidity_share_pct/100);
        info.append(el('small',`Ориентир по известным продажам: до ${fmt(cap)} шт.`));
        if(row.produced>cap)info.append(el('small','Партия выше выбранной доли продаж.','loss'));
      }
      card.append(info,qualitySummary(row.quality_summary,{el,fmt}));$('batch-lines').append(card);
    }
    if(!rows.length)$('batch-lines').append(el('p','В партии нет предметов под выбранный фильтр.','empty-history'));
    drawAdvanced();
  }
  function drawAdvanced(){
    const open=new Set([...$('batch-line-settings').querySelectorAll('details[open]')].map(r=>r.dataset.lineId));$('batch-line-settings').replaceChildren();
    for(const row of s.data.lines){
      const line=row.config,details=el('details');details.dataset.lineId=line.line_id;details.open=open.has(line.line_id);details.append(el('summary',row.item.name_ru));
      const controls=el('div',null,'craft-controls');
      for(const [field,label,placeholder] of [['no_focus_return','Возврат без Focus, %','Общий % партии'],['focus_return','Возврат с Focus, %','Общий % партии'],
        ['station_per_operation','Станция / операция','Общая ставка партии'],['focus_per_operation','Focus / операция','Фактический расход'],['sale_price','Своя цена продажи / шт.','По рынку']]){
        const l=el('label',label);l.append(input(line[field],v=>editLine(line.line_id,field,v),label+' '+row.item.name_en,placeholder));controls.append(l);
      }
      const label=el('label','Рамка для ручной цены'),select=el('select');
      for(const [q,text] of [[1,'Обычное'],[2,'Хорошее'],[3,'Выдающееся'],[4,'Отличное'],[5,'Шедевр']])select.add(new Option(text,q));
      select.value=String(line.output_quality);select.onchange=()=>editLine(line.line_id,'output_quality',select.value).catch(showError);label.append(select);controls.append(label);details.append(controls);$('batch-line-settings').append(details);
    }
  }
  function drawMaterials(){
    $('batch-materials').replaceChildren();
    for(const row of s.data.resources){
      const tr=el('tr');tr.dataset.materialId=row.id;
      const title=el('td');title.append(el('strong',row.name_ru),el('small',`${row.name_en} · ${row.tier}.${row.enchantment}`));
      const needed=el('td',fmt(row.quantity)),bought=el('td');
      bought.append(input(row.bought,v=>editMaterial(row,'bought',v||0),'Уже куплено '+row.name_en));
      const price=el('td');price.append(input(row.manual_price,v=>editMaterial(row,'price',v===''?null:v),'Цена материала '+row.name_en,row.quote?String(row.quote.price):'Нет цены'));
      price.append(el('small',row.status==='manual'?'Ручная цена':row.status==='ready'?'Свежая рыночная цена':row.status==='stale'?'Рыночная цена устарела':'Нужна цена'));
      const actions=el('td'),copyName=el('button','Название','quiet'),copyQty=el('button','Кол-во','quiet');
      copyName.onclick=()=>copy(name(row));copyQty.onclick=()=>copy(String(row.remaining),'quantity');actions.append(copyName,copyQty);
      tr.append(title,needed,bought,el('td',fmt(row.remaining)),price,actions);$('batch-materials').append(tr);
    }
  }
  async function editMaterial(row,field,v){
    s.cfg.materials[row.key]={...s.cfg.materials[row.key],[field]:v};persist();await refresh(true);
  }
  function draw(){
    const p=s.data,empty=!p||!s.cfg.lines.length;$('batch-empty').hidden=!empty;$('batch-body').hidden=empty;
    $('batch-count').textContent=s.cfg.lines.length;$('batch-save').disabled=empty;
    if(empty)return;
    for(const [id,key] of Object.entries(fields))$(id).value=s.cfg[key]??'';
    const sources={private:'мои наблюдения',public:'общие AODP',all:'все источники',legacy:'старые локальные'};
    $('batch-context').textContent=`${s.cfg.server.toUpperCase()} · материалы: ${$('craft-city').selectedOptions[0]?.textContent} · ${sources[s.cfg.scope]}`;
    $('batch-budget').textContent=money(p.summary.remaining_budget);
    $('batch-price-coverage').textContent=`Цены материалов: ${p.summary.ready_materials}/${p.summary.total_materials}. Количество по лучшей цене не гарантировано.`;
    const range=p.summary.no_focus_range;
    $('batch-profit-no-focus').textContent=range?.min==null?'Нужны цены':Math.round(range.min)===Math.round(range.max)?signed(range.min,fmt):`${signed(range.min,fmt)} … ${signed(range.max,fmt)}`;
    $('batch-profit-focus').textContent=money(p.summary.focus_profit);$('batch-produced-total').textContent=fmt(p.lines.reduce((n,r)=>n+r.produced,0))+' шт.';
    $('batch-focus-total').textContent=p.summary.focus==null?'Для серебра / Focus введите фактический расход в строках':`Расход: ${fmt(p.summary.focus)} Focus`;
    $('batch-cash').textContent=`Результат без стоимости возвращённых материалов: ${money(p.summary.cash_profit)}. Перевозка: ${fmt(p.summary.transport)}. Доля спроса — ориентир по известным продажам, не обещание сбыта; пропуски истории не равны нулевым продажам.`;
    drawLines();drawMaterials();drawQueue();
  }
  async function refresh(force=false){
    if(!s.cfg.lines.length){s.data=null;draw();return;}
    if(!force&&$('batch-workspace').contains(document.activeElement)&&['INPUT','SELECT'].includes(document.activeElement.tagName))return;
    s.cfg.all_qualities=true;s.cfg.no_focus_return??=0;
    const sequence=++s.sequence;
    const data=await api('/api/craft/batch/plan',s.cfg);if(sequence!==s.sequence)return;
    s.data=data;s.cfg=data.config;
    if(s.presets.length&&s.codeSignature!==codeSignature())invalidateCodes();
    persist();draw();
  }
  async function list(){
    const data=await api('/api/craft/batches');$('batch-saved').replaceChildren();
    for(const row of data.batches){const button=el('button',row.name,'secondary');button.onclick=async()=>{try{
      const data=await api('/api/craft/batch?'+new URLSearchParams({id:row.id}));invalidateCodes();s.cfg=data.config;s.id=data.id;s.data=data;
      $('batch-name').value=data.name;applyContext(data.config);s.key=null;persist();await refresh(true);
    }catch(e){showError(e);}};$('batch-saved').append(button);}
    if(!data.batches.length)$('batch-saved').append(el('p','Пока нет сохранённых партий.','muted'));
  }
  async function open(){
    if(!s.initialized){
      s.initialized=true;try{const saved=JSON.parse(localStorage.getItem(storageKey));if(saved?.config?.lines){s.cfg=saved.config;s.id=saved.id;s.key=saved.key;$('batch-name').value=saved.name||'Партия крафта';if(s.cfg.lines.length)applyContext(s.cfg);}}catch{}
      if(!s.cfg.lines.length)Object.assign(s.cfg,context());
    }
    await list();await refresh(true);
  }
  async function add(plan){
    if(!plan)return;await addSelection(plan.config,true);
  }
  async function addSelection(c,scroll=false){
    validateUnits(c.units);
    Object.assign(s.cfg,context());const quality=c.output_quality==='auto'?1:c.output_quality;
    const previous=s.cfg.lines.find(r=>r.item_id===c.item_id&&r.variant===c.variant);
    if(previous)previous.units+=c.units;
    else s.cfg.lines.push({line_id:crypto.randomUUID().replaceAll('-',''),item_id:c.item_id,units:c.units,variant:c.variant,output_quality:quality});
    persist();await refresh(true);$('batch-feedback').textContent='Рецепт добавлен. Цены и продажи всех рамок показаны в строке.';
    $('craft-preview').open=false;if(scroll)$('batch-workspace').scrollIntoView({block:'start'});
  }
  async function contextChanged(){Object.assign(s.cfg,context());persist();await refresh(true);}
  for(const [id,key] of Object.entries(fields))$(id).onchange=async()=>{s.cfg[key]=['buy_mode','sell_mode'].includes(key)?$(id).value:$(id).value===''?null:Number($(id).value);persist();try{await refresh(true);}catch(e){showError(e);}};
  $('batch-sort').onchange=$('batch-filter').onchange=()=>s.data&&drawLines();$('batch-language').onchange=drawQueue;$('batch-name').onchange=()=>{persist();invalidateCodes();};
  for(const id of ['batch-loadout-entries','batch-loadout-stack','batch-loadout-owned'])$(id).onchange=invalidateCodes;
  on('batch-export-loadout',async()=>{
    const request=()=>({...s.cfg,name:$('batch-name').value,
      loadout_entries:Number($('batch-loadout-entries').value),loadout_stack:Number($('batch-loadout-stack').value),loadout_include_owned:$('batch-loadout-owned').checked});
    const body=request(),requested=JSON.stringify(body);
    const data=await api('/api/craft/batch/loadouts',body);
    if(requested!==JSON.stringify(request())){invalidateCodes();throw new Error('Партия изменилась во время подготовки кода. Скопируйте код ещё раз.');}
    s.presets=data.presets;s.presetIndex=0;s.codeSignature=codeSignature();drawCode();await copy(s.presets[0].text,'loadout');
    $('batch-feedback').textContent=`Подготовлено кодов: ${s.presets.length}. Формат версии 1 по игровому примеру; импорт этой закупки ещё нужно проверить в Albion.`;
  });
  on('batch-loadout-copy',()=>s.presets[s.presetIndex]&&copy(s.presets[s.presetIndex].text,'loadout'));
  on('batch-loadout-next',async()=>{if(s.presetIndex+1<s.presets.length){s.presetIndex++;drawCode();await copy(s.presets[s.presetIndex].text,'loadout');}});
  on('batch-save',async()=>{const data=await api('/api/craft/batch/save',{...s.cfg,id:s.id,name:$('batch-name').value});s.id=data.id;persist();await list();$('batch-feedback').textContent='Партия и отметки закупки сохранены на компьютере.';});
  on('batch-crystal',async()=>{
    const data=await api('/api/craft/batch/crystal',{...s.cfg,...context(),tier:Number($('craft-tier').value||4),enchantment:Number($('craft-enchantment').value||0)});
    let added=0;
    for(const row of data.config.lines)if(!s.cfg.lines.some(r=>r.item_id===row.item_id&&r.output_quality===row.output_quality&&r.variant===row.variant)){s.cfg.lines.push(row);added++;}
    Object.assign(s.cfg,context());persist();await refresh(true);$('batch-feedback').textContent=`Рецептов кристального оружия в каталоге: ${data.lines.length}. Новых строк: ${added}. Выберите количества и проценты возврата.`;
    $('craft-preview').open=false;
  });
  on('batch-refresh',async()=>{
    $('batch-refresh').disabled=true;$('batch-feedback').textContent='Загружаем цены материалов, готовых вещей и историю продаж…';
    try{if(!s.publicEnabled){await api('/api/settings/public-api',{enabled:true});s.publicEnabled=true;}await job('/api/craft/batch/refresh',{...s.cfg,scope:'all',all_qualities:true});s.cfg.scope='all';applyContext(s.cfg);await refresh(true);$('batch-feedback').textContent='Цены материалов и продажи всех рамок обновлены; собственные наблюдения не отправлялись.';}
    finally{$('batch-refresh').disabled=false;}
  });
  on('batch-copy-name',()=>{const row=active();return row&&copy(name(row));});
  on('batch-copy-quantity',()=>{const row=active();return row&&copy(String(row.remaining),'quantity');});
  on('batch-next',()=>{const rows=queue(),row=active();if(row){s.key=rows[(rows.findIndex(r=>r.key===row.key)+1)%rows.length].key;persist();drawQueue();}});
  on('batch-done',async()=>{const row=active();if(row)await editMaterial(row,'bought',row.quantity);});
  on('batch-copy-all',()=>{const rows=s.data.resources.filter(r=>r.remaining>0);if(!rows.length){notice('Все материалы отмечены купленными.');return;}return copy(rows.map(r=>`${name(r)} · ${r.tier}.${r.enchantment} × ${r.remaining}`).join('\n'),'list');});
  on('batch-clear',()=>{++s.sequence;s.cfg.lines=[];s.cfg.materials={};s.id=null;s.key=null;invalidateCodes();persist();draw();});
  function updateContext(data){s.publicEnabled=data.public_api_enabled;$('batch-refresh').textContent=s.publicEnabled?'Обновить цены и продажи партии':'Включить общие цены и обновить партию';}
  async function setReturn(rate){s.cfg.no_focus_return=rate;persist();await refresh(true);}
  return {open,add,addSelection,refresh,contextChanged,updateContext,getReturn:()=>s.cfg.no_focus_return??0,setReturn};
}
