# Источники: подтверждения и ограничения

## Состояние проверки

Проверено 2026-10-31 в облачной среде. GitHub HTTPS работает с платформенной
аутентификацией. Реальный `formatted/items.json` (24 364 598 байт) и `items.json`
(17 457 106 байт) скачаны из ao-data/ao-bin-dumps с проверкой TLS. Импортированы
12 237 ID и 12 917 вариантов рецептов, включая RU/EN и числовой Index.
Количество зависит от версии дампа; исходники не заменены тестовыми предметами.

Живые запросы Asia `prices/T4_BAG.json` (Caerleon и Black Market) и
`history/T4_BAG.json?...&time-scale=1` не дошли до сервера: прокси отклонил
CONNECT (403). Это **не HTTP 403 от AODP**, не доказательство отсутствия данных
или доступа к самому API. Домены сохранены в черновик настроек, но изменение
черновика не применяет сетевую политику. Phase 1 нельзя считать полностью
подтверждённой до успешной проверки настоящих рыночных ответов Asia.

## Первичные исходники

Актуальный сервер — [albiondata-server-rails](https://github.com/ao-data/albiondata-server-rails).
Старый albiondata-api-dotNet изучен, но не используется как единственный контракт:
README albion-data-website указывает на Rails после февраля 2026.

| Возможность | Подтверждено исходниками | Живая проверка |
|---|---|---|
| REST prices | `app/api/stats_api.rb`, buy/sell и timestamps | Заблокирована сетью |
| REST history | `app/services/market_history_service.rb`: `item_id`, `location`, `quality`, `data[{item_count,avg_price,timestamp}]`; time-scale 1/6/24 | Заблокирована |
| HTTP rate limits | `stats_api.rb`, `rack_attack.rb`: gzip, 429, RateLimit-Reset = Unix epoch seconds, URL <4096 | Транспорт проверяется тестами, живое ограничение не провоцировалось |
| Orderbook REST | В изученном API не найден публичный endpoint полной глубины | Не подтверждено; не запрашиваем выдуманный endpoint |
| Client `-i` | `client/config.go`: адреса через запятую; `dispatcher.go` сохраняет magic URL `https+pow://albion-online-data.com` и выбирает регион | Источники проверены; игра/Windows здесь отсутствуют |
| Client HTTP | `client/uploader_http.go`: POST `<base>/<topic>`, JSON, требуется HTTP 200; `lib/market.go`: Orders и поля заявки | Локальный технический эксперимент входит в тесты, не равен тесту в игре |
| Денежные единицы | Rails `market_order_dedupe_service.rb`: ingress UnitPriceSilver делится на 10000. NATS deduped уже нормализован | Нельзя повторно делить NATS на 10000 |
| History client | `lib/marketHistory.go`, Rails processor: .NET ticks; только Timescale=0 интерпретируем как час в эксперименте | Нельзя считать Timescale=1 сутками: актуальный сервер хранит 6h; поддержка остальных масштабов отложена |
| NATS Asia | `app/views/pages/developer.html.erb`: порт 24222, marketorders.deduped, markethistories.deduped, дедупликация 5 min | Не подключались; отдельный TCP-доступ не настроен; в MVP отсутствует |
| Массовые дампы | Developer docs: `/database-east/`, `market_history_export_service.rb` экспортирует SQL | Доступность конкретных файлов не проверена; импорт SQL отложен |

## Границы достоверности

* Сервер, location ID и quality входят в каждый ключ. Caerleon=3005, BM=3003.
* Ноль цены / sentinel year 0001 — отсутствие наблюдения, не бесплатный товар.
* Свежесть определяется `observed_at`, не временем HTTP-ответа. Для ingress,
  где времени наблюдения нет, используется receipt и сохраняется ограничение.
* Локальные заявки — частичное наблюдение. Исчезновение из скана не доказывает
  продажу. Истечение заявки тоже не доказывает продажу.
* В источниках есть неоднозначность границ интервалов: суточная агрегация
  Rails специально сдвигает 00:00 на минуту назад. MVP использует только
  почасовые ответы и явно принятую start-labelled модель; проверка живых
  временных меток перед признанием метрик подтверждёнными обязательна.
* Неизвестная глубина остаётся неизвестной. Исторический объём не гарантирует
  исполнения будущей партии. BM оценивается только по действующему buy order.

Повторяемый эксперимент: `python -m albion_trade_desk probe --server east`.
Он сохраняет реальные JSON и HTTP-метаданные в `data/evidence/`; ошибки не
превращаются в пустые успешные результаты. Никакие mock-цены в рабочую базу
автоматически не загружаются.
