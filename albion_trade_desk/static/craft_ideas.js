import {qualitySummary,profitRange,salesText} from './craft_summary.js';
export function createCraftIdeas({api,el,fmt,showError,job,context,applyContext,addSelection,getReturn,setReturn}){
  const $=id=>document.getElementById(id),key='albion-craft-ideas-v1';
  const s={data:null,sequence:0,initialized:false,analyzing:false,pending:false,downloading:false,publicEnabled:false,lastCheck:0,revision:null};
  const controls=['ideas-tier','ideas-enchantment','ideas-category','ideas-search','ideas-show','ideas-sort','ideas-min-sales'];
  function persist(){localStorage.setItem(key,JSON.stringify(Object.fromEntries(controls.map(id=>[id,$(id).value]))));}
  function sync(){const c=context();$('ideas-city').value=c.city;$('ideas-sale-city').value=c.sale_city;$('ideas-scope').value=c.scope;$('ideas-return').value=getReturn()??0;}
  function body(){return {...context(),tier:$('ideas-tier').value,enchantment:$('ideas-enchantment').value,
    category:$('ideas-category').value,search:$('ideas-search').value,show:$('ideas-show').value,sort:$('ideas-sort').value,
    min_sales:Number($('ideas-min-sales').value||0),no_focus_return:Number(getReturn()??0)};}
  function downloadLabel(){if(!s.downloading)$('ideas-update').textContent=s.publicEnabled?'Обновить цены и продажи':'Включить общие цены и обновить';}
  function updateContext(data){
    s.publicEnabled=data.public_api_enabled;downloadLabel();
    if(!$('ideas-city').options.length)for(const [id,name] of Object.entries(data.markets)){
      if(id!=='3003')$('ideas-city').add(new Option(name,id));$('ideas-sale-city').add(new Option(name,id));
    }
  }
  function draw(){
    const p=s.data;if(!p)return;
    $('ideas-assumptions').textContent=`Без Focus · Налог без Premium 8% + размещение 2.5% · Возврат ${fmt(p.economics.no_focus_return)}% · ${p.economics.scope==='private'?'Мои наблюдения':p.economics.scope==='public'?'Общие данные':'Данные выбранных источников'}`;
    $('ideas-counts').replaceChildren();
    for(const [label,count] of [['С прибылью и продажами',p.counts.recommended],['С положительной оценкой',p.counts.profit],['Не хватает данных',p.counts.missing]])$('ideas-counts').append(el('span',`${label}: ${fmt(count)}`));
    $('ideas-coverage').textContent=`Проверено рецептов: ${fmt(p.evaluated_recipes)} из ${fmt(p.matched_recipes)} · разных предметов: ${fmt(p.evaluated_items)}.`+(p.unsupported_recipes.length?` Пропущено недоступных рецептов: ${p.unsupported_recipes.length}.`:'');
    const cards=document.createDocumentFragment();
    for(const row of p.rows){
      const card=el('article',null,'craft-opportunity');card.dataset.itemId=row.item.id;
      const info=el('div',null,'opportunity-info');
      info.append(el('h3',`${row.item.name_ru} · ${row.item.tier}.${row.item.enchantment}`),el('small',row.item.name_en));
      const status=row.recommended?'Есть прибыль и продажи':row.profit==null?'Нужны цены обычного качества или материалов':row.profit<0?'Есть риск убытка':row.known_sales==null?'Нужна история продаж':'Мало известных продаж';
      info.append(el('span',status,`idea-status ${row.recommended?'positive':row.profit<0?'negative':'pending'}`));
      const stats=el('div',null,'opportunity-stats');
      for(const [label,text,cls] of [['Материалы / шт.',row.materials_per_unit==null?'Нет цены':fmt(Math.round(row.materials_per_unit)),null],
        ['Прибыль I–IV / шт.',profitRange(row.overview,fmt),row.profit==null?'muted':row.profit<0?'loss':'gain'],['Продано I–IV / 7 дн.',salesText(row.overview,fmt),null]]){
        const stat=el('div');stat.append(el('small',label),el('strong',text,cls));stats.append(stat);
      }
      info.append(stats);
      if(!row.overview.sales_complete&&row.known_sales!=null)info.append(el('small','История неполная — показана известная часть.','muted'));
      if(!row.overview.ordinary_price_known)info.append(el('small','Без цены обычной рамки предмет не попадает в рекомендации.','muted'));
      const actions=el('div',null,'opportunity-actions'),amount=el('input');amount.type='number';amount.min='1';amount.max='1000000';amount.step='1';amount.value='1';amount.setAttribute('aria-label','Количество для '+row.item.name_en);
      const add=el('button','В закупку','primary');add.onclick=async()=>{try{
        add.disabled=true;await addSelection({item_id:row.item.id,units:Number(amount.value),variant:row.variant,output_quality:1});
        $('ideas-feedback').textContent=`Добавлено в закупку: ${row.item.name_ru} × ${amount.value}. Можно продолжить подбор.`;
      }catch(e){showError(e);$('ideas-feedback').textContent=e.message;}finally{add.disabled=false;}};
      actions.append(amount,add);if(row.suggested_limit!=null&&row.suggested_limit>0)actions.append(el('small',`Ориентир по известным продажам: до ${fmt(row.suggested_limit)} шт.`));
      info.append(actions);card.append(info,qualitySummary(row.qualities,{el,fmt}));cards.append(card);
    }
    $('ideas-results').replaceChildren(cards);
    $('ideas-empty').hidden=p.rows.length>0;
  }
  async function analyze(){
    if(s.downloading)return;
    const sequence=++s.sequence;persist();
    if(s.analyzing){s.pending=true;return;}
    s.analyzing=true;$('ideas-find').disabled=true;$('ideas-update').disabled=true;$('ideas-feedback').textContent='Сравниваем все подходящие рецепты по вашей базе…';
    try{
      const request=body(),data=await api('/api/craft/ideas',request);if(sequence!==s.sequence)return;
      s.data=data;s.lastBody=JSON.stringify(request);draw();$('ideas-feedback').textContent=data.counts.recommended?`Подходящих по известным ценам и продажам: ${data.counts.recommended}.`:'Можно загрузить цены и продажи прямо здесь. Отсутствующие данные не считаются нулевыми.';
    }catch(e){if(sequence===s.sequence){showError(e);$('ideas-feedback').textContent=e.detail||e.message;}}
    finally{
      s.analyzing=false;
      if(s.pending){s.pending=false;await analyze();}
      else{$('ideas-find').disabled=s.downloading;$('ideas-update').disabled=s.downloading;}
    }
  }
  async function open(){
    sync();$('ideas-return').value=getReturn()??0;
    if(!s.initialized){s.initialized=true;try{const saved=JSON.parse(localStorage.getItem(key));for(const id of controls)if(saved?.[id]!=null)$(id).value=saved[id];}catch{} }
    await analyze();
  }
  async function poll(force=false){
    if(!s.initialized||s.downloading||s.analyzing)return;
    if($('craft-ideas').contains(document.activeElement)&&['INPUT','SELECT'].includes(document.activeElement.tagName))return;
    force=force||s.lastBody!==JSON.stringify(body());
    if(!force&&Date.now()-s.lastCheck<10000)return;s.lastCheck=Date.now();
    const rev=JSON.stringify(await api('/api/craft/ideas/revision'));
    if(force||s.revision!==rev){s.revision=rev;sync();await analyze();}
  }
  for(const id of controls.filter(id=>id!=='ideas-search'))$(id).onchange=()=>analyze();
  let debounce;$('ideas-search').oninput=()=>{clearTimeout(debounce);debounce=setTimeout(()=>analyze(),280);};
  for(const id of ['ideas-city','ideas-sale-city','ideas-scope'])$(id).onchange=async()=>{
    try{await applyContext({...context(),city:$('ideas-city').value,sale_city:$('ideas-sale-city').value,scope:$('ideas-scope').value});await analyze();}catch(e){showError(e);$('ideas-feedback').textContent=e.detail||e.message;}
  };
  $('ideas-return').onchange=async()=>{try{await setReturn(Number($('ideas-return').value||0));await analyze();}catch(e){showError(e);}};
  $('ideas-find').onclick=()=>analyze();$('ideas-show-all').onclick=()=>{$('ideas-show').value='all';analyze();};
  $('ideas-to-shopping').onclick=()=>$('batch-workspace').scrollIntoView({block:'start',behavior:'smooth'});
  document.addEventListener('albion-job-progress',event=>{if(s.downloading&&event.detail.kind==='craft-ideas'){
    const p=event.detail.progress;$('ideas-feedback').textContent=`${p.label} · ${p.done}/${p.total}`;
  }});
  $('ideas-update').onclick=async()=>{
    const request={...body(),scope:'all'},before=context();s.downloading=true;
    const inputs=[...$('craft-ideas').querySelectorAll('input,select,button')];for(const node of inputs)node.disabled=true;
    $('ideas-feedback').textContent='Готовим цены материалов и продажи всех рамок…';
    try{
      if(!s.publicEnabled){await api('/api/settings/public-api',{enabled:true});s.publicEnabled=true;}
      await job('/api/craft/ideas/refresh',request);
      const after=context();
      if(['server','city','sale_city'].every(k=>before[k]===after[k]))await applyContext({...after,scope:'all'});
      s.downloading=false;sync();await analyze();
      $('ideas-feedback').textContent='Цены материалов, готовых вещей и продажи всех рамок обновлены. Собственные наблюдения не отправлялись.';
    }catch(e){showError(e);$('ideas-feedback').textContent=e.detail||e.message;}
    finally{s.downloading=false;for(const node of inputs)node.disabled=false;downloadLabel();if(s.data)draw();}
  };
  return {open,poll,updateContext,analyze,sync};
}
