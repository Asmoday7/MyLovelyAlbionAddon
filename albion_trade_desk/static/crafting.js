import {qualityGrid,qualityNames} from './quality.js';
import {createCraftBatch} from './craft_batch.js';
import {createCraftIdeas} from './craft_ideas.js';
// The server owns recipes, quantities, provenance and cost calculations.
export function createCrafting({api, fmt, date, el, notice, showError, job, showView, catalog, initialCity, initialScope, maxAge}) {
  const $ = id => document.getElementById(id);
  const s = {family:null, plan:null, id:null, families:[], sequence:0, searchSequence:0, signature:'', initialized:false, polling:false, focused:null};
  const on = (id, action) => $(id).addEventListener('click', async () => {try {await action();} catch(e) {showError(e);}});
  const cfg = () => ({item_id:selectedItem()?.id,units:$('craft-units').value,variant:$('craft-recipe').value || 0,
    output_quality:$('craft-quality').value,city:$('craft-city').value,sale_city:$('craft-sale-city').value,
    server:$('server').value,scope:$('craft-scope').value,max_age_hours:$('craft-age').value});
  function selectedItem() {
    return s.family?.variants.find(v => String(v.tier)===$('craft-tier').value && String(v.enchantment)===$('craft-enchantment').value);
  }
  function options(select, values, selected) {
    select.replaceChildren(...values.map(([value,label]) => new Option(label,value)));
    if (values.some(([v]) => String(v)===String(selected))) select.value=String(selected);
  }
  function chooseEnchantment(preferred=0) {
    const choices=s.family.variants.filter(v => String(v.tier)===$('craft-tier').value);
    options($('craft-enchantment'),choices.map(v => [v.enchantment,v.enchantment ? `.${v.enchantment}` : '.0 · без чар']),preferred);
    options($('craft-recipe'),[[0,'Основной рецепт']],0);
  }
  async function chooseFamily(f, uid=null) {
    s.family=f; s.signature='';
    const item=f.variants.find(v=>v.id===uid)||f.variants.find(v=>v.id===f.id)||f.variants[0];
    options($('craft-tier'),[...new Set(f.variants.map(v=>v.tier))].map(t=>[t,`Тир ${t}`]),item.tier);
    chooseEnchantment(item.enchantment);
    renderSearch();
    await refreshPlan(true);
    $('craft-selection').textContent=`${item.name_ru} · ${item.tier}.${item.enchantment}`;
    $('craft-selector').open=false;
  }
  function renderSearch() {
    $('craft-search-results').replaceChildren();
    for (const f of s.families) {
      const button=el('button',f.name_ru,s.family?.family===f.family?'active':'');
      button.append(el('small',f.name_en));
      button.onclick=()=>{s.id=null;chooseFamily(f).catch(showError);};
      $('craft-search-results').append(button);
    }
    if (!s.families.length) $('craft-search-results').append(el('p','Рецепты не найдены. Попробуйте другое название или обновите список предметов.','muted'));
  }
  async function search(text, auto=false, uid=null) {
    const sequence=++s.searchSequence;
    const data=await api('/api/craft/search?'+new URLSearchParams({search:text}));
    if (sequence!==s.searchSequence) return;
    s.families=data.results;
    renderSearch();
    if ((auto || s.families.length===1) && s.families.length) {
      if (!uid && s.family?.family!==s.families[0].family) s.id=null;
      await chooseFamily(s.families[0],uid);
    }
  }
  async function refreshPlan(force=false) {
    if (!selectedItem() || (!force && s.loading)) return;
    const sequence=++s.sequence;
    s.loading=sequence;
    let data;
    // Poll the committed selection, not a half-entered quantity in the form.
    try {data=await api('/api/craft/plan',force||!s.plan?cfg():s.plan.config);}
    catch(e) {if(sequence===s.sequence){s.plan=null;$('craft-plan').hidden=true;}throw e;}
    finally {if(s.loading===sequence) s.loading=0;}
    if (sequence!==s.sequence) return;
    s.plan=data;
    const oq=data.output_market.quote;
    const signature=JSON.stringify([data.config,data.resources.map(r=>[r.id,r.quantity,r.status,r.quote?.price,r.quote?.observed_at,r.quote?.received_at,Math.floor((r.quote?.age_seconds||0)/60)]),[oq?.price,oq?.observed_at,oq?.received_at,oq?.fresh,Math.floor((oq?.age_seconds||0)/60)],data.output_market.by_quality.map(r=>[r.quality,Object.values(r.quotes).map(q=>[q.price,q.observed_at,q.received_at,q.fresh])])]);
    if (force || signature!==s.signature) {s.signature=signature;renderPlan();}
  }
  function copyName(row) {return $('craft-copy-language').value==='ru'?row.name_ru:row.name_en;}
  async function copy(text,target='search') {
    try {await navigator.clipboard.writeText(text);notice(target==='loadout'?'Код комплекта скопирован. В Albion выберите «Вставить текст» / Paste Text, проверьте состав и сохраните.':`Скопировано: ${text.length>110?'список материалов':text}. `+(target==='quantity'?'Вставьте в поле количества в игре.':target==='list'?'Список можно сохранить в заметках.':'Вставьте в поиск рынка вручную.'));}
    catch { $('copy-text').value=text;$('copy-dialog').showModal();$('copy-text').focus();$('copy-text').select(); }
  }
  function sourceName(q) {return q?.source==='private-client'?'Моё наблюдение':q?.source==='data-client'?'Старое локальное':'Общие данные';}
  function resource(row, output=false) {
    const wrap=el('div',null,`craft-resource ${row.status==='ready'?'ready':''} ${s.focused===row.id?'focused':''}`);
    wrap.dataset.itemId=row.id;
    const name=el('div');name.append(el('div',row.name_ru,'resource-name'),el('small',row.name_en));
    name.append(el('small',`Тир ${row.tier}.${row.enchantment} · ${output?'готовый предмет · '+(qualityNames[row.quality]||'любая рамка'):'материал, обычное качество'}`));
    if (!output && row.returnable_quantity===0) name.append(el('small','Компонент без возврата ресурсов'));
    name.title=row.id;
    const quantity=el('div',null);quantity.append(el('span',fmt(row.quantity),'resource-qty'),el('small','шт.'));
    const price=el('div');
    price.append(el('div',row.quote?fmt(row.quote.price)+' серебра':'Нет цены','resource-price'));
    price.append(el('span',row.status==='ready'?'Цена свежая':row.status==='stale'?'Устарело или заявка истекла':'Ещё нужно получить цену',`resource-state ${row.status}`));
    if (row.quote) {price.append(el('small',`${sourceName(row.quote)} · ${fmt(row.quote.age_seconds/3600)} ч назад`));price.title=`Наблюдение: ${date(row.quote.observed_at)}\nПолучено: ${date(row.quote.received_at)}\n${row.quote.limitation}`;}
    const button=el('button','Копировать','secondary');button.disabled=Boolean(row.catalogue_missing);
    button.setAttribute('aria-label',`Копировать поиск: ${row.name_en}`);
    button.onclick=async()=>{s.focused=row.id;await copy(copyName(row));renderPlan();};
    if (row.catalogue_missing) name.append(el('small','Название неизвестно: обновите каталог'));
    wrap.append(name,quantity,price,button);return wrap;
  }
  function outputRow() {
    const p=s.plan,q=p.output_market.quote;
    return {...p.item,quantity:p.produced,quality:p.output_market.quote?.quality||p.output_market.quality,quote:q,
      status:q?.fresh?'ready':q?'stale':'missing',catalogue_missing:false};
  }
  function renderPlan() {
    const p=s.plan;if (!p) return;
    $('craft-plan').hidden=false;
    $('craft-item-title').textContent=`${p.item.name_ru} · ${p.item.tier}.${p.item.enchantment}`;
    $('craft-item-subtitle').textContent=`${p.item.name_en} · ${p.config.server.toUpperCase()} · материалы в ${$('craft-city').selectedOptions[0]?.textContent}`;
    $('craft-ready').textContent=`${p.ready_count} / ${p.resource_count}`;
    $('craft-cost').textContent=p.materials_cost==null?'Нужны цены':fmt(p.materials_cost)+' серебра';
    $('craft-cost-note').textContent=p.materials_cost==null?(p.known_materials_cost?`Известна только часть: ${fmt(p.known_materials_cost)} серебра`:'Нулевой цены не предполагаем'):p.recipe_silver?`Плюс серебро рецепта: ${fmt(p.recipe_silver)}. База партии: ${fmt(p.base_batch_cost)}`:'Только материалы, без станции и налогов';
    $('craft-produced').textContent=fmt(p.produced)+' шт.';
    $('craft-operations').textContent=`${fmt(p.operations)} операций по рецепту`;
    $('craft-rounding').hidden=!p.overproduction;
    $('craft-rounding').textContent=`Рецепт выпускает несколько единиц: для ${p.config.units} нужно ${p.operations} операций. Получится ${p.produced}, излишек — ${p.overproduction} шт.`;
    $('craft-recipe-label').hidden=p.recipe_variants.length<=1;
    options($('craft-recipe'),p.recipe_variants.map(r=>[r.variant,`Рецепт ${r.variant+1} · выход ${r.output}`]),p.config.variant);
    $('craft-save').textContent=s.id?'Сохранить изменения':'Сохранить набор';
    $('craft-save-copy').hidden=!s.id;$('craft-delete').hidden=!s.id;
    $('craft-resources').replaceChildren(...p.resources.map(r=>resource(r)));
    $('craft-output').replaceChildren(resource(outputRow(),true),qualityGrid(p.output_market.by_quality,{el,fmt,bm:p.output_market.location==='3003'}));
    $('craft-output').append(el('p',p.output_market.kind==='buy_price_max'?'Black Market: смотрим только заявку покупателя, не sell-цену.':'Готовый предмет: смотрим предложения продавцов для сравнения. Это не чистая прибыль.','caveat'));
    $('craft-public-refresh').disabled=p.config.scope==='private';
    const missing=p.resources.filter(r=>r.status!=='ready').length;
    $('craft-flow-hint').textContent=p.config.scope==='private'?`Выбраны только мои наблюдения. Для материалов смотрите предложения продавцов в игре. Ещё нужны свежие цены: ${missing}. При настроенном Data Client список обновится сам.`:`Ещё нужны свежие цены материалов: ${missing}. Можно загрузить общие цены одной кнопкой или вручную просмотреть рынок с подключённым Data Client.`;
  }
  async function listPacks() {
    const data=await api('/api/craft/packs');
    $('craft-saved-count').textContent=data.packs.length;
    $('craft-saved-list').replaceChildren();
    if (!data.packs.length) $('craft-saved-list').append(el('p','Сохраните первый набор — потом он будет открываться одним нажатием.','muted'));
    for (const p of data.packs) {
      const button=el('button',p.name,p.id===s.id?'active':'');
      const sourceLabels={private:'мои наблюдения',public:'общие цены',legacy:'старые локальные',all:'все источники'};
      button.append(el('small',`${p.config.server.toUpperCase()} · ${p.config.units} шт. · ${sourceLabels[p.config.scope]}`));
      button.onclick=async()=>{try {await loadPack(p.id);}catch(e){showError(e);}};
      $('craft-saved-list').append(button);
    }
  }
  async function loadPack(id) {
    const data=await api('/api/craft/pack?'+new URLSearchParams({id}));
    const c=data.config;s.id=id;
    $('server').value=c.server;$('craft-city').value=c.city;$('craft-sale-city').value=c.sale_city;
    $('craft-scope').value=c.scope;$('craft-age').value=c.max_age_hours;
    $('craft-units').value=c.units;$('craft-quality').value=c.output_quality;
    s.manualLoading=true;$('craft-manual').open=true;$('craft-preview').open=true;
    try{await search(c.item_id,true,c.item_id);}finally{s.manualLoading=false;}
    $('craft-recipe').value=String(c.variant);
    await refreshPlan(true);await listPacks();
    await batch.contextChanged();
  }
  async function save(asCopy=false) {
    if (!s.plan) return;
    const data=await api('/api/craft/packs',{...cfg(),id:asCopy?null:s.id});
    s.id=data.id;s.plan=data;renderPlan();await listPacks();notice('Набор сохранён на этом компьютере. Цены в нём будут перечитываться из вашей базы.');
  }
  function updateContext(data) {
    $('craft-no-catalog').hidden=data.items>0;$('craft-workspace').hidden=!data.items;
    if (!$('craft-city').options.length) {
      for (const [id,name] of Object.entries(data.markets)) {
        if (id!=='3003') $('craft-city').add(new Option(name,id));
        $('craft-sale-city').add(new Option(name,id));
      }
    }
    batch.updateContext(data);ideas.updateContext(data);
  }
  async function open(loadIdeas=true) {
    if (!catalog()) return;
    if (!s.initialized) {
      $('craft-city').value=initialCity()==='3003'?'1002':initialCity();
      $('craft-sale-city').value=initialCity();$('craft-scope').value=initialScope();$('craft-age').value=maxAge();
      s.initialized=true;
    }
    await listPacks();
    await batch.open();
    if(s.family)await refreshPlan(true);
    if(loadIdeas)await ideas.open();
  }
  async function openItem(uid,outputQuality=1) {
    await open(false);s.id=null;s.manualLoading=true;$('craft-manual').open=true;
    $('craft-city').value=initialCity()==='3003'?'1002':initialCity();$('craft-sale-city').value=initialCity();
    $('craft-scope').value=initialScope();$('craft-quality').value=String(['auto','all'].includes(String(outputQuality))?'auto':outputQuality);
    try{$('craft-search').value=uid;await search(uid,true,uid);await batch.contextChanged();$('craft-preview').open=true;}
    finally{s.manualLoading=false;}
  }
  const batch=createCraftBatch({api,el,fmt,notice,showError,job,copy,context:()=>{
    const c=cfg();return Object.fromEntries(['server','city','sale_city','scope','max_age_hours'].map(k=>[k,c[k]]));
  },applyContext:c=>{
    $('server').value=c.server;$('craft-city').value=c.city;$('craft-sale-city').value=c.sale_city;
    $('craft-scope').value=c.scope;$('craft-age').value=c.max_age_hours;
  }});
  const ideas=createCraftIdeas({api,el,fmt,showError,job,context:()=>{
    const c=cfg();return Object.fromEntries(['server','city','sale_city','scope','max_age_hours'].map(k=>[k,c[k]]));
  },applyContext:async c=>{
    $('server').value=c.server;$('craft-city').value=c.city;$('craft-sale-city').value=c.sale_city;$('craft-scope').value=c.scope;$('craft-age').value=c.max_age_hours;
    await batch.contextChanged();await refreshPlan(true);
  },addSelection:selection=>batch.addSelection(selection),getReturn:()=>batch.getReturn(),setReturn:rate=>batch.setReturn(rate)});
  $('craft-manual').addEventListener('toggle',async()=>{
    if($('craft-manual').open&&!s.family&&!s.manualLoading){s.manualLoading=true;try{$('craft-search').value='Forgebark';await search('Forgebark',true);}catch(e){showError(e);}finally{s.manualLoading=false;}}
  });
  on('batch-add',()=>batch.add(s.plan));
  let debounce;
  $('craft-search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>search($('craft-search').value).catch(showError),220);});
  $('craft-tier').addEventListener('change',()=>{chooseEnchantment(Number($('craft-enchantment').value));refreshPlan(true).catch(showError);});
  $('craft-enchantment').addEventListener('change',()=>{options($('craft-recipe'),[[0,'Основной рецепт']],0);refreshPlan(true).catch(showError);});
  for (const id of ['craft-units','craft-quality','craft-city','craft-sale-city','craft-scope','craft-age','craft-recipe']) $(id).addEventListener('change',async()=>{try{await refreshPlan(true);if(['craft-city','craft-sale-city','craft-scope','craft-age'].includes(id))await batch.contextChanged();}catch(e){showError(e);}});
  $('server').addEventListener('change',async()=>{if (!$('craft-view').hidden)try{await refreshPlan(true);await batch.contextChanged();}catch(e){showError(e);}});
  on('craft-forgebark',()=>{s.id=null;$('craft-search').value='Forgebark';return search('Forgebark',true);});
  on('craft-save',()=>save());on('craft-save-copy',()=>save(true));
  on('craft-delete',async()=>{await api('/api/craft/delete',{id:s.id});s.id=null;renderPlan();await listPacks();notice('Набор убран из сохранённых. Список остался на экране — его можно сохранить снова. Рыночные данные не удалялись.');});
  on('craft-next',async()=>{
    if (!s.plan) return;
    const rows=[...s.plan.resources,outputRow()];
    const next=rows.find(r=>r.status!=='ready'&&!r.catalogue_missing);
    if (!next) {notice('Для всех материалов и готового предмета уже есть свежие цены. Это не означает полного сканирования рынка.');return;}
    s.focused=next.id;await copy(copyName(next));renderPlan();
  });
  on('craft-copy-all',()=>copy(s.plan.resources.map(r=>`${copyName(r)} · ${r.tier}.${r.enchantment} × ${fmt(r.quantity)}`).join('\n'),'list'));
  on('craft-public-refresh',async()=>{await job('/api/craft/refresh',cfg());await refreshPlan(true);});
  on('craft-open-private',()=>showView('private'));
  on('craft-load-catalog',()=>{showView('market');return job('/api/catalog/sync',{});});
  on('copy-close',()=>$('copy-dialog').close());
  setInterval(async()=>{
    if (document.hidden||$('craft-view').hidden||s.polling) return;
    s.polling=true;
    try {await refreshPlan();await batch.refresh();await ideas.poll();} catch(e) {if(s.lastError!==e.message){s.lastError=e.message;showError(e);}}
    finally {s.polling=false;}
  },3000);
  return {open,openItem,updateContext,refresh:async()=>{await refreshPlan(true);await batch.refresh(true);await ideas.poll(true);}};
}
