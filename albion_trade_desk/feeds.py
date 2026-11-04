"""Market-only protocol adapters. No uplink, no private/personalized topics."""
from . import ingestion
from .domain import region, quality, location, number, timestamp, utcnow, MarketOrderError

SOURCES = ("private-client", "aodp-nats")


def integer(value, maximum=2**63-1):
    if isinstance(value, bool):
        raise ValueError("Ожидается целое число")
    n = int(value)
    if str(n) != str(value) or not 0 <= n <= maximum:
        raise ValueError("Некорректное целое число")
    return n


def validate_orders(payload):
    if not isinstance(payload, dict) or set(payload) != {"Orders"} or not isinstance(payload["Orders"], list):
        raise ValueError("Ожидается market-only объект Orders")
    fields = {"Id", "ItemTypeId", "ItemGroupTypeId", "LocationId", "QualityLevel", "EnchantmentLevel",
              "UnitPriceSilver", "Amount", "AuctionType", "Expires"}
    for index,row in enumerate(payload["Orders"]):
        if not isinstance(row, dict) or set(row) - fields:
            raise MarketOrderError("Неподдерживаемые или персональные поля в market order",index,'Orders')
        uid = row.get("ItemTypeId")
        if not isinstance(uid, str) or not 1 <= len(uid) <= 150 or not all(c.isalnum() or c in "_@-" for c in uid):
            raise MarketOrderError("Некорректный ItemTypeId",index,'ItemTypeId')
        checks = [
            ('LocationId',lambda v: v is not None and bool(location(v)) and len(str(v))<=150,'Некорректный LocationId'),
            ('QualityLevel',lambda v: bool(quality(integer(v))),'Качество должно быть от 1 до 5'),
            ('Id',lambda v: integer(v)>=0,'Ожидается неотрицательный целый ID'),
            ('Amount',lambda v: integer(v)>=0,'Количество должно быть целым и неотрицательным'),
            ('EnchantmentLevel',lambda v: integer(v,4)>=0,'Зачарование должно быть целым от 0 до 4'),
            ('AuctionType',lambda v: v in ('offer','request'),'Неизвестный AuctionType'),
            ('UnitPriceSilver',lambda v: number(v)>=0,'Некорректная цена'),
            ('Expires',lambda v: timestamp(v) is not None,'Некорректное время окончания ордера'),
        ]
        for field,check,message in checks:
            value=None
            try:
                value=row.get(field,0) if field=='EnchantmentLevel' else row[field]
                if not check(value):raise ValueError(message)
            except (ValueError,KeyError,TypeError,OverflowError) as exc:
                if field in ('QualityLevel','EnchantmentLevel') and type(value) is int and -10000<=value<=10000:
                    message+=f' (получено {value})'
                raise MarketOrderError(message,index,field,uid) from exc


def market_history(store, payload, server, source, scaled=True, observed_at=None):
    """Keep all native scales, normalize only verified hourly scale, never invent daily bins."""
    region(server)
    if source not in SOURCES:
        raise ValueError("Неизвестный источник потока")
    if not isinstance(payload, dict):
        raise ValueError("Ожидается объект истории")
    allowed = {"AlbionId", "AlbionIdString", "LocationId", "QualityLevel", "Timescale", "MarketHistories"}
    if set(payload) - allowed:
        raise ValueError("Неподдерживаемые или персональные поля истории")
    numeric, q, scale = integer(payload["AlbionId"]), integer(payload["QualityLevel"], 5), integer(payload["Timescale"], 2)
    if numeric == 0 or not str(payload["LocationId"]):
        raise ValueError("AlbionId и LocationId обязательны")
    city, now = location(payload["LocationId"]), utcnow() if observed_at is None else timestamp(observed_at)
    if not isinstance(payload["MarketHistories"], list):
        raise ValueError("MarketHistories должен быть массивом")
    parsed = []
    for p in payload["MarketHistories"]:
        if not isinstance(p, dict) or set(p) != {"Timestamp", "ItemAmount", "SilverAmount"}:
            raise ValueError("Неверный формат точки истории")
        ticks, quantity = integer(p["Timestamp"]), integer(p["ItemAmount"])
        observed = (ticks - 621355968000000000) / 10000000
        if not 946684800 <= observed <= now + 300:
            raise ValueError("Время истории вне допустимого диапазона")
        silver = number(p["SilverAmount"]) / (10000 if scaled else 1)
        parsed.append((ticks, quantity, silver))
    # Validate everything before committing. Unknown catalogue IDs remain recoverable.
    with store.connect() as db:
        item = db.execute("SELECT id FROM items WHERE numeric_id=?", (numeric,)).fetchone()
        uid = item["id"] if item else None
        provided_id = payload.get("AlbionIdString")
        if provided_id and uid and provided_id != uid:
            raise ValueError("AlbionIdString не совпадает с каталогом")
        for ticks, quantity, silver in parsed:
            db.execute("""INSERT INTO native_history VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(server,location,numeric_id,quality,timescale,ticks,source) DO UPDATE SET
                quantity=excluded.quantity,silver=excluded.silver,received_at=excluded.received_at,
                item_id=excluded.item_id WHERE excluded.received_at>=native_history.received_at""", (server, city, numeric, uid, q, scale, ticks, quantity, silver, now, source))
        ingestion.event(db, server, source, "native-history", len(parsed))
    resolve_history(store, source, server, numeric)
    return len(parsed)


def resolve_history(store, source=None, server=None, numeric=None):
    with store.connect() as db:
        db.execute("""UPDATE native_history SET item_id=(SELECT id FROM items WHERE numeric_id=native_history.numeric_id)
            WHERE item_id IS NULL AND EXISTS(SELECT 1 FROM items WHERE numeric_id=native_history.numeric_id)""")
        # Coarse Timescale 1/2 raw observations are retained, not spread over artificial hours.
        clauses, params = ['timescale=0', 'item_id IS NOT NULL', 'quality BETWEEN 1 AND 5'], []
        for name, value in (('source',source),('server',server),('numeric_id',numeric)):
            if value is not None:
                clauses.append(name+'=?'); params.append(value)
        rows = db.execute("SELECT * FROM native_history WHERE "+' AND '.join(clauses), params).fetchall()
        for row in rows:
            start = (row["ticks"] - 621355968000000000) / 10000000
            if start % 3600:
                continue  # Preserve native point; unsupported boundary must not be guessed.
            db.execute("""INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(server,location,item_id,quality,start,seconds,source) DO UPDATE SET
                quantity=excluded.quantity,average=excluded.average,received_at=excluded.received_at
                WHERE excluded.received_at>=history.received_at""", (
                    row["server"], row["location"], row["item_id"], row["quality"], start, 3600,
                    row["quantity"], row["silver"] / row["quantity"] if row["quantity"] else 0,
                    row["received_at"], row["source"]))


def ingest(store, topic, payload, server, source="private-client", observed_at=None):
    region(server)
    if source not in SOURCES:
        raise ValueError("Недопустимый источник")
    if topic in ("marketorders.ingest", "marketorders.deduped"):
        if source == "aodp-nats":
            if topic != "marketorders.deduped":
                raise ValueError("NATS: только deduped")
            payload = {"Orders": [payload]}
        elif topic != "marketorders.ingest":
            raise ValueError("Локальный клиент: только ingest")
        validate_orders(payload)
        return ingestion.local_orders(store, payload, server, source, scaled=source == "private-client", observed_at=observed_at)
    if topic in ("markethistories.ingest", "markethistories.deduped"):
        if (source == "aodp-nats") != topic.endswith("deduped"):
            raise ValueError("Неверный формат источника истории")
        return market_history(store, payload, server, source, scaled=source == "private-client", observed_at=observed_at)
    raise ValueError("Личные сообщения и прочие темы не принимаются")
