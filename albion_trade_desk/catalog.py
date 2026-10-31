"""Importer for ao-data/ao-bin-dumps; no hand-maintained item catalogue."""
import json
import re
from .domain import utcnow, number

CATALOG_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json"
RECIPES_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json"


def many(value):
    return value if isinstance(value, list) else [value] if value else []


def import_catalog(store, names, raw=None):
    if not isinstance(names, list) or not names or not all("UniqueName" in i for i in names):
        raise ValueError("Ожидается formatted/items.json из ao-bin-dumps")
    now, count = utcnow(), 0
    with store.connect() as db:
        for item in names:
            uid = item["UniqueName"]
            localized = item.get("LocalizedNames") or {}
            en = localized.get("EN-US") or uid
            ru = localized.get("RU-RU") or en
            tier = re.match(r"T(\d+)_", uid)
            enchant = re.search(r"@(\d+)$", uid)
            db.execute("""INSERT INTO items(id,numeric_id,name_ru,name_en,tier,enchantment,search,catalog_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET numeric_id=excluded.numeric_id,
                name_ru=excluded.name_ru,name_en=excluded.name_en,tier=excluded.tier,
                enchantment=excluded.enchantment,search=excluded.search,catalog_at=excluded.catalog_at""",
                       (uid, int(item["Index"]), ru, en, int(tier[1]) if tier else 0,
                        int(enchant[1]) if enchant else 0, f"{uid} {ru} {en}".casefold(), now))
            count += 1
        if raw:
            import_recipes(db, raw)
    return count


def import_recipes(db, raw):
    root = raw["items"]
    for kind, entries in root.items():
        for entry in many(entries):
            if not isinstance(entry, dict) or "@uniquename" not in entry:
                continue
            base = entry["@uniquename"]
            variants = [(base, entry)]
            for enchanted in many((entry.get("enchantments") or {}).get("enchantment")):
                variants.append((base + "@" + enchanted["@enchantmentlevel"], {**entry, **enchanted}))
            for uid, data in variants:
                db.execute("""UPDATE items SET category=?,subcategory=?,weight=?,metadata=? WHERE id=?""",
                           (data.get("@shopcategory", kind), data.get("@shopsubcategory1", ""),
                            float(data["@weight"]) if "@weight" in data else None,
                            json.dumps({"kind": kind, "subcategory2": data.get("@shopsubcategory2"),
                                        "upgrade": data.get("upgraderequirements")}, ensure_ascii=False), uid))
                db.execute("DELETE FROM recipes WHERE item_id=?", (uid,))
                for variant, recipe in enumerate(many(data.get("craftingrequirements"))):
                    resources = [{"item_id": r["@uniquename"], "count": number(r["@count"]),
                                  "returnable": r.get("@maxreturnamount") != "0"}
                                 for r in many(recipe.get("craftresource"))]
                    if resources:
                        db.execute("INSERT INTO recipes VALUES(?,?,?,?,?,?)", (
                            uid, variant, number(recipe.get("@amountcrafted", 1), minimum=0.001),
                            float(recipe["@craftingfocus"]) if "@craftingfocus" in recipe else None,
                            number(recipe.get("@silver", 0)), json.dumps(resources)))
