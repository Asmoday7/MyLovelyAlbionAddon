"""Metrics over observed closed hours. Missing coverage is never zero demand."""
from collections import defaultdict
import math
from .domain import utcnow, region, quality, location

SCOPES = {
    "private": ("private-client",),
    "public": ("aodp-rest", "aodp-file", "aodp-nats"),
    "legacy": ("data-client",),
}


def unique_hours(points):
    # Source is part of storage identity, but not a license to double-count the same hour.
    chosen = {}
    for point in sorted(points, key=lambda p: (p.get("received_at", 0), p.get("source", ""))):
        chosen[(point["start"], point["seconds"])] = point
    return list(chosen.values())


def window(points, hours, now):
    end = int(now // 3600) * 3600
    start = end - hours * 3600
    # Only hourly observations. Daily/6h aggregates must never overlap these.
    chosen = {p["start"]: p for p in points if p["seconds"] == 3600
              and start <= p["start"] < end}
    quantity = sum(p["quantity"] for p in chosen.values())
    complete = len(chosen) == hours
    return {"volume": quantity if complete else None,
            "known_quantity": quantity if chosen else None,
            "coverage": len(chosen) / hours, "known_hours": len(chosen),
            "expected_hours": hours, "start": start, "end": end,
            "turnover": sum(p["quantity"] * p["average"] for p in chosen.values()) if complete else None}


def metrics(points, now):
    points = unique_hours(points)
    windows = {label: window(points, hours, now) for label, hours in (("1h", 1), ("24h", 24), ("7d", 168))}
    closed = [p for p in points if p["seconds"] == 3600
              and windows["7d"]["start"] <= p["start"] < windows["7d"]["end"] and p["quantity"] > 0]
    count = sum(p["quantity"] for p in closed)
    vwap = sum(p["quantity"] * p["average"] for p in closed) / count if count else None
    variance = sum(p["quantity"] * (p["average"] - vwap) ** 2 for p in closed) / count if count else None
    return {"volumes": windows, "vwap": vwap,
            "volatility_pct": 100 * math.sqrt(variance) / vwap if vwap and len(closed) >= 2 else None,
            "average_daily": windows["7d"]["volume"] / 7 if windows["7d"]["volume"] is not None else None,
            "history_hours": len(closed)}


def market(store, filters=None, limit=50, offset=0, now=None):
    f = filters or {}
    now = now if now is not None else utcnow()
    server, city, q = region(f.get("server", "east")), location(f.get("city", "3005")), quality(f.get("quality", 1))
    max_age = float(f.get("max_age_hours", 24)) * 3600
    scope = f.get("scope", "all")
    if scope != "all" and scope not in SCOPES:
        raise ValueError("Неизвестный набор источников")
    sources = SCOPES.get(scope)
    if not math.isfinite(max_age) or max_age < 0:
        raise ValueError("Некорректный возраст")
    clauses, params = ["1=1"], []
    if f.get("search"):
        clauses.append("instr(i.search,?)>0")
        params.append(f["search"].casefold())
    for key in ("tier", "enchantment", "category", "subcategory"):
        if f.get(key) not in (None, ""):
            clauses.append(f"i.{key}=?")
            params.append(f[key])
    if str(f.get("favorites", "")).lower() in ("1", "true"):
        clauses.append("EXISTS(SELECT 1 FROM favorites WHERE item_id=i.id)")
    if str(f.get("priced", "")).lower() in ("1", "true"):
        source_sql = " AND source IN (" + ",".join("?" for _ in sources) + ")" if sources else ""
        clauses.append("EXISTS(SELECT 1 FROM quotes WHERE server=? AND location=? AND quality=? AND item_id=i.id" + source_sql + ")")
        params += [server, city, q]
        params += list(sources or ())
    sort = {"name": "i.name_ru", "tier": "i.tier", "id": "i.id", "category": "i.category"}.get(f.get("sort"), "i.name_ru")
    direction = "DESC" if f.get("direction") == "desc" else "ASC"
    where = " AND ".join(clauses)
    with store.connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM items i WHERE {where}", params).fetchone()[0]
        items = [dict(r) for r in db.execute(f"""SELECT i.*,EXISTS(SELECT 1 FROM favorites WHERE item_id=i.id) favorite,
            EXISTS(SELECT 1 FROM recipes WHERE item_id=i.id) has_recipe
            FROM items i WHERE {where} ORDER BY {sort} {direction},i.id LIMIT ? OFFSET ?""", params + [limit, offset])]
        result = []
        for item in items:
            uid = item["id"]
            quotes = db.execute("""SELECT * FROM quotes WHERE server=? AND location=? AND item_id=? AND quality=?
                ORDER BY observed_at DESC,received_at DESC""", (server, city, uid, q)).fetchall()
            best = {}
            for row in quotes:
                if sources and row["source"] not in sources:
                    continue
                if row["kind"] not in best:
                    live = True
                    if row["source"] in ("data-client", "private-client", "aodp-nats"):
                        side = "offer" if row["kind"] == "sell_price_min" else "request"
                        live = db.execute("""SELECT 1 FROM orders WHERE server=? AND location=?
                            AND item_id=? AND quality=? AND side=? AND price=? AND amount>0 AND expires>? AND source=?
                            LIMIT 1""", (server, city, uid, q, side, row["price"], now, row["source"])).fetchone() is not None
                    best[row["kind"]] = {**dict(row), "age_seconds": max(0, now - row["observed_at"]),
                                         "fresh": live and now - row["observed_at"] <= max_age}
            # BM is a buyer. Never base economics on a hypothetical ordinary sell price.
            if city == "3003":
                best.pop("sell_price_min", None)
            points = [dict(p) for p in db.execute("""SELECT * FROM history WHERE server=? AND location=?
                AND item_id=? AND quality=? AND start>=? AND start<?""",
                         (server, city, uid, q, int(now // 3600) * 3600 - 168 * 3600, now))]
            if sources:
                points = [p for p in points if p["source"] in sources]
            m = metrics(points, now)
            sell, buy = best.get("sell_price_min"), best.get("buy_price_max")
            spread = sell["price"] - buy["price"] if sell and buy else None
            outlier = m["history_hours"] >= 3 and m["vwap"] and any(
                row["price"] < m["vwap"] / 3 or row["price"] > m["vwap"] * 3 for row in best.values())
            result.append({**item, "server": server, "location": city, "quality": q,
                           "quotes": best, "spread": spread,
                           "spread_pct": spread / buy["price"] * 100 if spread is not None and buy["price"] else None,
                           "anomaly": bool(outlier), "depth": None, **m})
        return {"rows": result, "total": total, "limit": limit, "offset": offset,
                "window_model": "last_completed_utc_hours; start-labelled (live validation pending)"}
