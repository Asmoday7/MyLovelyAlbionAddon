"""Shared identities and UTC handling. Region is always part of market identity."""
from datetime import datetime, timezone
import math

SERVERS = {
    "east": "https://east.albion-online-data.com",
    "west": "https://west.albion-online-data.com",
    "europe": "https://europe.albion-online-data.com",
}
MARKETS = {"2004": "Bridgewatch", "3008": "Martlock", "1002": "Lymhurst",
           "4002": "Fort Sterling", "7": "Thetford", "3005": "Caerleon",
           "5003": "Brecilien", "3003": "Black Market"}

# Market packets can carry either the city cluster or its auction-house zone.
# 3003 is deliberately absent: bare 3003 denotes Black Market in market data.
MARKET_ALIASES = {"0": "7", "1000": "1002", "2000": "2004", "3004": "3008",
                  "4000": "4002", "5000": "5003", "301": "7", "1301": "1002",
                  "2301": "2004", "3301": "3008", "4301": "4002", "3013": "3005"}
HELLDEN_MARKETS = {"0000-HellDen": "7", "1000-HellDen": "1002", "2000-HellDen": "2004",
                   "3004-HellDen": "3008", "3003-HellDen": "3005",
                   "4000-HellDen": "4002", "5000-HellDen": "5003"}


def utcnow():
    return datetime.now(timezone.utc).timestamp()


def timestamp(value):
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        result = dt.replace(tzinfo=dt.tzinfo or timezone.utc).timestamp()
    if not math.isfinite(result):
        raise ValueError("Некорректное время")
    return result


def location(value):
    text = str(value).strip()
    # Native AOD locations differ from normalized REST locations. Preserve unknowns.
    if text in HELLDEN_MARKETS:
        return HELLDEN_MARKETS[text]
    if text.endswith('-Auction2'):
        text = text.removesuffix('-Auction2')
    if text.isdecimal():
        text = str(int(text))
    text = MARKET_ALIASES.get(text, text)
    return next((k for k, v in MARKETS.items() if v.casefold() == text.casefold()), text)


def region(value):
    if value not in SERVERS:
        raise ValueError("Неизвестный сервер")
    return value


def quality(value):
    q = int(value)
    if q not in range(1, 6):
        raise ValueError("Качество должно быть от 1 до 5")
    return q


def number(value, minimum=0, maximum=1e15):
    n = float(value)
    if not math.isfinite(n) or not minimum <= n <= maximum:
        raise ValueError("Число вне допустимого диапазона")
    return n
