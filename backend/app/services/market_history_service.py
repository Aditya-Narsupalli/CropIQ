"""
Persistence layer for market price history.

Agmarknet only ever gives us "today's" price for each commodity - there's no
historical endpoint. This module is what turns that daily snapshot into a
rolling ~30-day series in Postgres:

- `save_daily_prices()`   upserts today's scraped prices (one row per
                            crop/location/day).
- `get_historical_prices()` reads back the last N days for a given crop, in
                            the {date, price} shape the frontend chart wants.
- `purge_expired_prices()` deletes rows older than the retention window so
                            the table never grows past ~30 days of history.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.core.db import get_session
from app.models.market import MarketPriceHistory

logger = logging.getLogger(__name__)
settings = get_settings()


def _parse_price_date(value: Optional[str]) -> date:
    """Records from the scraper carry an ISO date string (YYYY-MM-DD)."""
    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


async def save_daily_prices(prices: List[Dict[str, Any]]) -> int:
    """Upsert a batch of today's price records into market_price_history.

    Uses a Postgres ON CONFLICT DO UPDATE keyed on (crop, location,
    price_date) so re-fetching the same day's price just refreshes that row
    instead of piling up duplicates.

    Returns the number of rows written.
    """
    if not prices:
        return 0

    rows = []
    for p in prices:
        crop = (p.get("crop") or "").strip()
        if not crop:
            continue
        rows.append(
            {
                "crop": crop,
                "commodity_group": p.get("commodity_group"),
                "location": p.get("location") or "All India (Agmarknet)",
                "price_per_quintal": p.get("price_per_quintal"),
                "msp_price": p.get("msp_price"),
                "arrival_metric_tonnes": p.get("arrival_metric_tonnes"),
                "price_change_pct": p.get("price_change_pct"),
                "trend": p.get("trend"),
                "source": p.get("source") or "Agmarknet (Live)",
                "price_date": _parse_price_date(p.get("date")),
                "recorded_at": datetime.utcnow(),
            }
        )

    if not rows:
        return 0

    try:
        async with get_session() as session:
            stmt = pg_insert(MarketPriceHistory).values(rows)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_market_price_crop_location_date",
                set_={
                    "price_per_quintal": stmt.excluded.price_per_quintal,
                    "msp_price": stmt.excluded.msp_price,
                    "arrival_metric_tonnes": stmt.excluded.arrival_metric_tonnes,
                    "price_change_pct": stmt.excluded.price_change_pct,
                    "trend": stmt.excluded.trend,
                    "commodity_group": stmt.excluded.commodity_group,
                    "source": stmt.excluded.source,
                    "recorded_at": stmt.excluded.recorded_at,
                },
            )
            await session.execute(stmt)
            await session.commit()
        logger.info(f"Saved/updated {len(rows)} market price rows for {date.today().isoformat()}.")
        return len(rows)
    except Exception as e:
        logger.error(f"Failed to save daily market prices: {e}")
        return 0


async def get_historical_prices(crop: str, days: int = None) -> List[Dict[str, Any]]:
    """Return up to `days` worth of stored daily prices for `crop`, oldest
    first, as [{"date": "YYYY-MM-DD", "price": float}, ...] - exactly the
    shape the frontend's 30-day trend chart expects."""
    days = days or settings.PRICE_HISTORY_RETENTION_DAYS
    cutoff = date.today() - timedelta(days=days)
    needle = crop.strip().lower()

    try:
        async with get_session() as session:
            result = await session.execute(
                select(MarketPriceHistory)
                .where(MarketPriceHistory.price_date >= cutoff)
                .where(MarketPriceHistory.crop.ilike(f"%{needle}%"))
                .order_by(MarketPriceHistory.price_date.asc())
            )
            rows = result.scalars().all()
            return [r.to_history_point() for r in rows if r.price_per_quintal is not None]
    except Exception as e:
        logger.error(f"Failed to read historical prices for '{crop}': {e}")
        return []


async def purge_expired_prices(days: int = None) -> int:
    """Delete rows older than the retention window (default 30 days) so the
    table only ever holds a rolling last-month of data."""
    days = days or settings.PRICE_HISTORY_RETENTION_DAYS
    cutoff = date.today() - timedelta(days=days)

    try:
        async with get_session() as session:
            result = await session.execute(
                delete(MarketPriceHistory).where(MarketPriceHistory.price_date < cutoff)
            )
            await session.commit()
            deleted = result.rowcount or 0
        if deleted:
            logger.info(f"Purged {deleted} expired market price rows older than {cutoff.isoformat()}.")
        return deleted
    except Exception as e:
        logger.error(f"Failed to purge expired market prices: {e}")
        return 0
