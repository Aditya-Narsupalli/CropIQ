"""
Market price scraper for FarmGenius.

Pulls LIVE commodity price & arrival data directly from the official
Agmarknet dashboard API (https://agmarknet.gov.in/home -> "Go" button):

    POST https://api.agmarknet.gov.in/v1/dashboard-data/

No API key is required. Note the important caveat: this particular
endpoint (dashboard="marketwise_price_arrival") returns a NATIONAL
summary per commodity (today / yesterday / day-before prices & arrivals),
not mandi/district-level prices. The `state`/`district`/`market` values
in the payload are Agmarknet's fixed internal IDs for the default
"All India" view, not something we can swap for a district name — so
`state`/`district` args on get_prices() are accepted for API
compatibility with the rest of the app but do not currently narrow the
result to a specific mandi. If district-level prices are needed later,
Agmarknet exposes a separate "price and arrival report" dashboard type
that does accept real state/district/market IDs - flag it if that's
wanted and we can wire up a dropdown-driven lookup.
"""
import httpx
import asyncio
from typing import List, Dict, Any, Optional
import json
from datetime import datetime, date
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGMARKNET_API_URL = "https://api.agmarknet.gov.in/v1/dashboard-data/"

# Default payload mirrors what agmarknet.gov.in's own frontend sends for
# the "All India / all commodities" marketwise price & arrival view.
DEFAULT_PAYLOAD = {
    "dashboard": "marketwise_price_arrival",
    "group": [100000],
    "commodity": [100001],
    "district": [100007],
    "market": [100009],
    "state": 100006,
    "variety": 100021,
    "grades": [4],
    "format": "json",
    "limit": 30,
}

REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://agmarknet.gov.in/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _to_float(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "-", "") else None
    except (TypeError, ValueError):
        return None


def _reformat_date(ddmmyyyy: Optional[str]) -> str:
    """Agmarknet returns dates as DD-MM-YYYY; normalize to YYYY-MM-DD."""
    if not ddmmyyyy:
        return date.today().isoformat()
    try:
        return datetime.strptime(ddmmyyyy, "%d-%m-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ddmmyyyy


def _pct_change(today_val: Optional[float], prev_val: Optional[float]) -> Optional[float]:
    if today_val is None or prev_val in (None, 0):
        return None
    return round(((today_val - prev_val) / prev_val) * 100, 1)


def _map_record(idx: int, r: Dict[str, Any]) -> Dict[str, Any]:
    """Map a raw Agmarknet record into the shape the frontend already expects
    ({crop, price_per_quintal, location, date, source}), plus extra fields
    (trend, msp_price, price_change_pct, commodity_group) the UI can use."""
    price_today = _to_float(r.get("as_on_price"))
    price_1d_ago = _to_float(r.get("one_day_ago_price"))

    return {
        "id": idx,
        "crop": r.get("cmdt_name", "Unknown"),
        "commodity_group": r.get("cmdt_grp_name"),
        "price_per_quintal": price_today,
        "msp_price": _to_float(r.get("msp_price")),
        "arrival_metric_tonnes": _to_float(r.get("as_on_arrival")),
        "trend": r.get("trend"),  # "up" | "down" | null, as reported by Agmarknet
        "price_change_pct": _pct_change(price_today, price_1d_ago),
        "location": "All India (Agmarknet)",
        "date": _reformat_date(r.get("reported_date")),
        "source": "Agmarknet (Live)",
    }


class AgmarknetAPI:
    """Live scraper for agmarknet.gov.in's public dashboard-data API."""

    async def _fetch_dashboard(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        payload = {**DEFAULT_PAYLOAD, "date": target_date or date.today().isoformat()}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                AGMARKNET_API_URL, json=payload, headers=REQUEST_HEADERS
            )
            response.raise_for_status()
            return response.json()

    async def get_all(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch and map every commodity in today's dashboard."""
        try:
            raw = await self._fetch_dashboard(target_date)
            records = raw.get("data", {}).get("records", [])
            return [_map_record(i, r) for i, r in enumerate(records)]
        except Exception as e:
            logger.error(f"Error fetching Agmarknet dashboard: {e}")
            return []

    async def get_prices(
        self,
        commodity: str,
        state: Optional[str] = None,
        district: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> List[Dict[Any, Any]]:
        """Fetch prices filtered to commodities matching `commodity` (substring,
        case-insensitive). `state`/`district` are accepted for interface
        compatibility but not currently used to filter - see module docstring."""
        all_prices = await self.get_all(target_date)
        needle = commodity.lower().strip()
        if not needle:
            return all_prices
        return [p for p in all_prices if needle in p["crop"].lower()]


# Factory function to get appropriate scraper (kept for backward compatibility
# with call sites that do get_scraper("agmarknet") / get_scraper("worldbank")).
def get_scraper(source: str = "agmarknet") -> AgmarknetAPI:
    return AgmarknetAPI()


async def get_all_prices() -> List[Dict[Any, Any]]:
    """Get current live prices for all commodities Agmarknet reports today."""
    scraper = get_scraper()
    return await scraper.get_all()


# When run directly, this will test the scraper
if __name__ == "__main__":
    async def test():
        prices = await get_all_prices()
        print(json.dumps(prices, indent=2))

    asyncio.run(test())
