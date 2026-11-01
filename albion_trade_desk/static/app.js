import {createCloth} from './cloth.js';
import {createMarketView} from './market_view.js';
import {createCrafting} from './crafting.js';
const $ = id => document.getElementById(id);
let crafting = null;
let marketView = null;
let marketNames = {};
let cardLayout = true;
const fmt = value => value == null ? '—' : new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(value);
const date = value => value ? new Date(value * 1000).toLocaleString('ru-RU') : 'нет данных';
const state = {offset: 0, limit: 50, rows: [], selected: new Set(), sort: 'name', direction: 'asc', total: 0, catalog: null, busy: false, activeJob: null, privateEnabled: false};
const keys = ['server', 'city', 'quality', 'tier', 'enchantment', 'category', 'scope', 'search', 'max_age_hours', 'favorites', 'priced'];
let loadSequence = 0;
function filters() {
  return Object.fromEntries(keys.map(k => [k, $(k).type === 'checkbox' ? String($(k).checked) : $(k).value]));
}
function params() { return new URLSearchParams({...filters(), sort: state.sort, direction: state.direction}); }
function notice(message, error = false) { $('notice').textContent = message; $('notice').className = error ? 'error' : ''; $('notice').hidden = false; $('error-details').hidden = true; }
function showError(error) {
  const offline = error instanceof TypeError;
  notice(offline ? 'Приложение не отвечает. Проверьте, что его тёмное окно Windows открыто, затем обновите страницу.' : error.message, true);
  if (error.detail || offline) { $('error-details').hidden = false; $('error-text').textContent = error.detail || error.message; }
}
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
function priceCell(tr, quote, className) {
  const td = cell(tr, quote ? fmt(quote.price) : 'Нет цены', quote ? (quote.fresh ? className : 'stale') : 'no-data', quote ? `Источник: ${quote.source}\nНаблюдение: ${date(quote.observed_at)}\nПолучено: ${date(quote.received_at)}\nОграничение: ${quote.limitation}` : 'Цена ещё не получена или источник её не знает');
  if (quote) {td.append(el('b',` · ${quote.quality===5?'★ Шедевр':quote.quality+' рамка'}`,quote.quality===5?'masterpiece':'quality-caption'));td.append(el('small', quote.source === 'private-client' ? 'Моё наблюдение' : quote.source === 'data-client' ? 'Старое локальное' : 'Общие данные', 'price-origin'));}
  return td;
}
function advancedCell(tr, text, className = '', title) { return cell(tr, text, `advanced-column ${className}`, title); }
function renderRows() {
  $('rows').replaceChildren();
  for (const item of state.rows) {
    const tr = el('tr');
    tr.classList.toggle('selected', state.selected.has(item.id));
    const select = el('input'); select.type = 'checkbox'; select.checked = state.selected.has(item.id); select.setAttribute('aria-label', `Выбрать ${item.name_ru}`);
    select.onchange = () => { select.checked ? state.selected.add(item.id) : state.selected.delete(item.id); tr.classList.toggle('selected', select.checked); updateSelected(); };
    cell(tr).append(select);
    const name = el('div', null, 'item-name');
    const star = el('button', item.favorite ? '★' : '☆', `favorite ${item.favorite ? 'enabled' : ''}`); star.setAttribute('aria-label', 'Добавить или убрать из избранного');
    star.onclick = async () => { try { await api('/api/favorites', {id: item.id, enabled: !item.favorite}); await load(); } catch (e) { notice(e.message, true); } };
    const icon = el('span', item.tier || '·', 'tier-icon');
    const names = el('div'); const open = el('button', $('language').value === 'en' ? item.name_en : item.name_ru, 'item-open');
    open.onclick = () => openItem(item); names.append(open, el('small', item.id, 'item-id')); name.append(star, icon, names); cell(tr).append(name);
    cell(tr, `${item.tier || '—'}.${item.enchantment}`);
    const sell = item.quotes.sell_price_min, buy = item.quotes.buy_price_max;
    if (item.location === '3003') cell(tr, 'Не применяется', 'no-data', 'Black Market покупает предметы: смотрите заявку покупателя'); else priceCell(tr, sell);
    priceCell(tr, buy, 'buy-price'); advancedCell(tr, item.spread_pct == null ? '—' : `${fmt(item.spread_pct)}%`);
    for (const key of ['1h', '24h', '7d']) advancedCell(tr, volume(item.volumes[key]), item.volumes[key].coverage < 1 ? 'partial' : '', volumeTitle(item.volumes[key]));
    advancedCell(tr, fmt(item.vwap), '', 'Историческая средневзвешенная цена доступных часов 7D, не ордер');
    const qs = Object.values(item.quotes); const age = qs.length ? Math.max(...qs.map(q => q.age_seconds)) : null;
    cell(tr, age == null ? 'Не получена' : age < 3600 ? `${Math.floor(age / 60)} мин назад` : `${fmt(age / 3600)} ч назад`, qs.some(q => !q.fresh) ? 'stale' : 'muted');
    const signal = advancedCell(tr);
    if (item.anomaly) signal.append(el('span', 'Аномалия', 'signal'));
    else if (qs.some(q => q.source === 'private-client')) signal.append(el('span', 'Свои · частичный', 'signal'));
    else if (qs.some(q => q.source === 'data-client')) signal.append(el('span', 'Старый скан', 'signal'));
    else signal.append(el('span', '—', 'no-data'));
    const fetchPrice = el('button', $('scope').value === 'private' ? 'Свои данные' : 'Узнать цену', 'row-refresh');
    fetchPrice.disabled = state.busy || $('scope').value === 'private';
    fetchPrice.setAttribute('aria-label', `Узнать цену: ${item.name_ru}`);
    fetchPrice.onclick = async () => { try { await refresh([item.id]); } catch (error) { showError(error); } };
    const actions=el('div',null,'item-actions');actions.append(fetchPrice);
    if (item.has_recipe) {
      const pack=el('button','В набор для крафта','quiet');
      pack.onclick=()=>{showView('craft',true);crafting.openItem(item.id,['auto','all'].includes($('quality').value)?'auto':Number($('quality').value)).catch(showError);};
      actions.append(pack);
    }
    cell(tr).append(actions);
    $('rows').append(tr);
  }
  renderCards();
  $('empty').hidden = state.rows.length > 0; $('total-badge').textContent = fmt(state.total);
  $('page-info').textContent = state.total ? `${state.offset + 1}–${Math.min(state.offset + state.limit, state.total)} из ${fmt(state.total)} предметов` : '0 предметов';
  $('page-number').textContent = Math.floor(state.offset / state.limit) + 1;
  $('prev').disabled = state.offset === 0; $('next').disabled = state.offset + state.limit >= state.total;
  $('market-label').textContent = $('city').selectedOptions[0]?.textContent || '';
  updateSelected();
}
function updateSelected() {
  const own = $('scope').value === 'private';
  $('refresh').textContent = own ? 'Показаны мои наблюдения' : state.selected.size ? `Загрузить цены выбранных (${state.selected.size})` : 'Загрузить цены выбранных';
  $('refresh').disabled = state.busy || !state.selected.size || state.selected.size > 100 || own;
  $('select-all').checked = state.rows.length > 0 && state.rows.every(r => state.selected.has(r.id));
  $('selection-hint').textContent = state.selected.size ? `Выбрано: ${state.selected.size}. Кнопка загрузки находится под таблицей.` : 'Для одного предмета нажмите «Узнать цену» в его строке.';
  renderOnboarding();
}
function renderOnboarding() {
  const ready = state.catalog > 0;
  $('market-workspace').hidden = !ready;
  $('setup-sync').hidden = ready;
  $('example-bag').hidden = !ready; $('example-crystal').hidden = !ready;
  for (const id of ['setup-sync', 'sync-catalog', 'help-sync']) { $(id).disabled = state.busy; }
  $('setup-sync').textContent = state.busy ? 'Загружаем список…' : 'Загрузить список предметов';
  $('job-progress').hidden = !state.busy;
  const hasPrice = state.rows.some(r => Object.keys(r.quotes).length > 0);
  const hasTarget = ready && (state.rows.length === 1 || state.selected.size > 0);
  const own = $('scope').value === 'private';
  $('onboarding').classList.toggle('ready', ready);
  $('onboarding-label').textContent = !ready ? 'Первый запуск · шаг 1 из 3' : own ? 'Ваши наблюдения' : hasPrice ? 'Данные доступны' : hasTarget ? 'Осталось загрузить цены · шаг 3 из 3' : 'Список готов · шаг 2 из 3';
  $('onboarding-title').textContent = !ready ? 'Начните локальный сбор или загрузите каталог' : hasPrice ? 'Теперь можно сравнивать цены' : own ? 'Собственные цены поступают из Data Client' : hasTarget ? 'Предмет найден. Теперь узнайте цену' : 'Начнём с одного знакомого предмета';
  $('onboarding-text').textContent = !ready ? 'Локальный сбор работает без каталога и Интернета. Для русских названий и рецептов можно отдельно разрешить публичные загрузки в разделе «Источники».' : hasPrice ? 'Нажмите название предмета для сравнения городов. Обращайте внимание на давность и источник: цена может устареть.' : own ? 'Сейчас выбраны только ваши данные. Для их получения проверьте подключение в «Мои наблюдения». Общие цены можно показать отдельно кнопкой ниже.' : hasTarget ? 'Проверьте город и качество. Нажмите «Узнать цену» справа в строке предмета. Галочка нужна только для загрузки нескольких предметов сразу.' : `В списке ${fmt(state.catalog)} предметов. Найдите свой через поиск ниже или нажмите пример. Затем выберите город и нажмите «Узнать цену» в строке предмета.`;
  $('step-prices').querySelector('strong').textContent = own ? 'Получить свои наблюдения' : 'Нажать «Узнать цену»';
  $('step-prices').querySelector('small').textContent = own ? 'Через настроенный Data Client' : 'Прямо в строке нужного предмета';
  for (const [id, done, current] of [['step-catalog', ready, !ready], ['step-search', hasTarget, ready && !hasTarget], ['step-prices', hasPrice, hasTarget]]) {
    $(id).classList.toggle('done', Boolean(done)); $(id).classList.toggle('current', Boolean(current && !done));
  }
  $('private-filter-note').hidden = $('scope').value !== 'private';
  const applied = Number(Boolean($('category').value)) + Number($('favorites').checked) + Number($('priced').checked);
  $('filters-summary').textContent = applied ? `Дополнительные фильтры · применено ${applied}` : 'Дополнительные фильтры';
}
async function load() {
  const sequence = ++loadSequence;
  const data = await api(`/api/market?${params()}&offset=${state.offset}&limit=${state.limit}`);
  if (sequence !== loadSequence) return;
  state.rows = data.rows; state.total = data.total; renderRows();
  localStorage.setItem('albion-filters', JSON.stringify(filters()));
}
async function status() {
  const data = await api('/api/status');
  $('app-version').textContent = `Версия ${data.version}`;
  state.catalog = data.items;marketNames=data.markets;
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
  $('public-api-enabled').checked = data.public_api_enabled;
  renderPrivate(data.private_scanner);
  const nats = data.public_nats;
  const natsNames = {disabled: 'Выключен', connecting: 'Подключение…', connected: 'Подключён', error: 'Нет подключения'};
  $('nats-state').textContent = `${natsNames[nats.status] || nats.status} · ${nats.server || 'сервер не выбран'} · принято записей: ${nats.records} · отклонено: ${nats.rejected}${nats.error ? ' · ' + nats.error : ''}`;
  $('saved-filters').replaceChildren(new Option('Выберите профиль', ''));
  for (const [name, f] of Object.entries(data.filters)) { const option = new Option(name, name); option.dataset.filters = JSON.stringify(f); $('saved-filters').add(option); }
  renderOnboarding();
  crafting?.updateContext(data);
  if (data.active_job && !state.activeJob) trackJob(data.active_job).catch(showError);
  return data;
}
function renderPrivate(p) {
  state.privateEnabled = p.enabled || p.process?.active;
  const names = {disabled: 'Выключен', starting: 'Запускается · ожидается Windows', waiting: 'Ожидание рыночных данных', receiving: 'Работает · получены данные', error: 'Ошибка'};
  $('private-state').textContent = `${names[p.state || p.connection]}${p.server ? ' · ' + p.server.toUpperCase() : ''}`;
  $('private-counts').textContent = `Ордеров обработано: ${p.orders_processed || 0} · уникальных на сервере: ${p.unique_orders || 0}. В сессии: ${p.packets || 0} пакетов · ${p.records || 0} записей с обновлениями · ${p.duplicates || 0} повторных пакетов · ${p.rejected || 0} отклонено. В базе: ${p.own_orders} своих заявок, ${p.own_native_history} точек истории; без названия: ${p.unmapped_history}.`;
  $('private-db').textContent = `База: ${p.db_path} · ${(p.db_bytes / 1048576).toFixed(2)} МБ`;
  $('private-region').textContent = `Сервер сессии: ${(p.server || $('server').value).toUpperCase()}. Сервер игры: ${p.detected_server || 'не передаётся в HTTP AOD; проверьте в окне клиента'}`;
  $('server').disabled = state.busy || p.enabled || p.process?.active;
  $('private-error').textContent = p.last_error || '';
  $('private-start').disabled = p.enabled || p.process?.active;
  $('private-last').textContent = `Последний пакет: ${date(p.last_received_at)}${p.last_topic ? ' · ' + p.last_topic : ''}`;
  $('private-launcher').disabled = !p.enabled; $('private-start').disabled = p.enabled || p.process?.active; $('private-stop').disabled = !p.enabled && !p.process?.active;
  $('private-filter-text').textContent = p.enabled ? 'Приёмник включён. Свои цены появятся после получения сообщений от правильно запущенного Data Client. Открытие рынка в игре само по себе не подключает его.' : 'Приватный приёмник выключен. Настройка собственных наблюдений находится в разделе «Мои наблюдения».';
}
function setBusy(busy) {
  state.busy = busy;
  for (const input of document.querySelectorAll('#filters input, #filters select, #server, #select-all, #rows input[type=checkbox]')) input.disabled = busy;
  for (const button of document.querySelectorAll('.row-refresh')) button.disabled = busy || $('scope').value === 'private';
  $('server').disabled = busy || state.privateEnabled;
  updateSelected();
}
async function trackJob(started) {
  if (state.activeJob === started.id) return;
  state.activeJob = started.id; setBusy(true);
  const catalog = started.kind === 'catalog';
  $('job-progress').textContent = catalog ? 'Загружаем список предметов и рецепты. При первом запуске это может занять несколько минут.' : 'Запрашиваем общие цены и доступную историю. Ваши наблюдения при этом не публикуются.';
  notice(catalog ? 'Загрузка списка началась. Дождитесь её окончания — больше ничего нажимать не нужно.' : 'Получаем общие цены. Дождитесь окончания запроса.');
  try {
    let result;
    do { await new Promise(resolve => setTimeout(resolve, 800)); result = await api(`/api/jobs/${started.id}`); } while (['queued', 'running'].includes(result.status));
    await status(); await load();
    if (!$('craft-view').hidden) await crafting?.refresh();
    if (result.status !== 'done') {
      const error = new Error(catalog ? 'Не удалось загрузить список предметов. Проверьте подключение к Интернету и повторите загрузку. Точный текст ошибки можно раскрыть ниже.' : 'Не удалось завершить загрузку цен. Уже полученные данные сохранены. Проверьте Интернет; точный текст ошибки можно раскрыть ниже.');
      error.detail = result.error || result.status; throw error;
    }
    if (catalog) notice(`Список готов: ${fmt(result.result.items)} предметов. Теперь выберите пример или введите название в поиск ниже.`);
    else if(started.kind==='history') notice(result.result.history?`Получено исторических интервалов: ${fmt(result.result.history)}. График обновлён.`:'За выбранный период источник не сообщил историю. Пропуски не означают нулевые продажи.');
    else notice(result.result.prices ? `Получено ценовых наблюдений: ${fmt(result.result.prices)}. Исторических интервалов: ${fmt(result.result.history)}. ${started.kind==='craft'?'Цены набора обновлены в списке материалов.':'Цены показаны в таблице.'}` : 'Запрос выполнен, но источник пока не сообщил цен для выбранных условий. Попробуйте другой город или качество. «Нет цены» не означает нулевую стоимость.');
  } finally { state.activeJob = null; setBusy(false); }
}
async function job(path, body) {
  if (state.busy) throw new Error('Обновление уже идёт. Дождитесь его завершения.');
  setBusy(true);
  try { const started = await api(path, body); await trackJob(started); }
  finally { if (!state.activeJob) setBusy(false); }
}
async function refresh(items = [...state.selected]) {
  if (!state.catalog) { notice('Сначала загрузите список предметов большой кнопкой на этой странице.'); return; }
  if ($('scope').value === 'private') { notice('Сейчас показаны только ваши наблюдения. Для них проверьте подключение в «Мои наблюдения». Общие цены можно выбрать отдельно.'); return; }
  if (!items.length) { notice('Нажмите «Узнать цену» в строке предмета. Для нескольких предметов отметьте галочки в первом столбце.'); return; }
  if (items.length > 100) throw new Error('За один раз можно загрузить цены не более чем для 100 предметов.');
  await job('/api/market/refresh', {items, server: $('server').value, cities: [$('city').value], qualities: ['all','auto'].includes($('quality').value)?[1,2,3,4,5]:[Number($('quality').value)]});
}
function bind(id, action) { $(id).addEventListener('click', async () => { try { await action(); } catch (error) { showError(error); } }); }
function showView(name,skipCraft=false) {
  for (const view of document.querySelectorAll('.view')) view.hidden = view.id !== `${name}-view`;
  for (const nav of document.querySelectorAll('.nav')) nav.classList.toggle('active', nav.dataset.view === name);
  const nav = document.querySelector(`[data-view="${name}"]`);
  $('breadcrumb').textContent = nav?.textContent.trim() || name;
  if (nav?.closest('.nav-more')) $('nav-more').open = true;
  $('notice').hidden = true; $('error-details').hidden = true;
  status().catch(showError);
  if (name==='craft'&&!skipCraft) crafting?.open().catch(showError);
  if (name==='cloth') cloth.open().catch(showError);
  if (name==='market') load().catch(showError); // A saved pack may have selected another server.
}
for (const button of document.querySelectorAll('[data-view]')) button.onclick = () => showView(button.dataset.view);
for (const key of keys.filter(k => k !== 'search')) $(key).addEventListener('change', async () => { state.offset = 0; state.selected.clear(); try { await load(); } catch (e) { showError(e); } });
let debounce; $('search').addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(() => { state.offset = 0; state.selected.clear(); load().catch(e => notice(e.message, true)); }, 220); });
$('filters').onsubmit = e => e.preventDefault();
$('language').onchange = () => { localStorage.setItem('albion-language', $('language').value); renderRows(); };
for (const button of document.querySelectorAll('[data-sort]')) button.onclick = () => { state.direction = state.sort === button.dataset.sort && state.direction === 'asc' ? 'desc' : 'asc'; state.sort = button.dataset.sort; state.offset = 0; load().catch(e => notice(e.message, true)); };
$('select-all').onchange = () => { for (const r of state.rows) $('select-all').checked ? state.selected.add(r.id) : state.selected.delete(r.id); renderRows(); };
bind('prev', () => { state.offset = Math.max(0, state.offset - state.limit); return load(); }); bind('next', () => { state.offset += state.limit; return load(); });
bind('refresh', () => refresh()); bind('sources-refresh', () => { showView('market'); return refresh(); });
bind('private-start', async () => {
  if (!$('private-ack').checked) throw new Error('Сначала прочитайте предупреждение и отметьте согласие на экспериментальный режим.');
  await api('/api/private/launch', {server: $('server').value, experimental_ack: true});
  $('scope').value = 'private'; state.offset = 0; await status(); await load();
  notice('Ожидайте запрос Windows. При первом запуске выберите установленный AOD 0.1.61. Затем откройте рынок в игре.');
});
bind('private-stop', async () => { await api('/api/private/stop', {}); $('private-ack').checked = false; await status(); notice('Запрошена остановка своего AOD и приёмника. Чужие процессы не завершаются.'); });
bind('setup-private', () => showView('private'));
bind('app-stop', async () => { await api('/api/app/stop',{}); notice('Trade Desk остановлен. Можно закрыть эту вкладку.'); });
bind('private-logs-refresh', async () => { const r=await api('/api/private/logs'); $('private-logs').textContent=r.lines.join('\n') || 'Журнал пока пуст'; });
bind('private-orders-export', () => { location.href='/api/private/orders.xlsx?server='+encodeURIComponent($('server').value); });
$('public-api-enabled').onchange=async () => { try { await api('/api/settings/public-api',{enabled:$('public-api-enabled').checked}); await status(); } catch(e) {showError(e);} };
bind('private-launcher', () => { location.href = '/api/private/launcher'; });
bind('nats-start', async () => { await api('/api/nats/start', {server: $('server').value}); await status(); });
bind('nats-stop', async () => { await api('/api/nats/stop', {}); await status(); });
for (const id of ['sync-catalog', 'setup-sync', 'help-sync']) bind(id, () => { showView('market'); return job('/api/catalog/sync', {}); });
function resetFilters() {
  for (const key of ['search', 'tier', 'enchantment', 'category']) $(key).value = '';
  $('favorites').checked = false; $('priced').checked = false; state.offset = 0; state.selected.clear();
  return load();
}
async function example(name) {
  showView('market');
  if (!state.catalog) { notice('Сначала загрузите список предметов. Кнопка находится прямо на этой странице.'); return; }
  $('search').value = name; $('tier').value = '4'; $('enchantment').value = '0'; $('category').value = '';
  $('quality').value = '1';
  $('favorites').checked = false; $('priced').checked = false;
  $('extra-filters').open = false; state.offset = 0; state.selected.clear();
  await load(); $('search').focus();
}
bind('example-bag', () => example('Сумка (знаток)'));
for (const id of ['example-crystal', 'help-crystal']) bind(id, () => example('Кристалл разлома (знаток)'));
for (const id of ['market-help', 'sidebar-help']) bind(id, () => showView('help'));
for (const id of ['open-my-feed', 'help-my-feed']) bind(id, () => showView('private'));
for (const id of ['reset-filters', 'empty-sync']) bind(id, resetFilters);
bind('show-public', () => { $('scope').value = 'public'; state.offset = 0; state.selected.clear(); return load(); });
bind('table-details', () => { const on = $('market-table').classList.toggle('show-metrics'); $('table-details').textContent = on ? 'Простая таблица' : 'Подробная таблица'; $('table-details').setAttribute('aria-pressed', String(on)); });
for (const type of ['csv', 'xlsx']) bind(`export-${type}`, () => { location.href = `/api/export.${type}?${params()}`; });
bind('backup', () => { location.href = '/api/backup'; });
bind('save-filter', () => { $('profile-dialog').showModal(); $('profile-name').focus(); });
bind('cancel-profile', () => $('profile-dialog').close());
$('profile-form').onsubmit = async e => { e.preventDefault(); try { await api('/api/filters', {name: $('profile-name').value, filters: filters()}); $('profile-dialog').close(); await status(); notice('Профиль сохранён.'); } catch (error) { notice(error.message, true); } };
$('saved-filters').onchange = async () => { const data = $('saved-filters').selectedOptions[0]?.dataset.filters; if (!data) return; applyFilters(JSON.parse(data)); state.offset = 0; state.selected.clear(); try { await load(); } catch (e) { notice(e.message, true); } };
function applyFilters(values) { for (const k of keys) if (k in values) { if ($(k).type === 'checkbox') $(k).checked = values[k] === 'true'; else $(k).value = values[k]; } }
bind('import-button', async () => { const file = $('import-file').files[0]; if (!file) throw new Error('Выберите JSON-файл'); if (file.size > 15 * 1024 * 1024) throw new Error('Файл слишком большой: максимум 15 МБ'); const data = JSON.parse(await file.text()); const result = await api('/api/import', {kind: $('import-kind').value, data, server: $('server').value}); notice(`Импортировано записей: ${result.imported}`); await status(); await load(); });
function openItem(item){marketView.open(item).catch(showError);}
function renderCards(){
  const wrap=$('market-cards');wrap.replaceChildren();
  for(const item of state.rows){
    const card=el('article',null,'market-card'+(state.selected.has(item.id)?' selected':'')),head=el('div',null,'market-card-heading');
    const select=el('input');select.type='checkbox';select.checked=state.selected.has(item.id);select.setAttribute('aria-label','Выбрать '+item.name_ru);
    select.onchange=()=>{select.checked?state.selected.add(item.id):state.selected.delete(item.id);card.classList.toggle('selected',select.checked);updateSelected();};
    const open=el('button',$('language').value==='en'?item.name_en:item.name_ru,'card-name');open.onclick=()=>openItem(item);
    const star=el('button',item.favorite?'★':'☆','favorite');star.setAttribute('aria-label','Добавить или убрать из избранного');star.onclick=async()=>{try{await api('/api/favorites',{id:item.id,enabled:!item.favorite});await load();}catch(e){showError(e);}};
    head.append(select,star,open,el('strong',`${item.tier}.${item.enchantment}`,'tier-pill'));card.append(head,marketView.qualityGrid(item.by_quality));
    const actions=el('div',null,'card-actions'),refresh=el('button','Узнать цены','row-refresh');refresh.disabled=state.busy||$('scope').value==='private';refresh.onclick=()=>refreshCard(item.id);
    const details=el('button','График и города','secondary');details.onclick=()=>openItem(item);actions.append(refresh,details);
    if(item.has_recipe){const b=el('button','Набор для крафта','quiet');b.onclick=()=>{showView('craft',true);crafting.openItem(item.id,$('quality').value).catch(showError);};actions.append(b);}
    card.append(actions);wrap.append(card);
  }
}
async function refreshCard(id){try{await refresh([id]);}catch(e){showError(e);}}
function layout(cards){cardLayout=cards;$('market-cards').hidden=!cards;$('market-table-wrap').hidden=cards;
  for(const [id,on] of [['layout-cards',cards],['layout-table',!cards]]){$(id).classList.toggle('active',on);$(id).setAttribute('aria-pressed',String(on));}if(state.rows.length)renderRows();}
bind('layout-cards',()=>layout(true));bind('layout-table',()=>layout(false));
bind('close-dialog', () => $('item-dialog').close());
async function init() {
  await status();
  try { const saved = localStorage.getItem('albion-filters'); if (saved) applyFilters(JSON.parse(saved)); $('language').value = localStorage.getItem('albion-language') || 'ru'; }
  catch { /* Ignore malformed browser preferences; network/data errors are displayed. */ }
  if ($('category').value || $('favorites').checked || $('priced').checked) $('extra-filters').open = true;
  await load();
}
crafting=createCrafting({api,fmt,date,el,notice,showError,job,showView,catalog:()=>state.catalog,
  initialCity:()=>$('city').value,initialScope:()=>$('scope').value,maxAge:()=>$('max_age_hours').value});
marketView=createMarketView({api,el,fmt,notice,showError,job,filters,markets:()=>marketNames,craft:(id,q)=>{showView('craft',true);crafting.openItem(id,q).catch(showError);}});
const cloth=createCloth({api,el,fmt,notice,showError});
init().catch(showError);
setInterval(async () => {
  if (document.hidden || state.polling) return;
  const watchingFeed = !$('private-view').hidden || !$('sources-view').hidden;
  if (!state.privateEnabled && !watchingFeed) return;
  state.polling = true;
  try {
    if (watchingFeed) await status();
    else {
      const p = await api('/api/private/status'); renderPrivate(p);
      if (!$('market-view').hidden && !state.busy && p.last_received_at !== state.lastReceived) {
        await load(); await marketView.refresh(); state.lastReceived = p.last_received_at;
      }
    }
  } catch (e) { showError(e); }
  finally { state.polling = false; }
}, 5000);
