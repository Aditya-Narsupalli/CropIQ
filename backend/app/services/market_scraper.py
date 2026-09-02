"""
Market price scraper for CropIQ.

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
import time
import os
from typing import List, Dict, Any, Optional
import json
from datetime import datetime, date, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGMARKNET_API_URL = "https://api.agmarknet.gov.in/v1/dashboard-data/"

# --- In-memory cache for daily dashboard fetches ---
# A given PAST date's dashboard never changes once reported, and every
# get_prices() call for that date was re-fetching the *entire* national
# dashboard (all commodities) from scratch just to filter down to one crop
# client-side. With a 30-day trend pulling one date per day, that meant up
# to 30 full-dashboard requests per trend lookup - and repeating that for
# every crop/user hit Agmarknet's rate limit (429). Caching by date fixes
# both: repeat lookups (same date, different crop or different user) are
# free, and only genuinely new dates hit the network.
_DASHBOARD_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_DASHBOARD_CACHE_TIME: Dict[str, float] = {}
_CACHE_TTL_TODAY = 15 * 60      # today's prices can still update - refresh every 15 min
_CACHE_TTL_PAST = 24 * 60 * 60  # past dates are final - cache for a day
_cache_locks: Dict[str, asyncio.Lock] = {}

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
        "price_1d_ago": price_1d_ago,  # exposed so callers can build a real (if short) 2-point trend without an extra request
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

    async def _fetch_dashboard_raw(self, target_date: str) -> Dict[str, Any]:
        """Single network call, with retry + backoff on 429/5xx.
        Honors the Retry-After header when Agmarknet sends one."""
        payload = {**DEFAULT_PAYLOAD, "date": target_date}
        max_attempts = 3
        async with httpx.AsyncClient(timeout=20.0) as client:
            for attempt in range(1, max_attempts + 1):
                response = await client.post(
                    AGMARKNET_API_URL, json=payload, headers=REQUEST_HEADERS
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == max_attempts:
                        response.raise_for_status()
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else (2 ** attempt)  # 2s, 4s
                    logger.warning(
                        f"Agmarknet {response.status_code} for {target_date} "
                        f"(attempt {attempt}/{max_attempts}), retrying in {wait:.0f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()

    async def _fetch_dashboard(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Cached, mapped dashboard for one date. Concurrent requests for the
        same not-yet-cached date are serialized (via a per-date lock) so a
        burst of calls for the same day results in one network request, not
        N of them."""
        target_date = target_date or date.today().isoformat()
        is_today = target_date == date.today().isoformat()
        ttl = _CACHE_TTL_TODAY if is_today else _CACHE_TTL_PAST

        cached_at = _DASHBOARD_CACHE_TIME.get(target_date)
        if cached_at is not None and (time.time() - cached_at) < ttl:
            return _DASHBOARD_CACHE[target_date]

        lock = _cache_locks.setdefault(target_date, asyncio.Lock())
        async with lock:
            # Re-check after acquiring the lock - another concurrent caller
            # may have just populated the cache while we were waiting.
            cached_at = _DASHBOARD_CACHE_TIME.get(target_date)
            if cached_at is not None and (time.time() - cached_at) < ttl:
                return _DASHBOARD_CACHE[target_date]

            raw = await self._fetch_dashboard_raw(target_date)
            records = raw.get("data", {}).get("records", [])
            mapped = [_map_record(i, r) for i, r in enumerate(records)]
            _DASHBOARD_CACHE[target_date] = mapped
            _DASHBOARD_CACHE_TIME[target_date] = time.time()
            return mapped

    async def get_all(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch and map every commodity in the given day's dashboard (today by default)."""
        try:
            return await self._fetch_dashboard(target_date)
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


# --- Daily snapshot log (persisted to Upstash Redis when configured) ---
# Agmarknet's live API only ever exposes a today/yesterday snapshot - there
# is no real endpoint to pull an arbitrary 30-day window from (confirmed:
# see get_price_history's docstring below). A genuine multi-day trend can
# only exist if *we* record real daily prices over time.
#
# IMPORTANT: a local JSON file alone does NOT work for this in production on
# Render (or most PaaS free/standard tiers) - the filesystem is ephemeral,
# so every redeploy, and every time a free-tier service sleeps and wakes
# back up, wipes local disk changes and resets the log to empty. Upstash
# Redis's free tier (REST-based, no persistent connection needed - fits an
# ephemeral/serverless-style host like Render well) is used instead when
# configured. Falls back to a local file when it's not (e.g. local dev
# without an Upstash account) - fine for testing, NOT fine for production
# without UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN set.
_SNAPSHOT_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "price_snapshots.json")
_SNAPSHOT_LOG_MAX_ENTRIES = 220  # keep the most recent N *recorded* dates (not calendar days) -
                                 # a bit above 30 so sparser-reporting crops still have room to
                                 # reach a real 30-point history even with reporting gaps
_UPSTASH_KEY = "cropiq:price_snapshots"


def _upstash_configured() -> bool:
    from app.core.config import get_settings
    s = get_settings()
    return bool(s.UPSTASH_REDIS_REST_URL and s.UPSTASH_REDIS_REST_TOKEN)


async def _load_snapshot_log() -> Dict[str, Dict[str, float]]:
    if _upstash_configured():
        from app.core.config import get_settings
        s = get_settings()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{s.UPSTASH_REDIS_REST_URL}/get/{_UPSTASH_KEY}",
                    headers={"Authorization": f"Bearer {s.UPSTASH_REDIS_REST_TOKEN}"},
                )
                resp.raise_for_status()
                result = resp.json().get("result")
                return json.loads(result) if result else {}
        except Exception as e:
            logger.error(f"Upstash read failed, treating snapshot log as empty for this call: {e}")
            return {}
    # Local file fallback (dev only - does not survive Render redeploys)
    try:
        with open(_SNAPSHOT_LOG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


async def _save_snapshot_log(log: Dict[str, Dict[str, float]]) -> None:
    """Trim by COUNT of recorded dates, not calendar age. Markets don't
    report every calendar day (weekends, holidays, and some crops are
    simply reported less often than others) - a calendar-day cutoff would
    silently shrink the usable history on any month with gaps, instead of
    consistently working toward a real N-point trend regardless of how many
    calendar days it actually took to collect them."""
    most_recent_dates = sorted(log.keys(), reverse=True)[:_SNAPSHOT_LOG_MAX_ENTRIES]
    trimmed = {d: log[d] for d in most_recent_dates}

    if _upstash_configured():
        from app.core.config import get_settings
        s = get_settings()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{s.UPSTASH_REDIS_REST_URL}/set/{_UPSTASH_KEY}",
                    headers={"Authorization": f"Bearer {s.UPSTASH_REDIS_REST_TOKEN}"},
                    content=json.dumps(trimmed),
                )
                resp.raise_for_status()
                return
        except Exception as e:
            logger.error(f"Upstash write failed - today's snapshot won't be persisted: {e}")
            return
    # Local file fallback (dev only)
    os.makedirs(os.path.dirname(_SNAPSHOT_LOG_PATH), exist_ok=True)
    with open(_SNAPSHOT_LOG_PATH, "w") as f:
        json.dump(trimmed, f)


_snapshot_lock = asyncio.Lock()


async def record_todays_snapshot_if_needed() -> None:
    """Record the latest live prices to the snapshot log, once per reported day.

    Keyed by Agmarknet's own reported date (records[...]['date']), NOT the
    server's system clock date - Agmarknet has real reporting lag (mandi
    arrivals from one day are commonly published as the next day's
    "current" price), so `date.today()` and the date the displayed prices
    actually correspond to can differ by a day. Keying by system date caused
    the log to record data under a date that didn't match what the Market
    page was showing for "today's price". Safe to call on every trend
    request - it's a no-op once that reported date is already recorded.
    """
    records = await get_all_prices()  # cheap: hits the dashboard cache if already fetched today
    if not records:
        return  # don't record a failed fetch as if it were a real (flat) day
    reported_date = next((r["date"] for r in records if r.get("date")), None) or date.today().isoformat()
    day_prices = {
        r["crop"]: r["price_per_quintal"]
        for r in records
        if r.get("crop") and r.get("price_per_quintal") is not None
    }
    if not day_prices:
        return
    async with _snapshot_lock:
        log = await _load_snapshot_log()
        if reported_date in log:
            return
        log[reported_date] = day_prices
        await _save_snapshot_log(log)


async def get_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Return the most recently recorded day's prices from the Redis-backed
    snapshot log (see _load_snapshot_log), as {"date": ..., "prices": {crop: price}}.

    Live requests to Agmarknet's dashboard-data API can fail at request time
    (rate limiting, transient outages, or the endpoint blocking a given
    server's IP) even though a daily cron job
    (record_todays_snapshot_if_needed, triggered via /market/cron/refresh-snapshot)
    has already written that day's - or a recent day's - real prices to
    Redis. Callers that need "today's price" but can tolerate it being the
    last successfully recorded day (rather than failing outright) should
    fall back to this instead of only relying on the live scraper.
    """
    log = await _load_snapshot_log()
    if not log:
        return None
    latest_date = max(log.keys())
    return {"date": latest_date, "prices": log[latest_date]}


async def get_local_price_history(commodity: str, days: int = 30) -> List[Dict[str, Any]]:
    """Read back the most recent `days` REAL recorded snapshots for
    `commodity` - by count, not calendar window. A crop that's reported
    less often than others (or hit by holidays/weekends) can still reach a
    full `days`-point history, it'll just span more calendar days to get
    there - which is exactly what should happen, rather than silently
    returning fewer points because a calendar cutoff excluded real data
    that was still there. Never fabricated."""
    log = await _load_snapshot_log()
    needle = commodity.lower().strip()

    matches = []
    for day_str, day_prices in log.items():
        match_price = next((p for name, p in day_prices.items() if needle in name.lower()), None)
        if match_price is not None:
            matches.append({"date": day_str, "price": match_price})

    matches.sort(key=lambda h: h["date"])
    return matches[-days:]


async def get_price_history(commodity: str, days: int = 30) -> List[Dict[str, Any]]:
    """DEPRECATED - do not use for new code.

    This looped over `days` calendar dates, sending each as the `date` field
    in the dashboard-data request, on the assumption that Agmarknet would
    return that date's historical snapshot. Confirmed in production that it
    doesn't: every requested date came back with the exact same price,
    meaning the endpoint ignores `date` for this purpose - it only ever
    reflects "today" vs "one day ago" relative to *now* (see the two real
    fields the raw record actually has: as_on_price, one_day_ago_price).
    There is no real multi-day history available from this endpoint.

    Kept only in case Agmarknet's API changes in the future. Callers wanting
    a trend today should use AgmarknetAPI.get_prices() directly and read
    price_per_quintal / price_1d_ago / price_change_pct - see
    agents.py::MarketAnalyzerAgent.handle_analyze_trends.
    """
    scraper = get_scraper()
    dates = [(date.today() - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    semaphore = asyncio.Semaphore(2)

    async def fetch_one(target_date: str) -> Optional[Dict[str, Any]]:
        async with semaphore:
            try:
                matches = await scraper.get_prices(commodity, target_date=target_date)
            except Exception as e:
                logger.warning(f"get_price_history: failed to fetch {target_date} for {commodity}: {e}")
                return None
        if matches and matches[0].get("price_per_quintal") is not None:
            return {"date": target_date, "price": matches[0]["price_per_quintal"]}
        return None

    results = await asyncio.gather(*(fetch_one(d) for d in dates))
    history = [r for r in results if r is not None]

    distinct_prices = {round(h["price"], 2) for h in history}
    if len(history) >= 5 and len(distinct_prices) <= 1:
        logger.warning(
            f"get_price_history('{commodity}'): all {len(history)} fetched days returned "
            f"the identical price {next(iter(distinct_prices), None)} - confirms this endpoint "
            "doesn't support historical date queries. This function is deprecated; see its docstring."
        )
        return []

    return history


# When run directly, this will test the scraper
if __name__ == "__main__":
    async def test():
        prices = await get_all_prices()
        print(json.dumps(prices, indent=2))

    asyncio.run(test())
