"""Stable typed exports, Excel-compatible CSV and minimal Open XML workbook."""
import csv
import io
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

COLUMNS = ("item_id", "name_ru", "name_en", "server", "location_id", "quality", "tier", "enchantment",
           "category", "sell_min", "sell_observed_at", "sell_received_at", "sell_source", "sell_fresh",
           "buy_max", "buy_observed_at", "buy_received_at", "buy_source", "buy_fresh",
           "spread", "spread_pct", "volume_1h", "known_1h", "coverage_1h", "volume_24h", "known_24h",
           "coverage_24h", "volume_7d", "known_7d", "coverage_7d", "vwap_7d", "volatility_pct", "anomaly")


def records(rows):
    expanded=[]
    for row in rows:
        if len(row.get('by_quality',[]))>1:
            for q in row['by_quality']:
                sell,buy=q['quotes'].get('sell_price_min'),q['quotes'].get('buy_price_max')
                spread=sell['price']-buy['price'] if sell and buy else None
                expanded.append({**row,**q,'spread':spread,'spread_pct':100*spread/buy['price'] if spread is not None else None})
        else:expanded.append(row)
    for row in expanded:
        sell, buy = row["quotes"].get("sell_price_min", {}), row["quotes"].get("buy_price_max", {})
        result = dict(zip(COLUMNS[:9], [row["id"], row["name_ru"], row["name_en"], row["server"], row["location"],
                                       row["quality"], row["tier"], row["enchantment"], row["category"]]))
        for prefix, q in (("sell", sell), ("buy", buy)):
            result[prefix + ("_min" if prefix == "sell" else "_max")] = q.get("price")
            for key in ("observed_at", "received_at", "source", "fresh"):
                result[prefix + "_" + key] = q.get(key)
        result.update(spread=row["spread"], spread_pct=row["spread_pct"], vwap_7d=row["vwap"],
                      volatility_pct=row["volatility_pct"], anomaly=row["anomaly"])
        for window in ("1h", "24h", "7d"):
            p = row["volumes"][window]
            result.update({"volume_" + window: p["volume"], "known_" + window: p["known_quantity"],
                           "coverage_" + window: p["coverage"]})
        yield [result.get(c) for c in COLUMNS]


def safe_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(COLUMNS)
    writer.writerows([safe_text(v) for v in record] for record in records(rows))
    return stream.getvalue().encode("utf-8-sig")


def column(index):
    text = ""
    while index:
        index, n = divmod(index - 1, 26)
        text = chr(65 + n) + text
    return text


def xlsx_bytes(rows):
    return table_xlsx([list(COLUMNS), *records(rows)])


def table_xlsx(data, sheet_name="{escape(sheet_name)}"):
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = [f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews><sheetData>']
    for r, record in enumerate(data, 1):
        sheet.append(f'<row r="{r}">')
        for c, value in enumerate(record, 1):
            ref = f"{column(c)}{r}"
            if value is None:
                continue
            if isinstance(value, bool):
                sheet.append(f'<c r="{ref}" t="b"><v>{int(value)}</v></c>')
            elif isinstance(value, (int, float)):
                sheet.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                sheet.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>')
        sheet.append('</row>')
    sheet.append(f'</sheetData><autoFilter ref="A1:{column(len(data[0]))}{len(data)}"/></worksheet>')
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>''')
        z.writestr("_rels/.rels", '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>''')
        z.writestr("xl/worksheets/sheet1.xml", "".join(sheet))
    return stream.getvalue()
