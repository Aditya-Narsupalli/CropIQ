"""
Checks exactly what's currently stored in Upstash under cropiq:price_snapshots -
how many days, the date range, and how many days match a few sample crops.
Run from backend/ with your venv active (needs the same .env with
UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN set):

    python check_upstash_snapshot.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_scraper import _load_snapshot_log, _upstash_configured, get_local_price_history  # noqa: E402


async def main():
    print(f"Upstash configured: {_upstash_configured()}")
    log = await _load_snapshot_log()
    print(f"Total days stored: {len(log)}")
    if log:
        dates = sorted(log.keys())
        print(f"Earliest date: {dates[0]}")
        print(f"Latest date: {dates[-1]}")
        print()
        print("Sample of stored dates (first 5, last 5):")
        for d in dates[:5]:
            print(f"  {d}: {len(log[d])} crops")
        print("  ...")
        for d in dates[-5:]:
            print(f"  {d}: {len(log[d])} crops")
    else:
        print("STORE IS EMPTY - nothing is saved under this key right now.")
        return

    print()
    print("Match counts for a few sample crops (via get_local_price_history):")
    for crop in ["Rice", "Wheat", "Cotton", "Cotton(Lint)", "Onion", "Sunflower", "Sunflower/Sunflower Seed"]:
        history = await get_local_price_history(crop, days=200)
        span = f"{history[0]['date']} to {history[-1]['date']}" if history else "no matches"
        print(f"  {crop!r}: {len(history)} days ({span})")


if __name__ == "__main__":
    asyncio.run(main())
