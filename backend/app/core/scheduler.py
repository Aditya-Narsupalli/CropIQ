"""
Background job that builds the 30-day price history.

Agmarknet's public API only ever returns "today's" price per commodity -
there's no history endpoint. So to have anything to chart, this app has to
take its own daily snapshot and accumulate it in Postgres over time. This
module runs that snapshot on a timer (default: once every 24h, immediately
on startup) and prunes rows past the retention window on every pass.
"""
import asyncio
import logging

from app.core.config import get_settings
from app.services.market_scraper import get_all_prices
from app.services.market_history_service import purge_expired_prices, save_daily_prices

logger = logging.getLogger(__name__)
settings = get_settings()


async def collect_and_store_prices_once() -> None:
    """Fetch today's live prices for every commodity and upsert them, then
    purge anything past the 30-day retention window."""
    try:
        prices = await get_all_prices()
        saved = await save_daily_prices(prices)
        purged = await purge_expired_prices()
        logger.info(f"Price collection run complete: saved={saved}, purged={purged}.")
    except Exception as e:
        logger.error(f"Price collection run failed: {e}")


async def price_collection_loop() -> None:
    """Run `collect_and_store_prices_once` immediately, then on a fixed
    interval (default: daily) for as long as the app is running."""
    interval = max(settings.PRICE_COLLECTION_INTERVAL_SECONDS, 60)
    while True:
        await collect_and_store_prices_once()
        await asyncio.sleep(interval)


def start_price_collection_task() -> asyncio.Task:
    """Kick off the background loop as a fire-and-forget asyncio task."""
    return asyncio.create_task(price_collection_loop())
