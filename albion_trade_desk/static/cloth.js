export function createCloth({api,el,fmt,notice,showError}) {
  const $=id=>document.getElementById(id);
  let config=null,tier=4,seq=0,loaded=false;
  const fields=['batch','return_rate','tax_pct','station','t3_price','coefficient','mode','rounding','steps','secondary_initial','secondary_rate'];
  function collect(){return {...config,...Object.fromEntries(fields.map(k=>[k,$('cloth-'+k).value])),levels:Object.fromEntries([...document.querySelectorAll('[data-cloth-level]')].map(n=>[n.dataset.clothLevel,n.value]))};}
  function table(headers,rows){const t=el('table'),h=el('tr');for(const name of headers)h.append(el('th',name));t.append(h);for(const row of rows){const tr=el('tr');for(const value of row)tr.append(el('td',value));t.append(tr);}return t;}
  function render(data){
    $('cloth-output').textContent=fmt(data.expected_output)+' шт.';$('cloth-output').title=String(data.expected_output);$('cloth-additional').textContent='+'+fmt(data.additional_output)+' шт.';$('cloth-additional').title=String(data.additional_output);
    $('cloth-model-note').textContent=data.config.mode==='finite'?`Первая партия + ${data.config.steps} повторов. ${data.config.rounding==='continuous'?'Дробная оценка как в исходном Excel.':'Каждый возвращённый материал округляем вниз; при нехватке операции прекращаются.'}`:data.config.mode==='coefficient'?'Ручной коэффициент добавочных единиц; таблица повторов ниже служит отдельным сравнением.':'Теоретический предел без ограничения повторов. Для практического расчёта используйте «Ограниченные повторы».';$('cloth-fce').textContent=fmt(data.global_fce);
    $('cloth-coefficient').disabled=data.config.mode!=='coefficient';
    $('cloth-rows').replaceChildren();
    for(const row of data.rows.filter(r=>r.tier===tier)){
      const tr=el('tr');tr.append(el('th',`${row.tier}.${row.enchantment}`));
      for(const key of ['fiber','cloth_buy','sale']){
        const td=el('td'),input=el('input');input.type='number';input.min='0';input.value=row[key];input.setAttribute('aria-label',`${key} ${row.tier}.${row.enchantment}`);
        input.onchange=()=>{config.rows.find(r=>r.tier===row.tier&&r.enchantment===row.enchantment)[key]=input.value;recalculate().catch(showError);};td.append(input);tr.append(td);
      }
      for(const value of [row.initial_cost,row.profit,row.profit_per_focus])tr.append(el('td',fmt(value),value<0?'loss':'profit'));
      $('cloth-rows').append(tr);
    }
    const focusRows=[];for(let t=4;t<=8;t++)focusRows.push([`T${t}`,...data.rows.filter(r=>r.tier===t).map(r=>fmt(r.focus_first_batch))]);
    $('cloth-focus').replaceChildren(table(['Тир','.0','.1','.2','.3','.4'],focusRows));
    $('cloth-loop-summary').textContent=`Первая партия + ${data.config.steps} повторов: первая партия — ${fmt(data.main_loop.produced)} ткани, осталось ресурсов на ${fmt(data.main_loop.remaining)} операций; Focus ${fmt(data.main_loop.focus)}. Вторая — ${fmt(data.secondary_loop.produced)} ткани, Focus ${fmt(data.secondary_loop.focus)}.`;
    $('cloth-loops').replaceChildren(table(['Шаг','Обрабатывается','Доступно операций из остатка','Всего изготовлено','Focus T8.2','Вторая: обрабатывается','Вторая: всего'],data.main_loop.rows.map((r,i)=>[r.step,fmt(r.input),fmt(r.returned),fmt(r.produced_total),fmt(r.focus),fmt(data.secondary_loop.rows[i].input),fmt(data.secondary_loop.rows[i].produced_total)])));
  }
  async function recalculate(){if(!config)return;const id=++seq;const data=await api('/api/cloth/calculate',collect());if(id!==seq)return;config=data.config;render(data);$('cloth-save-state').textContent='Есть несохранённые изменения';}
  async function save(){if(!config)return;const id=++seq;const data=await api('/api/cloth/save',collect());if(id===seq){config=data.config;render(data);$('cloth-save-state').textContent='Сохранено на этом компьютере';}return data;}
  async function open(){if(loaded)return;const data=await api('/api/cloth');config=data.config;
    for(const k of fields)$('cloth-'+k).value=config[k];
    for(let t=4;t<=8;t++){
      const label=el('label',`T${t}`),input=el('input');input.type='number';input.min='0';input.max='100';input.value=config.levels[t];input.dataset.clothLevel=t;input.onchange=()=>recalculate().catch(showError);label.append(input);$('cloth-levels').append(label);
      const button=el('button',`Тир ${t}`,t===tier?'active':'');button.onclick=()=>{tier=t;for(const b of $('cloth-tiers').children)b.classList.toggle('active',b===button);recalculate().catch(showError);};$('cloth-tiers').append(button);
    }
    render(data);loaded=true;
  }
  for(const k of fields)$('cloth-'+k).onchange=()=>recalculate().catch(showError);
  $('cloth-save').onclick=()=>save().catch(showError);
  $('cloth-export').onclick=async()=>{try{await save();location.href='/api/cloth/export.xlsx';}catch(e){showError(e);}};
  return {open};
}
