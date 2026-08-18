"""
Seeds `price_snapshots.json` with 28 days of MOCK price data, filling the
gap behind whatever real day(s) you already have (it explicitly skips
"yesterday" and "today" so it never collides with or overwrites real data) -
so the log reaches a full 30-day window immediately: 28 mock + 1 real
(yesterday) + 1 real (today, once your app records it) = 30.

This is placeholder data only. As the app keeps running, each new real day
gets added and the *oldest* day (always mock data first, since mock data
is placed furthest back) gets dropped once the window is full - so within
28 days of normal use, every mock entry will have been pushed out and
replaced by real Agmarknet data, with zero manual intervention.

Run once from backend/:
    python -m app.data.seed_mock_price_history
"""
import json
import os
import random
from datetime import date, timedelta

_SNAPSHOT_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_snapshots.json")

# Rough, illustrative base prices (INR per quintal) for commonly searched
# crops in this app - NOT real historical data, just plausible starting
# points so the mock trend looks like a realistic market instead of a
# random scribble.
BASE_PRICES = {
    "Rice": 2100, "Wheat": 2200, "Onion": 1500, "Potato": 1200, "Tomato": 1600,
    "Cotton(Lint)": 6500, "Sugarcane": 320, "Maize": 1900, "Jowar": 2500,
    "Bajra": 2100, "Soyabean": 4200, "Sunflower": 6000, "Groundnut": 7200,
    "Paddy(Common)": 2500, "Bengal Gram(Gram)(Whole)": 6300, "Rapeseed &Mustard": 5300,
    "Turmeric": 8000, "Dry Chillies": 12000, "Coriander": 7000, "Garlic": 4000,
    "Ginger": 5000, "Banana": 1800, "Arhar/Tur": 7000, "Moong(Green Gram)": 7500,
    "Urad": 7000, "Masoor": 6000, "Ragi": 3400, "Safflower": 5800, "Tobacco": 15000,
    "Niger Seed": 7800, "Sesamum": 12000, "Castor Seed": 6200, "Jute": 4800,
    "Mesta": 4600, "Barley": 1900, "Small Millets": 3200, "Horse-Gram": 5500,
}


def generate_mock_history(days: int = 28, skip_recent_days: int = 2, seed: int = 42) -> dict:
    """Generate `days` days of mock data, ending `skip_recent_days` days
    before today. Default skips the most recent 2 days (yesterday + today) -
    those are expected to already be real, or about to be recorded live -
    so the mock data fills in exactly the gap behind them instead of
    colliding with real dates."""
    rng = random.Random(seed)
    log = {}
    for crop, base_price in BASE_PRICES.items():
        price = base_price
        crop_series = {}
        for i in range(skip_recent_days + days, skip_recent_days, -1):
            d = (date.today() - timedelta(days=i)).isoformat()
            pct_move = rng.gauss(0, 0.012)  # ~1.2% std dev daily move
            price = max(price * (1 + pct_move), 1)
            crop_series[d] = round(price, 2)
        for d, p in crop_series.items():
            log.setdefault(d, {})[crop] = p
    return log


def main():
    mock_log = generate_mock_history(days=28, skip_recent_days=2)

    existing = {}
    if os.path.exists(_SNAPSHOT_LOG_PATH):
        try:
            with open(_SNAPSHOT_LOG_PATH, "r") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            existing = {}

    # Never overwrite a real (already-recorded) day - only fill in the
    # mock dates that aren't already present (i.e. don't clobber today's
    # real entry if your app already ran and recorded it).
    merged = {**mock_log, **existing}

    with open(_SNAPSHOT_LOG_PATH, "w") as f:
        json.dump(merged, f, indent=2)

    print(f"Seeded {len(mock_log)} mock days x {len(BASE_PRICES)} crops into {_SNAPSHOT_LOG_PATH}")
    print(f"Total days now in log: {len(merged)}")
    print("These mock days will be pushed out and replaced by real recorded "
          "days automatically as the app keeps running (oldest day drops "
          "once the log has 30 entries for a given crop).")


if __name__ == "__main__":
    main()
