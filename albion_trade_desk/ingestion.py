"""Validated market inputs. A partial scan is never a complete order book."""
from collections import defaultdict
from .domain import region, quality, location, number, timestamp, utcnow


def put_quote(db, server, city, item, q, kind, price, observed, received, source, limitation):
    if price <= 0 or observed < 946684800 or observed > received + 300:
        return 0  # AODP zero and year 0001 mean missing, not a free item.
    db.execute("INSERT OR IGNORE INTO market_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",
               (server, city, item, q, kind, price, observed, received, source, limitation))
    db.execute("""INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(server,location,item_id,quality,kind,source) DO UPDATE SET
        price=excluded.price,observed_at=excluded.observed_at,received_at=excluded.received_at,
        limitation=excluded.limitation WHERE excluded.observed_at>=quotes.observed_at""",
               (server, city, item, q, kind, price, observed, received, source, limitation))
    return 1


def event(db, server, source, kind, count, detail=""):
    db.execute("INSERT INTO events(at,server,source,kind,count,detail) VALUES(?,?,?,?,?,?)",
               (utcnow(), server, source, kind, count, detail))


def prices(store, payload, server="east", source="aodp-rest"):
    region(server)
    if not isinstance(payload, list):
        raise ValueError("Ожидается массив prices")
    now, count = utcnow(), 0
    with store.connect() as db:
        for row in payload:
            for kind in ("sell_price_min", "buy_price_max"):
                price = number(row.get(kind, 0))
                if not price:
                    continue
                if str(row.get(kind + "_date", "")).startswith("0001-"):
                    continue
                observed = timestamp(row[kind + "_date"])
                count += put_quote(db, server, location(row["city"]), row["item_id"],
                                   quality(row["quality"]), kind, price, observed, now,
                                   source, "crowdsourced; depth unknown")
        event(db, server, source, "prices", count)
    return count


def history(store, payload, server="east", seconds=3600, source="aodp-rest"):
    region(server)
    if seconds not in (3600, 21600, 86400):
        raise ValueError("Поддерживаются интервалы 1, 6, 24 часа")
    if not isinstance(payload, list):
        raise ValueError("Ожидается массив history")
    now, count = utcnow(), 0
    with store.connect() as db:
        for row in payload:
            for point in row["data"]:
                start = timestamp(point["timestamp"])
                if start > now + 300 or start % seconds != 0:
                    raise ValueError("Неверная граница исторического интервала")
                qty = number(point["item_count"])
                if int(qty) != qty:
                    raise ValueError("Объём должен быть целым")
                db.execute("""INSERT INTO history VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(server,location,item_id,quality,start,seconds) DO UPDATE SET
                    quantity=excluded.quantity,average=excluded.average,
                    received_at=excluded.received_at,source=excluded.source""",
                           (server, location(row["location"]), row["item_id"], quality(row["quality"]),
                            start, seconds, int(qty), number(point["avg_price"]), now, source))
                count += 1
        event(db, server, source, "history", count)
    return count


def local_orders(store, payload, server="east"):
    region(server)
    now, groups, count = utcnow(), defaultdict(list), 0
    rows = payload["Orders"]
    if not isinstance(rows, list):
        raise ValueError("Orders должен быть массивом")
    with store.connect() as db:
        for row in rows:
            side = row["AuctionType"]
            if side not in ("offer", "request"):
                raise ValueError("Неизвестный AuctionType")
            uid = str(row["ItemTypeId"])
            enchant = int(number(row.get("EnchantmentLevel", 0), maximum=4))
            if enchant and "@" not in uid and "_LEVEL" not in uid:
                uid += f"@{enchant}"
            price = number(row["UnitPriceSilver"]) / 10000
            amount = int(number(row["Amount"]))
            expires = timestamp(row["Expires"])
            city, q = location(row["LocationId"]), quality(row["QualityLevel"])
            if not city:
                raise ValueError("LocationId обязателен")
            db.execute("""INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(server,id)
                DO UPDATE SET price=excluded.price,amount=excluded.amount,expires=excluded.expires,
                received_at=excluded.received_at""",
                       (server, str(row["Id"]), uid, city, q, side, price, amount, expires, now))
            if expires > now and amount > 0 and price > 0:
                groups[(city, uid, q, side)].append(price)
            count += 1
        for (city, uid, q, side), values in groups.items():
            put_quote(db, server, city, uid, q,
                      "sell_price_min" if side == "offer" else "buy_price_max",
                      min(values) if side == "offer" else max(values), now, now,
                      "data-client", "partial scan; observation time is local receipt; depth unknown")
        event(db, server, "data-client", "orders", count)
    return count


def local_history(store, payload, server="east"):
    # Only hourly client input validated. Nonzero Timescale is NOT a daily bin.
    region(server)
    scale = int(payload["Timescale"])
    if scale != 0:
        raise ValueError("Эксперимент принимает только Timescale=0 (час)")
    with store.connect() as db:
        item = db.execute("SELECT id FROM items WHERE numeric_id=?", (int(payload["AlbionId"]),)).fetchone()
    if item is None:
        raise ValueError("Сначала импортируйте каталог для сопоставления AlbionId")
    points = []
    for p in payload["MarketHistories"]:
        quantity = number(p["ItemAmount"])
        points.append({"timestamp": (int(p["Timestamp"]) - 621355968000000000) / 10000000,
                       "item_count": quantity,
                       "avg_price": number(p["SilverAmount"]) / 10000 / quantity if quantity else 0})
    return history(store, [{"item_id": item["id"], "location": payload["LocationId"],
                            "quality": payload["QualityLevel"], "data": points}],
                   server, 3600, "data-client")
