"""
Adds mock historical data for ALL 24 crops your live app currently reports
(the new Agmarknet naming scheme, e.g. "Bajra(Pearl Millet/Cumbu)",
"Sunflower/Sunflower Seed", etc.) going back 177 days, anchored to their
real 2026-08-13 prices so the walk connects smoothly into real data.

This MERGES into whatever's already in your store (local file or Upstash,
whichever is currently configured) rather than replacing it:
- Existing dates keep all their existing crop entries untouched.
- New crop entries are added to each date (old dates get the new-naming
  crops added alongside whatever old-naming crops are already there).
- Your real recorded days (2026-08-12, 08-13, 08-14) are never touched.

Run from backend/:
    python -m app.data.add_current_crops_mock_history
"""
import asyncio
import random
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.market_scraper import _load_snapshot_log, _save_snapshot_log, _upstash_configured  # noqa: E402

# Real prices from 2026-08-13 - the anchor point the backward walk starts from.
ANCHOR_PRICES = {
    "Bajra(Pearl Millet/Cumbu)": 2163.87, "Barley(Jau)": 2280.42, "Jowar(Sorghum)": 5133.12,
    "Maize": 2081.25, "Paddy(Common)": 2940.58, "Ragi(Finger Millet)": 3397.92,
    "Wheat": 2570.61, "Cotton": 8677.69, "Copra": 21006.14, "Groundnut": 7084.95,
    "Mustard": 7453.93, "Niger Seed(Ramtil)": 8000.0, "Safflower": 5254.32,
    "Sesamum(Sesame,Gingelly,Til)": 11894.89, "Soyabean": 6478.08,
    "Sunflower/Sunflower Seed": 8111.49, "Bengal Gram(Gram)(Whole)": 6108.71,
    "Black Gram(Urd Beans)(Whole)": 8644.3, "Green Gram(Moong)(Whole)": 7396.03,
    "Lentil(Masur)(Whole)": 7943.84, "Red gram/Arhar/Tur(whole)": 7387.13,
    "Onion": 2134.1, "Potato": 659.35, "Tomato": 2010.87,
}
ANCHOR_DATE = date(2026, 8, 13)


def generate_mock_history(days: int = 177, seed: int = 7) -> dict:
    """Backward random walk from ANCHOR_DATE - 1 day, for `days` days."""
    rng = random.Random(seed)
    log = {}
    for crop, anchor_price in ANCHOR_PRICES.items():
        price = anchor_price
        for i in range(1, days + 1):
            d = (ANCHOR_DATE - timedelta(days=i)).isoformat()
            pct_move = rng.gauss(0, 0.012)
            price = max(price * (1 - pct_move), 1)  # walking backward
            log.setdefault(d, {})[crop] = round(price, 2)
    return log


async def main():
    print(f"Storage backend: {'Upstash Redis' if _upstash_configured() else 'local file'}")

    mock_log = generate_mock_history(days=177)
    existing = await _load_snapshot_log()

    added_dates = 0
    added_entries = 0
    for d, crops in mock_log.items():
        if d not in existing:
            existing[d] = {}
            added_dates += 1
        for crop, price in crops.items():
            if crop not in existing[d]:  # never overwrite a real entry
                existing[d][crop] = price
                added_entries += 1

    await _save_snapshot_log(existing)

    reloaded = await _load_snapshot_log()
    print(f"New dates added: {added_dates}")
    print(f"New crop entries added: {added_entries}")
    print(f"Total days in store now: {len(reloaded)}")
    print(f"Range: {min(reloaded.keys())} to {max(reloaded.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
