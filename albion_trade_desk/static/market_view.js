import {qualityGrid,qualityNames} from './quality.js';
export function createMarketView({api,el,fmt,notice,showError,job,filters,markets,craft}) {
  const $=id=>document.getElementById(id);
  let current=null,marketData=null,city=null,quality=1,period=24,seq=0,itemSeq=0,chartData=null;
  function chart(data) {
    chartData=data;const wrap=$('history-chart');wrap.replaceChildren();
    const summary=$('history-summary');summary.replaceChildren();
    summary.append(el('strong',data.known_quantity==null?'Нет данных':`${data.volume==null?'≥ ':''}${fmt(data.known_quantity)} продано`),
      el('span',`Средняя цена: ${fmt(data.vwap)} · покрытие ${data.known_hours}/${data.expected_hours} ч · интервалы ${data.step_hours} ч`));
    const available=data.points.filter(p=>p.average!=null);
    if(!available.length){$('history-hover').textContent=data.known_hours?'Известные интервалы содержат нулевой объём продаж.':'Нет наблюдений за выбранный период.';wrap.append(el('p',data.known_hours?'В известных интервалах продаж нет. Средняя цена не вычисляется; покрытие показано выше.':'История пока не получена для этого города, качества и периода. Загрузите общую историю или просмотрите её в игре с подключённым клиентом.','empty-history'));return;}
    const ns='http://www.w3.org/2000/svg';
    const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 900 280');svg.setAttribute('role','img');svg.setAttribute('aria-label','История средней цены и числа продаж');
    const node=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!=null)n.textContent=text;svg.append(n);return n;};
    const prices=available.map(p=>p.average),lo=Math.min(...prices)*.94,hi=Math.max(...prices)*1.06||1;
    const maxQty=Math.max(1,...data.points.map(p=>p.quantity||0)),width=800/data.points.length;
    for(let i=0;i<4;i++){const y=24+i*55;node('line',{x1:75,x2:875,y1:y,y2:y,stroke:'#ead5ca'});node('text',{x:65,y:y+5,'text-anchor':'end','font-size':14,fill:'#69534e'},fmt(hi-(hi-lo)*i/3));}
    let path='',last=false;
    data.points.forEach((p,i)=>{
      const x=75+(i+.5)*width;
      if(p.quantity!=null)node('rect',{x:x-width*.32,y:245-65*p.quantity/maxQty,width:Math.max(1,width*.64),height:65*p.quantity/maxQty,fill:p.complete?'#d4a68a':'#ead7c7',rx:2});
      if(p.average==null){last=false;return;}
      const y=24+(hi-p.average)/(hi-lo)*165;
      path+=`${last?'L':'M'}${x},${y} `;last=true;
    });
    node('path',{d:path,fill:'none',stroke:'#ba6444','stroke-width':3});
    data.points.forEach((p,i)=>{if(p.average==null)return;const x=75+(i+.5)*width,y=24+(hi-p.average)/(hi-lo)*165;
      const dot=node('circle',{cx:x,cy:y,r:4,fill:'#fff5e9',stroke:'#a85a40','stroke-width':2,tabindex:0});
      const info=`${new Date(p.start*1000).toLocaleString('ru-RU')} — ${new Date(p.end*1000).toLocaleString('ru-RU')} · цена ${fmt(p.average)} · продано ${p.complete?'':'≥ '}${fmt(p.quantity)} · ${p.known_hours}/${p.expected_hours} ч`;
      const title=document.createElementNS(ns,'title');title.textContent=info;dot.append(title);dot.setAttribute('aria-label',info);
      dot.onmouseenter=dot.onfocus=()=>{$('history-hover').textContent=info;};
    });
    for(const f of [0,.25,.5,.75,1])node('text',{x:75+f*800,y:273,'text-anchor':f===0?'start':f===1?'end':'middle','font-size':14,fill:'#69534e'},new Date((data.start+f*(data.end-data.start))*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'short'})+(data.expected_hours<=48?' '+new Date((data.start+f*(data.end-data.start))*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}):''));
    wrap.append(svg);$('history-hover').textContent='Наведите на точку: средняя цена, продажи и покрытие интервала. Пропуски не считаются нулевыми продажами.';
  }
  function query(){return {id:current.id,server:current.server,city,quality,scope:filters().scope,hours:period,
    ...($('history-custom').checked?{start:new Date($('history-start').value).toISOString(),end:new Date($('history-end').value).toISOString()}: {})};}
  async function loadHistory(){const id=++seq;$('history-chart').replaceChildren(el('p','Загрузка истории…'));$('history-summary').replaceChildren();try{const data=await api('/api/history?'+new URLSearchParams(query()));if(id===seq)chart(data);}catch(e){if(id===seq){$('history-chart').replaceChildren(el('p','Не удалось прочитать историю выбранного города и качества.','empty-history'));$('history-hover').textContent=e.message;}throw e;}}
  function prices(){
    const row=marketData.markets.find(r=>r.location===city);
    $('detail-prices').replaceChildren(qualityGrid(row?.by_quality,{el,fmt,bm:city==='3003'}));
    $('detail-bm').hidden=city!=='3003';
  }
  function renderCities(){
      const table=el('table'),head=el('tr');head.append(el('th','Город'));for(const q of Object.values(qualityNames))head.append(el('th',q));table.append(head);
      for(const row of marketData.markets){const tr=el('tr');tr.append(el('td',markets()[row.location]));
        for(const entry of row.by_quality){const q=entry.quotes[row.location==='3003'?'buy_price_max':'sell_price_min'];const td=el('td',q?fmt(q.price):'—',entry.quality===5?'masterpiece':'');if(q)td.title=`${q.fresh?'Свежая':'Устаревшая'} · ${new Date(q.observed_at*1000).toLocaleString('ru-RU')}`;tr.append(td);}table.append(tr);}
      $('detail-cities').replaceChildren(table);
  }
  async function open(item){
    const request=++itemSeq;++seq;current=item;city=filters().city;quality=Number.isInteger(Number(item.quality))?Number(item.quality):item.quotes.sell_price_min?.quality||item.quotes.buy_price_max?.quality||1;
    $('detail-title').textContent=item.name_ru;$('detail-id').textContent=`${item.name_en} · ${item.id} · ${item.server.toUpperCase()}`;
    $('detail-prices').replaceChildren(el('p','Загрузка…'));$('item-dialog').showModal();
    try {
      const result=await api('/api/item?'+new URLSearchParams({...filters(),id:item.id,server:item.server}));
      if(request!==itemSeq||!$('item-dialog').open)return;marketData=result;
      $('detail-city').replaceChildren(...Object.entries(markets()).map(([id,name])=>new Option(name,id)));$('detail-city').value=city;
      $('history-quality').value=String(quality);
      const localInput=t=>{const d=new Date(t);return new Date(t-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
      const end=Math.floor(Date.now()/3600000)*3600000;$('history-end').value=localInput(end);$('history-start').value=localInput(end-period*3600000);$('history-custom').checked=false;$('history-custom-fields').hidden=true;
      prices();
      renderCities();$('detail-craft').hidden=!item.has_recipe;$('detail-refresh').disabled=filters().scope==='private';
      await loadHistory();
    }catch(e){showError(e);$('detail-prices').append(el('p',e.message,'error'));}
  }
  $('detail-city').onchange=async()=>{city=$('detail-city').value;prices();try{await loadHistory();}catch(e){showError(e);}};
  $('history-quality').onchange=()=>{quality=Number($('history-quality').value);loadHistory().catch(showError);};
  for(const button of document.querySelectorAll('[data-period]'))button.onclick=()=>{
    period=Number(button.dataset.period);$('history-custom').checked=false;$('history-custom-fields').hidden=true;
    for(const b of document.querySelectorAll('[data-period]'))b.classList.toggle('active',b===button);loadHistory().catch(showError);
  };
  $('history-custom').onchange=()=>{$('history-custom-fields').hidden=!$('history-custom').checked;};
  $('history-apply').onclick=()=>loadHistory().catch(showError);
  $('history-fetch').onclick=async()=>{try{if(filters().scope==='private')throw new Error('Выбраны мои наблюдения. Просмотрите историю в игре с подключённым клиентом.');await job('/api/history/refresh',query());await loadHistory();}catch(e){showError(e);$('history-hover').textContent=e.message;}};
  $('detail-refresh').onclick=async()=>{try{$('detail-refresh').disabled=true;await job('/api/market/refresh',{items:[current.id],server:current.server,cities:[city],qualities:[1,2,3,4,5]});marketData=await api('/api/item?'+new URLSearchParams({...filters(),id:current.id,server:current.server}));prices();renderCities();}catch(e){showError(e);$('history-hover').textContent=e.message;}finally{$('detail-refresh').disabled=filters().scope==='private';}};
  $('detail-craft').onclick=()=>{$('item-dialog').close();craft(current.id,quality);};
  return {open,qualityGrid:rows=>qualityGrid(rows,{el,fmt,bm:filters().city==='3003',compact:true})};
}
