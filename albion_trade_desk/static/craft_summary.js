const labels={1:'Обычное',2:'Хорошее',3:'Выдающееся',4:'Отличное',5:'Шедевр'};
export function signed(value,fmt){return value==null?'—':(value>0?'+':'')+fmt(Math.round(value));}
export function profitRange(overview,fmt,model='no_focus',unit=true){
  const m=overview?.models[model],a=m?.[unit?'unit_profit_min':'profit_min'],b=m?.[unit?'unit_profit_max':'profit_max'];
  if(a==null)return 'Нужны цены';
  return Math.round(a)===Math.round(b)?signed(a,fmt):`${signed(a,fmt)} … ${signed(b,fmt)}`;
}
export function salesText(overview,fmt){return overview?.known_sales==null?'Нет истории':`${overview.sales_complete?'':'≥ '}${fmt(overview.known_sales)}`;}
export function qualitySummary(frames,{el,fmt,model='no_focus'}){
  const grid=el('div',null,'craft-frame-grid');
  for(const frame of frames||[]){
    const tile=el('div',null,`craft-frame q${frame.quality}${frame.quality===5?' masterpiece':''}`);tile.dataset.quality=frame.quality;
    tile.append(el('strong',labels[frame.quality]));
    if(!frame.applicable){tile.append(el('small','Не используется'));grid.append(tile);continue;}
    tile.append(el('span',frame.price==null?'Нет цены':fmt(Math.round(frame.price)),'frame-price'));
    const profit=frame.models[model].unit_profit;
    tile.append(el('span',profit==null?'Нет расчёта':signed(profit,fmt)+' / шт.',profit==null?'muted':profit<0?'loss':'gain'));
    const l=frame.liquidity;
    tile.append(el('small',l.known_sales==null?'Нет истории':`${l.complete?'':'≥ '}${fmt(l.known_sales)} продано`));
    tile.title=`${labels[frame.quality]} · продажи за 7 дней\n`+(l.known_sales==null?'История не получена':l.point_count!=null?`${l.point_count} исходных точек; полнота не подтверждена`:`Покрытие ${l.known_hours}/168 часов`);
    grid.append(tile);
  }
  return grid;
}
