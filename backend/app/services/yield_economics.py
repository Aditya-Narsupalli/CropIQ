"""
Turns a yield prediction into money: expected revenue, cultivation cost and
profit, using live Agmarknet prices (see market_scraper.py) with a static
MSP/FRP fallback when the live feed is unavailable.

Units: prices are Rs/quintal (as Agmarknet and MSP announcements quote them),
production is tonnes. 1 tonne = 10 quintals.
"""
import asyncio
import logging
from typing import Dict, Optional

from app.services.market_scraper import get_all_prices
from app.services.agronomy import typical_inputs

logger = logging.getLogger(__name__)

# Frontend crop label -> (Agmarknet commodity name, tonnes of marketed
# produce per tonne of predicted yield).
# Rice: the yield data is in milled-rice terms but farmers sell paddy, at a
# standard ~67% milling outturn, so 1 t rice ~= 1/0.67 t paddy.
CROP_MARKET = {
    "Rice": ("Paddy(Common)", 1 / 0.67),
    "Jowar": ("Jowar(Sorghum)", 1.0),
    "Bajra": ("Bajra(Pearl Millet/Cumbu)", 1.0),
    "Maize": ("Maize", 1.0),
    "Ragi": ("Ragi(Finger Millet)", 1.0),
    "Wheat": ("Wheat", 1.0),
    "Gram": ("Bengal Gram(Gram)(Whole)", 1.0),
    "Tur": ("Red gram/Arhar/Tur(whole)", 1.0),
    "Groundnut": ("Groundnut", 1.0),
    "Sunflower": ("Sunflower/Sunflower Seed", 1.0),
    "Soyabean": ("Soyabean", 1.0),
    "Safflower": ("Safflower", 1.0),
    "Nigerseed": ("Niger Seed(Ramtil)", 1.0),
    "Cotton": ("Cotton", 1.0),
    "Sugarcane": ("Sugarcane", 1.0),
    "Potato": ("Potato", 1.0),
    "Onion": ("Onion", 1.0),
}

# Fallback Rs/quintal when the live feed is down or has no price for the crop:
# MSPs as reported by Agmarknet on 2026-10-01; sugarcane uses the 2025-26 FRP;
# potato/onion (no MSP) use that day's all-India average.
FALLBACK_PRICE = {
    "Paddy(Common)": (2441, "MSP"),
    "Jowar(Sorghum)": (4023, "MSP"),
    "Bajra(Pearl Millet/Cumbu)": (2900, "MSP"),
    "Maize": (2410, "MSP"),
    "Ragi(Finger Millet)": (5205, "MSP"),
    "Wheat": (2585, "MSP"),
    "Bengal Gram(Gram)(Whole)": (5875, "MSP"),
    "Red gram/Arhar/Tur(whole)": (8450, "MSP"),
    "Groundnut": (7517, "MSP"),
    "Sunflower/Sunflower Seed": (8343, "MSP"),
    "Soyabean": (5708, "MSP"),
    "Safflower": (6540, "MSP"),
    "Niger Seed(Ramtil)": (10052, "MSP"),
    "Cotton": (8267, "MSP"),
    "Sugarcane": (355, "FRP"),
    "Potato": (620, "recent average"),
    "Onion": (3412, "recent average"),
}

# Approximate paid-out cultivation cost per hectare (Rs), in the spirit of
# CACP's A2+FL cost concept: seed, fertilizer, plant protection, hired and
# family labour, machinery, irrigation. These are rough national-level
# figures - farm costs vary a lot, which is why the UI lets the farmer
# overwrite this with their own number.
TYPICAL_COST_PER_HA = {
    "Rice": 60000, "Jowar": 40000, "Bajra": 32000, "Maize": 48000, "Ragi": 45000,
    "Wheat": 50000, "Gram": 38000, "Tur": 42000, "Groundnut": 62000, "Sunflower": 40000,
    "Soyabean": 42000, "Safflower": 30000, "Nigerseed": 25000, "Cotton": 78000,
    "Sugarcane": 160000, "Potato": 125000, "Onion": 105000,
}

# Marginal input costs, so the what-if sliders show that more fertilizer or
# spraying isn't free. Blended fertilizer (urea/DAP/MOP mix) ~Rs 20/kg;
# plant-protection chemicals ~Rs 600 per kg or litre.
FERTILIZER_COST_PER_KG = 20
PESTICIDE_COST_PER_UNIT = 600

LIVE_PRICE_TIMEOUT_S = 6


async def get_crop_price(crop: str) -> Optional[Dict]:
    """Price for the crop's marketed produce: live Agmarknet all-India
    average if available, else the fallback table. None if the crop has no
    market mapping (e.g. "Other Vegetables")."""
    market = CROP_MARKET.get(crop)
    if not market:
        return None
    commodity, conversion = market

    try:
        records = await asyncio.wait_for(get_all_prices(), timeout=LIVE_PRICE_TIMEOUT_S)
    except Exception as e:  # timeout or network error - fall back quietly
        logger.warning(f"Live price lookup failed for {crop}: {e}")
        records = []

    live = next((r for r in records if r.get("crop") == commodity), None)
    if live and live.get("price_per_quintal"):
        return {
            "price_per_quintal": live["price_per_quintal"],
            "commodity": commodity,
            "conversion": conversion,
            "source": "Agmarknet all-India average",
            "date": live.get("date"),
        }

    price, kind = FALLBACK_PRICE[commodity]
    return {
        "price_per_quintal": float(price),
        "commodity": commodity,
        "conversion": conversion,
        "source": kind,
        "date": None,
    }


def compute_economics(crop: str, production_t: float, area_ha: float, price_per_quintal: float,
                      conversion: float, cost_per_ha: Optional[float], fertilizer: float, pesticide: float,
                      production_low_t: Optional[float] = None, production_high_t: Optional[float] = None) -> Dict:
    """Revenue, cost and profit for the whole farm.
    cost_per_ha is the farmer's cost at typical input levels; it's adjusted
    for how far their fertilizer/pesticide use is from typical."""
    rs_per_tonne = price_per_quintal * 10 * conversion
    if cost_per_ha is None:
        cost_per_ha = TYPICAL_COST_PER_HA.get(crop)

    revenue = production_t * rs_per_tonne
    result = {
        "revenue": revenue,
        "revenue_low": production_low_t * rs_per_tonne if production_low_t is not None else None,
        "revenue_high": production_high_t * rs_per_tonne if production_high_t is not None else None,
        "marketed_production_t": production_t * conversion,
        "base_cost_per_ha": cost_per_ha,
        "cost": None,
        "profit": None,
        "profit_per_ha": None,
    }
    if cost_per_ha is not None:
        typical = typical_inputs(crop)
        input_adjustment = ((fertilizer - typical["fertilizer"]) * FERTILIZER_COST_PER_KG +
                            (pesticide - typical["pesticide"]) * PESTICIDE_COST_PER_UNIT)
        cost = max(0.0, cost_per_ha + input_adjustment) * area_ha
        result.update({
            "cost": cost,
            "profit": revenue - cost,
            "profit_per_ha": (revenue - cost) / area_ha if area_ha else None,
        })
    return result
