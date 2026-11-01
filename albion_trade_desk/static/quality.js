export const qualityNames={1:'Обычное',2:'Хорошее',3:'Выдающееся',4:'Отличное',5:'Шедевр'};
export function qualityGrid(rows,{el,fmt,bm=false,compact=false}) {
  const grid=el('div',null,'quality-grid'+(compact?' compact':''));
  for(const row of rows||[]) {
    const tile=el('div',null,`quality-tile q${row.quality}`);tile.dataset.quality=row.quality;
    tile.append(el('strong',qualityNames[row.quality]));
    for(const [kind,label] of [['sell_price_min','Продают'],['buy_price_max','Покупают']]) {
      if(bm&&kind==='sell_price_min')continue;
      const q=row.quotes[kind],line=el('div',null,'quality-price');
      line.append(el('span',label),el('b',q?fmt(q.price):'—',q&&!q.fresh?'stale':''));
      if(q)line.title=`${q.source} · ${new Date(q.observed_at*1000).toLocaleString('ru-RU')}\n${q.fresh?'Свежая цена':'Устарело / заявка истекла'}\nОбъём сделки не гарантирован`;
      if(q){const hours=q.age_seconds/3600;line.append(el('small',(hours<1?Math.floor(q.age_seconds/60)+' мин':Math.round(hours*10)/10+' ч')+' назад'+(!q.fresh?' · устарело':''),'quality-age'));}
      if(q&&['private-client','data-client'].includes(q.source)&&q.last_scan_at>q.observed_at+60){
        const minutes=Math.floor(q.last_scan_age_seconds/60);
        const scan=el('small',`Скан: ${minutes<60?minutes+' мин':Math.round(minutes/6)/10+' ч'} назад`,'quality-scan');
        scan.title='После наблюдения этой цены поступали новые заявки. Более дешёвая старая заявка сохранена: частичный просмотр рынка не подтверждает её исчезновение.';line.append(scan);
      }
      tile.append(line);
    }
    if(row.quality===5)tile.append(el('small','Отдельное качество'));
    grid.append(tile);
  }
  return grid;
}
