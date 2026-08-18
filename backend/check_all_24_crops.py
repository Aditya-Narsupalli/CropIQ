"""
Checks all 24 crops individually against whatever store is actually
configured (Upstash if env vars are set, else the local file) - to find
out precisely which crops are missing coverage and why.

Run from backend/:
    python check_all_24_crops.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.market_scraper import _load_snapshot_log, _upstash_configured, get_local_price_history  # noqa: E402

ALL_24_CROPS = [
    "Bajra(Pearl Millet/Cumbu)", "Barley(Jau)", "Jowar(Sorghum)", "Maize",
    "Paddy(Common)", "Ragi(Finger Millet)", "Wheat", "Cotton", "Copra",
    "Groundnut", "Mustard", "Niger Seed(Ramtil)", "Safflower",
    "Sesamum(Sesame,Gingelly,Til)", "Soyabean", "Sunflower/Sunflower Seed",
    "Bengal Gram(Gram)(Whole)", "Black Gram(Urd Beans)(Whole)",
    "Green Gram(Moong)(Whole)", "Lentil(Masur)(Whole)",
    "Red gram/Arhar/Tur(whole)", "Onion", "Potato", "Tomato",
]


async def main():
    print(f"Upstash configured: {_upstash_configured()}")
    log = await _load_snapshot_log()
    print(f"Total days in store: {len(log)}")
    if log:
        dates = sorted(log.keys())
        print(f"Date range: {dates[0]} to {dates[-1]}")

        # Show how many dates actually contain a "Sunflower/Sunflower Seed"
        # key literally, vs how many get_local_price_history matches via
        # substring - to catch a naming/substring mismatch directly.
        exact_key_count = sum(1 for d in log.values() if "Sunflower/Sunflower Seed" in d)
        print(f"\nDates with EXACT key 'Sunflower/Sunflower Seed': {exact_key_count}")

        # Show a raw sample of what keys actually exist on 3 different dates
        # spread across the store, so we can see real key names directly.
        sample_dates = [dates[0], dates[len(dates)//2], dates[-1]]
        print("\nRaw crop keys on 3 sample dates:")
        for d in sample_dates:
            print(f"  {d}: {sorted(log[d].keys())}")
    print()

    print(f"Checking all {len(ALL_24_CROPS)} crops via get_local_price_history:\n")
    for crop in ALL_24_CROPS:
        history = await get_local_price_history(crop, days=200)
        n = len(history)
        span = f"{history[0]['date']} to {history[-1]['date']}" if history else "NO DATA"
        status = "OK" if n >= 150 else "SHORT"
        print(f"  [{status}] {crop!r}: {n} days ({span})")


if __name__ == "__main__":
    asyncio.run(main())
