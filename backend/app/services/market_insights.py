"""
Market analysis built only from real data: today's live Agmarknet feed
(price, previous-day price, MSP) and the real recorded daily history
(market_scraper.get_local_price_history - placeholder dates excluded).

Nothing here forecasts prices. The signals describe what has actually
happened, with a confidence that reflects how much real history exists, and
the advice is phrased as considerations, not instructions.
"""
import statistics
from typing import Any, Dict, List, Optional

from app.services.market_scraper import get_all_prices

# A move smaller than this over the recorded window is treated as "stable"
TREND_THRESHOLD_PCT = 3.0


def _confidence(real_days: int) -> str:
    if real_days < 5:
        return "none"
    if real_days < 15:
        return "low"
    if real_days < 30:
        return "medium"
    return "high"


def analyze_trend_signal(history: List[Dict[str, Any]], msp: Optional[float] = None) -> Dict[str, Any]:
    """Summarise a real price history into a trend signal.

    - trend_score: % change from the average of the first few recorded days
      to the average of the last few (averaging damps single-day noise).
    - range_position: where the latest price sits between the lowest (0)
      and highest (100) recorded price.
    - volatility: typical day-to-day move, as %.
    """
    prices = [h["price"] for h in history if h.get("price")]
    real_days = len(prices)
    result: Dict[str, Any] = {"real_days": real_days, "confidence": _confidence(real_days)}
    if real_days < 2:
        return result

    window = max(1, min(5, real_days // 3))
    start, end = statistics.mean(prices[:window]), statistics.mean(prices[-window:])
    trend_score = round((end - start) / start * 100, 1)
    low, high, latest = min(prices), max(prices), prices[-1]
    range_position = round((latest - low) / (high - low) * 100) if high > low else 50
    daily_moves = [abs(b - a) / a * 100 for a, b in zip(prices, prices[1:]) if a]
    volatility = round(statistics.mean(daily_moves), 1) if daily_moves else 0.0

    label = "Upward" if trend_score > TREND_THRESHOLD_PCT else "Downward" if trend_score < -TREND_THRESHOLD_PCT else "Stable"
    result.update({
        "trend_score": trend_score,
        "trend_label": label,
        "period": f"{history[0]['date']} to {history[-1]['date']}",
        "latest_price": latest,
        "recorded_low": low,
        "recorded_high": high,
        "range_position": range_position,
        "volatility_pct": volatility,
        "advisory": _advisory(label, range_position, latest, msp, result["confidence"]),
    })
    return result


def _advisory(label: str, range_position: int, latest: float, msp: Optional[float], confidence: str) -> str:
    """Plain-language considerations for a farmer deciding when to sell."""
    parts = []
    if msp and latest < msp:
        parts.append(
            f"The market price is below the MSP (₹{msp:,.0f}). If government procurement is open in your "
            "area, selling at a procurement centre may get you a better price - check with your local "
            "APMC or agriculture office."
        )
    if label == "Upward" and range_position >= 70:
        parts.append("Prices have been rising and are near the top of their recorded range - a reasonable "
                     "time to consider selling at least part of your stock.")
    elif label == "Upward":
        parts.append("Prices have been rising. If you can store your produce safely, watching for a few more "
                     "days may help, but trends can reverse.")
    elif label == "Downward" and range_position <= 30:
        parts.append("Prices have been falling and are near the bottom of their recorded range. If you can store "
                     "safely and don't need cash immediately, selling in smaller lots over time spreads the risk.")
    elif label == "Downward":
        parts.append("Prices have been falling. Selling in smaller lots over time can reduce the risk of "
                     "selling everything at a low.")
    else:
        parts.append("Prices have been fairly stable, so timing matters less - storage and transport costs "
                     "may outweigh waiting.")
    if confidence in ("none", "low"):
        parts.append("This is based on only a few recorded days, so treat it as a rough indication.")
    parts.append("These are all-India averages - check your local mandi rate before selling.")
    return " ".join(parts)


async def get_market_insights() -> Dict[str, Any]:
    """Today's market at a glance: biggest movers and price vs MSP."""
    records = await get_all_prices()
    priced = [r for r in records if r.get("price_per_quintal")]

    movers = sorted(
        (r for r in priced if r.get("price_change_pct") is not None),
        key=lambda r: r["price_change_pct"],
    )

    def mover(r):
        return {"crop": r["crop"], "price": r["price_per_quintal"], "change_pct": r["price_change_pct"]}

    gainers = [mover(r) for r in reversed(movers) if r["price_change_pct"] > 0][:3]
    losers = [mover(r) for r in movers if r["price_change_pct"] < 0][:3]

    msp_comparison = []
    for r in priced:
        msp = r.get("msp_price")
        if not msp:
            continue
        gap = (r["price_per_quintal"] - msp) / msp * 100
        msp_comparison.append({
            "crop": r["crop"],
            "price": r["price_per_quintal"],
            "msp": msp,
            "gap_pct": round(gap, 1),
        })
    msp_comparison.sort(key=lambda m: m["gap_pct"])

    return {
        "date": max((r["date"] for r in priced), default=None),
        "gainers": gainers,
        "losers": losers,
        "msp_comparison": msp_comparison,
        "below_msp": [m for m in msp_comparison if m["gap_pct"] < 0],
        "source": "Agmarknet all-India averages",
    }
