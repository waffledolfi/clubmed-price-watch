"""Club Med price API client.

Prices come from api.clubmed.com/v1/search_price -- the same backend the
website's GraphQL gateway calls. The website displays best_price + fees_amount,
so that sum is what we track.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

API = "https://api.clubmed.com/v1/search_price"
API_KEY = "202306011107.b2c.revamp.clubmed.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36")


class PriceError(Exception):
    pass


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def nights_between(start, end):
    return (parse_date(end) - parse_date(start)).days


def fetch_price(product_id, start_date, nights, adults=2, children=0,
                departure_option_id=None, locale="en-SG", timeout=30):
    """Return a price dict for one stay, or raise PriceError.

    start_date: 'YYYY-MM-DD'. nights: integer stay length.
    departure_option_id: e.g. 'SIN' to include flights; None = resort only.
    """
    params = {
        "number_attendees": adults + children,
        "first_date": parse_date(start_date).strftime("%Y%m%d"),
        "duration": nights,
        "product_id": product_id,
        "api_key": API_KEY,
    }
    if departure_option_id:
        params["departure_option_id"] = departure_option_id

    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Accept-Language": locale,
        "Accept": "application/json",
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise PriceError("HTTP %s: %s" % (e.code, detail))
    except Exception as e:
        raise PriceError(str(e))

    if not isinstance(body, list) or not body:
        raise PriceError("no availability returned")

    item = body[0]
    price = item.get("price") or {}
    trip = price.get("per_trip") or {}
    if "best_price" not in trip:
        raise PriceError("no price in response")

    fees = trip.get("fees_amount") or 0
    best = trip["best_price"] + fees
    initial = (trip.get("initial_price") or trip["best_price"]) + fees
    return {
        "product_id": item.get("product_id", product_id),
        "currency": price.get("currency", "SGD"),
        "best_price": round(best, 2),
        "initial_price": round(initial, 2),
        "fees": fees,
        "nights": item.get("terms_and_conditions", {}).get("total_duration", nights),
        "discount_pct": round(100.0 * (initial - best) / initial, 1) if initial else 0.0,
    }


def booking_url(product_id, slug, start_date, nights, adults=2, children=0,
                site="https://www.clubmed.com.sg", season="w"):
    end = (parse_date(start_date) + timedelta(days=nights)).isoformat()
    q = urllib.parse.urlencode({
        "adults": adults, "children": children,
        "start_date": start_date, "end_date": end,
    })
    return "%s/r/%s/%s?%s" % (site, slug, season, q)
