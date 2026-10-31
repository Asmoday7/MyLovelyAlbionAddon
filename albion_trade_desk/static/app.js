const $ = id => document.getElementById(id);
const fmt = value => value == null ? '—' : new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(value);
const date = value => value ? new Date(value * 1000).toLocaleString('ru-RU') : 'нет данных';
const state = {offset: 0, limit: 50, rows: [], selected: new Set(), sort: 'name', direction: 'asc', total: 0};
const keys = ['server', 'city', 'quality', 'tier', 'enchantment', 'category', 'scope', 'search', 'max_age_hours', 'favorites', 'priced'];
let loadSequence = 0;
function filters() {
  return Object.fromEntries(keys.map(k => [k, $(k).type === 'checkbox' ? String($(k).checked) : $(k).value]));
}
function params() { return new URLSearchParams({...filters(), sort: state.sort, direction: state.direction}); }
function notice(message, error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; $('notice').hidden = false; }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function el(tag, text, className) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; }
function cell(row, text, className, title) { const td = el('td', text, className); if (title) td.title = title; row.append(td); return td; }
function volume(point) { return point.volume != null ? fmt(point.volume) : point.known_quantity == null ? '—' : `≥ ${fmt(point.known_quantity)}`; }
function volumeTitle(point) { return `Покрытие: ${point.known_hours}/${point.expected_hours} часов (${fmt(point.coverage * 100)}%). ${date(point.start)} — ${date(point.end)}. Не точное скользящее окно.`; }
function priceCell(tr, quote, className) { return cell(tr, fmt(quote?.price), quote ? (quote.fresh ? className : 'stale') : 'no-data', quote ? `Источник: ${quote.source}\nНаблюдение: ${date(quote.observed_at)}\nПолучено: ${date(quote.received_at)}\nОграничение: ${quote.limitation}` : 'Нет наблюдения'); }
function renderRows() {
  $('rows').replaceChildren();
  for (const item of state.rows) {
    const tr = el('tr');
    const select = el('input'); select.type = 'checkbox'; select.checked = state.selected.has(item.id); select.setAttribute('aria-label', `Выбрать ${item.name_ru}`);
    select.onchange = () => { select.checked ? state.selected.add(item.id) : state.selected.delete(item.id); updateSelected(); };
    cell(tr).append(select);
    const name = el('div', null, 'item-name');
    const star = el('button', item.favorite ? '★' : '☆', `favorite ${item.favorite ? 'enabled' : ''}`); star.setAttribute('aria-label', 'Добавить или убрать из избранного');
    star.onclick = async () => { try { await api('/api/favorites', {id: item.id, enabled: !item.favorite}); await load(); } catch (e) { notice(e.message, true); } };
    const icon = el('span', item.tier || '·', 'tier-icon');
    const names = el('div'); const open = el('button', $('language').value === 'en' ? item.name_en : item.name_ru, 'item-open');
    open.onclick = () => openItem(item); names.append(open, el('small', item.id, 'item-id')); name.append(star, icon, names); cell(tr).append(name);
    cell(tr, `${item.tier || '—'}.${item.enchantment}`);
    const sell = item.quotes.sell_price_min, buy = item.quotes.buy_price_max;
    priceCell(tr, sell); priceCell(tr, buy, 'buy-price'); cell(tr, item.spread_pct == null ? '—' : `${fmt(item.spread_pct)}%`);
    for (const key of ['1h', '24h', '7d']) cell(tr, volume(item.volumes[key]), item.volumes[key].coverage < 1 ? 'partial' : '', volumeTitle(item.volumes[key]));
    cell(tr, fmt(item.vwap), null, 'Историческая средневзвешенная цена доступных часов 7D, не ордер');
    const qs = Object.values(item.quotes); const age = qs.length ? Math.max(...qs.map(q => q.age_seconds)) : null;
    cell(tr, age == null ? '—' : age < 3600 ? `${Math.floor(age / 60)} мин` : `${fmt(age / 3600)} ч`, qs.some(q => !q.fresh) ? 'stale' : 'muted');
    const signal = cell(tr);
    if (item.anomaly) signal.append(el('span', 'Аномалия', 'signal'));
    else if (qs.some(q => q.source === 'private-client')) signal.append(el('span', 'Свои · частичный', 'signal'));
    else if (qs.some(q => q.source === 'data-client')) signal.append(el('span', 'Старый скан', 'signal'));
    else signal.append(el('span', '—', 'no-data'));
    $('rows').append(tr);
  }
  $('empty').hidden = state.rows.length > 0; $('total-badge').textContent = fmt(state.total);
  $('page-info').textContent = state.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, state.total)} из ${fmt(state.total)} предметов` : '0 предметов';
  $('page-number').textContent = Math.floor(state.offset / state.limit) + 1;
  $('prev').disabled = state.offset === 0; $('next').disabled = state.offset + state.limit >= state.total;
  $('market-label').textContent = $('city').selectedOptions[0]?.textContent || '';
  updateSelected();
}
function updateSelected() { $('refresh').textContent = `↻ Обновить выбранные (${state.selected.size})`; $('select-all').checked = state.rows.length > 0 && state.rows.every(r => state.selected.has(r.id)); }
async function load() {
  const sequence = ++loadSequence;
  const data = await api(`/api/market?${params()}&offset=${state.offset}&limit=${state.limit}`);
  if (sequence !== loadSequence) return;
  state.rows = data.rows; state.total = data.total; renderRows();
  localStorage.setItem('albion-filters', JSON.stringify(filters()));
}
async function status() {
  const data = await api('/api/status');
  $('item-count').textContent = fmt(data.items); $('quote-count').textContent = fmt(data.quotes); $('history-count').textContent = fmt(data.history);
  if (!$('city').options.length) {
    for (const [id, name] of Object.entries(data.markets)) $('city').add(new Option(name, id));
    $('city').value = '3005';
  }
  const old = $('category').value; $('category').replaceChildren(new Option('Все категории', ''));
  for (const c of data.categories.filter(Boolean)) $('category').add(new Option(c, c));
  $('category').value = old;
  $('catalog-date').textContent = `Последний импорт: ${date(data.catalog_at)}`;
  $('events').replaceChildren();
  for (const event of data.events) {
    const row = el('div', null, 'event'); row.append(el('span', `${event.server.toUpperCase()} · ${event.source} / ${event.kind} · ${fmt(event.count)} записей`), el('span', date(event.at))); $('events').append(row);
  }
  if (!data.events.length) $('events').append(el('p', 'Рыночных обновлений пока нет. Каталог не содержит цен.', 'muted'));
  renderPrivate(data.private_scanner);
  const nats = data.public_nats;
  $('nats-state').textContent = `${nats.status} · ${nats.server || 'сервер не выбран'} · принято записей: ${nats.records} · отклонено: ${nats.rejected}${nats.error ? ' · ' + nats.error : ''}`;
  $('saved-filters').replaceChildren(new Option('Выберите профиль', ''));
  for (const [name, f] of Object.entries(data.filters)) { const option = new Option(name, name); option.dataset.filters = JSON.stringify(f); $('saved-filters').add(option); }
}
function renderPrivate(p) {
  const names = {disabled: 'Выключен', waiting: 'Приёмник включён · ожидание пакетов', receiving: 'Недавно получены пакеты'};
  $('private-state').textContent = `${names[p.connection]}${p.server ? ' · ' + p.server.toUpperCase() : ''}`;
  $('private-counts').textContent = `В сессии: ${p.packets || 0} пакетов · ${p.records || 0} записей с обновлениями · ${p.duplicates || 0} повторных пакетов · ${p.rejected || 0} отклонено. В базе: ${p.own_orders} своих заявок, ${p.own_native_history} точек истории; без названия: ${p.unmapped_history}.`;
  $('private-last').textContent = `Последний пакет: ${date(p.last_received_at)}${p.last_topic ? ' · ' + p.last_topic : ''}`;
  $('private-launcher').disabled = !p.enabled; $('private-start').disabled = p.enabled; $('private-stop').disabled = !p.enabled;
}
async function job(path, body) {
  const started = await api(path, body); notice('Обновление запущено. Данные сохранятся в локальную базу.');
  let result;
  do { await new Promise(resolve => setTimeout(resolve, 800)); result = await api(`/api/jobs/${started.id}`); } while (['queued', 'running'].includes(result.status));
  if (result.status !== 'done') { await status(); await load(); throw new Error(`Обновление не завершено: ${result.error || result.status}. Уже полученные данные сохранены. Проверьте сеть и настройки доступа.`); }
  notice(`Обновление завершено: ${JSON.stringify(result.result)}`); await status(); await load();
}
async function refresh() {
  if (!state.selected.size) { notice('Отметьте предметы слева в таблице. Одно обновление — до 100 предметов.'); return; }
  await job('/api/market/refresh', {items: [...state.selected], server: $('server').value, cities: [$('city').value], qualities: [Number($('quality').value)]});
}
function bind(id, action) { $(id).addEventListener('click', async () => { try { await action(); } catch (error) { notice(error.message, true); } }); }
for (const button of document.querySelectorAll('[data-view]')) button.onclick = () => {
  for (const view of document.querySelectorAll('.view')) view.hidden = view.id !== `${button.dataset.view}-view`;
  for (const nav of document.querySelectorAll('.nav')) nav.classList.toggle('active', nav === button);
  $('breadcrumb').textContent = button.textContent.trim();
  status().catch(e => notice(e.message, true));
};
for (const key of keys.filter(k => k !== 'search')) $(key).addEventListener('change', async () => { state.offset = 0; state.selected.clear(); try { await load(); await status(); } catch (e) { notice(e.message, true); } });
let debounce; $('search').addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(() => { state.offset = 0; state.selected.clear(); load().catch(e => notice(e.message, true)); }, 220); });
$('filters').onsubmit = e => e.preventDefault();
$('language').onchange = () => { localStorage.setItem('albion-language', $('language').value); renderRows(); };
for (const button of document.querySelectorAll('[data-sort]')) button.onclick = () => { state.direction = state.sort === button.dataset.sort && state.direction === 'asc' ? 'desc' : 'asc'; state.sort = button.dataset.sort; state.offset = 0; load().catch(e => notice(e.message, true)); };
$('select-all').onchange = () => { for (const r of state.rows) $('select-all').checked ? state.selected.add(r.id) : state.selected.delete(r.id); renderRows(); };
bind('prev', () => { state.offset = Math.max(0, state.offset - state.limit); return load(); }); bind('next', () => { state.offset += state.limit; return load(); });
bind('refresh', refresh); bind('sources-refresh', refresh);
bind('private-start', async () => {
  if (!$('private-ack').checked) throw new Error('Сначала прочитайте предупреждение и отметьте согласие на экспериментальный режим.');
  await api('/api/private/start', {server: $('server').value, experimental_ack: true});
  $('scope').value = 'private'; state.offset = 0; await status(); await load();
  notice('Приватный приёмник включён. Сам клиент ещё не запущен; скачайте файл запуска Windows. Сетевая приватность ещё не подтверждена.');
});
bind('private-stop', async () => { await api('/api/private/stop', {}); $('private-ack').checked = false; await status(); notice('Приёмник остановлен. Файл запуска Windows должен остановить свой клиент при следующей проверке.'); });
bind('private-launcher', () => { location.href = '/api/private/launcher'; });
bind('nats-start', async () => { await api('/api/nats/start', {server: $('server').value}); await status(); });
bind('nats-stop', async () => { await api('/api/nats/stop', {}); await status(); });
for (const id of ['sync-catalog', 'empty-sync']) bind(id, () => job('/api/catalog/sync', {}));
for (const type of ['csv', 'xlsx']) bind(`export-${type}`, () => { location.href = `/api/export.${type}?${params()}`; });
bind('backup', () => { location.href = '/api/backup'; });
bind('save-filter', () => { $('profile-dialog').showModal(); $('profile-name').focus(); });
bind('cancel-profile', () => $('profile-dialog').close());
$('profile-form').onsubmit = async e => { e.preventDefault(); try { await api('/api/filters', {name: $('profile-name').value, filters: filters()}); $('profile-dialog').close(); await status(); notice('Профиль сохранён.'); } catch (error) { notice(error.message, true); } };
$('saved-filters').onchange = async () => { const data = $('saved-filters').selectedOptions[0]?.dataset.filters; if (!data) return; applyFilters(JSON.parse(data)); state.offset = 0; state.selected.clear(); try { await load(); } catch (e) { notice(e.message, true); } };
function applyFilters(values) { for (const k of keys) if (k in values) { if ($(k).type === 'checkbox') $(k).checked = values[k] === 'true'; else $(k).value = values[k]; } }
bind('import-button', async () => { const file = $('import-file').files[0]; if (!file) throw new Error('Выберите JSON-файл'); if (file.size > 15 * 1024 * 1024) throw new Error('Файл слишком большой: максимум 15 МБ'); const data = JSON.parse(await file.text()); const result = await api('/api/import', {kind: $('import-kind').value, data, server: $('server').value}); notice(`Импортировано записей: ${result.imported}`); await status(); await load(); });
async function openItem(item) {
  $('detail-title').textContent = $('language').value === 'en' ? item.name_en : item.name_ru;
  $('detail-id').textContent = `${item.id} · Q${item.quality} · ${item.server.toUpperCase()}`;
  $('detail-content').replaceChildren(el('p', 'Загрузка…', 'muted')); $('item-dialog').showModal();
  try {
    const data = await api(`/api/item?id=${encodeURIComponent(item.id)}&server=${item.server}&quality=${item.quality}&max_age_hours=${$('max_age_hours').value}&scope=${$('scope').value}`);
    $('detail-content').replaceChildren(); const table = el('table'); const head = el('tr');
    for (const name of ['Рынок', 'Sell min', 'Buy max', '1H', '24H', '7D']) head.append(el('th', name)); table.append(head);
    for (const row of data.markets) { const tr = el('tr'); cell(tr, $('city').querySelector(`option[value="${row.location}"]`)?.textContent || row.location); priceCell(tr, row.quotes.sell_price_min); priceCell(tr, row.quotes.buy_price_max, 'buy-price'); for (const key of ['1h', '24h', '7d']) cell(tr, volume(row.volumes[key]), 'partial', volumeTitle(row.volumes[key])); table.append(tr); }
    const wrap = el('div', null, 'table-scroll'); wrap.append(table); $('detail-content').append(wrap);
    $('detail-content').append(el('p', 'Глубина заявок неизвестна. Black Market использует только buy order. История показывает покрытие закрытых часов и ожидает живой проверки временных границ.', 'caveat'));
    $('detail-content').append(el('h2', `Рецептов в каталоге: ${data.recipes.length}`));
    for (const recipe of data.recipes) { const p = el('p', `Вариант ${recipe.variant + 1} · Выход: ${recipe.output} · Базовый Focus: ${fmt(recipe.focus)} · Серебро: ${fmt(recipe.silver)}`, 'muted'); const ul = el('ul'); for (const r of JSON.parse(recipe.resources)) ul.append(el('li', `${r.item_id} × ${r.count}${r.returnable ? '' : ' · без возврата'}`)); $('detail-content').append(p, ul); }
    $('detail-content').append(el('p', 'Производственная себестоимость, налоги, эффективность Focus и прибыль будут добавлены в Phase 3.', 'caveat'));
  } catch (error) { $('detail-content').replaceChildren(el('p', error.message)); }
}
bind('close-dialog', () => $('item-dialog').close());
async function init() { await status(); try { const saved = localStorage.getItem('albion-filters'); if (saved) applyFilters(JSON.parse(saved)); $('language').value = localStorage.getItem('albion-language') || 'ru'; } catch { /* Ignore an obsolete browser preference, not API errors. */ } await load(); await status(); }
init().catch(e => notice(e.message, true));
setInterval(async () => {
  if (document.hidden) return;
  try { const p = await api('/api/private/status'); renderPrivate(p); if (p.enabled && !$('market-view').hidden) await load(); if (!$('private-view').hidden || !$('sources-view').hidden) await status(); }
  catch (e) { notice(`Связь с локальным приложением потеряна: ${e.message}`, true); }
}, 5000);
