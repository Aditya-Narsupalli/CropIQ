"""
Tools the CropIQ chat assistant can call (Gemini function calling).

Instead of guessing from English keywords whether a message needs live data
(which missed every Hindi/regional-language question and every follow-up like
"and tomorrow?"), the model itself decides when to call these - in any
language, with the whole conversation in view. A tool only costs an extra
model round-trip when the question actually needs it.

Every tool returns a small JSON-able dict. Figures are pre-formatted where
the model is likely to quote them, so the answer can repeat them exactly.
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from google.genai import types

from app.services.market_scraper import get_all_prices, get_latest_snapshot

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_S = 8


async def _get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET with one quick retry - Open-Meteo occasionally returns a
    transient 502/503, which shouldn't cost the farmer their forecast."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        for attempt in range(2):
            r = await client.get(url, params=params)
            if r.status_code >= 500 and attempt == 0:
                await asyncio.sleep(0.7)
                continue
            r.raise_for_status()
            return r.json()

# --- Market prices -----------------------------------------------------------

# Common names (English, Hindi/regional transliterations) -> Agmarknet
# commodity name. The model is asked to pass English crop names, but farmers'
# words leak through ("dhan", "chana", "sarson"), so both are covered.
COMMODITY_ALIASES = {
    "Paddy(Common)": ["paddy", "rice", "dhan", "dhaan", "chawal", "bhat"],
    "Wheat": ["wheat", "gehu", "gehun", "gahu"],
    "Maize": ["maize", "corn", "makka", "makai"],
    "Bajra(Pearl Millet/Cumbu)": ["bajra", "pearl millet", "cumbu", "sajje"],
    "Jowar(Sorghum)": ["jowar", "sorghum", "jola", "cholam"],
    "Ragi(Finger Millet)": ["ragi", "finger millet", "nachni", "mandua"],
    "Barley(Jau)": ["barley", "jau", "jow"],
    "Bengal Gram(Gram)(Whole)": ["gram", "bengal gram", "chana", "chickpea", "harbhara", "kadale"],
    "Red gram/Arhar/Tur(whole)": ["tur", "toor", "arhar", "red gram", "pigeon pea", "tuvar"],
    "Green Gram(Moong)(Whole)": ["moong", "mung", "green gram", "hesaru"],
    "Black Gram(Urd Beans)(Whole)": ["urad", "urd", "black gram", "uddu"],
    "Lentil(Masur)(Whole)": ["lentil", "masur", "masoor"],
    "Groundnut": ["groundnut", "peanut", "moongphali", "mungfali", "shenga", "kadalai"],
    "Mustard": ["mustard", "sarson", "rapeseed", "rai", "mohari"],
    "Soyabean": ["soyabean", "soybean", "soya"],
    "Sunflower/Sunflower Seed": ["sunflower", "surajmukhi"],
    "Safflower": ["safflower", "kardai", "kusum"],
    "Sesamum(Sesame,Gingelly,Til)": ["sesame", "sesamum", "til", "gingelly", "ellu"],
    "Niger Seed(Ramtil)": ["niger", "nigerseed", "niger seed", "ramtil", "karale"],
    "Copra": ["copra", "coconut", "nariyal"],
    "Cotton": ["cotton", "kapas", "kapus", "narma"],
    "Sugarcane": ["sugarcane", "ganna", "oos", "kabbu"],
    "Onion": ["onion", "pyaz", "pyaj", "kanda", "vengayam", "ulli"],
    "Potato": ["potato", "aloo", "alu", "batata", "urulai"],
    "Tomato": ["tomato", "tamatar", "takkali"],
}
_ALIAS_TO_COMMODITY = {alias: name for name, aliases in COMMODITY_ALIASES.items() for alias in aliases}


def resolve_commodity(query: str) -> Optional[str]:
    """Map a crop name in any common form to its Agmarknet commodity name.
    Whole-alias matching only - substring matching is what used to turn
    "gram" into four different pulses and "rice" into nothing."""
    q = re.sub(r"[^a-z ]+", " ", (query or "").lower()).strip()
    if not q:
        return None
    if q in _ALIAS_TO_COMMODITY:
        return _ALIAS_TO_COMMODITY[q]
    # Multi-word input ("today's onion rate", "red gram price"): prefer the
    # longest alias that appears as whole words.
    for alias in sorted(_ALIAS_TO_COMMODITY, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", q):
            return _ALIAS_TO_COMMODITY[alias]
    return None


async def get_market_prices(commodity: str) -> Dict[str, Any]:
    """Today's all-India average mandi price for one commodity."""
    name = resolve_commodity(commodity)
    if not name:
        return {
            "found": False,
            "message": f"'{commodity}' isn't one of the commodities CropIQ tracks.",
            "available_commodities": sorted(COMMODITY_ALIASES),
        }

    try:
        records = await asyncio.wait_for(get_all_prices(), timeout=10)
    except Exception as e:
        logger.warning(f"Live Agmarknet fetch failed in chat tool: {e}")
        records = []

    live = next((r for r in records if r.get("crop") == name), None)
    if live and live.get("price_per_quintal"):
        result = {
            "found": True,
            "commodity": name,
            "price_per_quintal": f"₹{live['price_per_quintal']:,.0f}",
            "date": live.get("date"),
            "scope": "all-India average across reporting mandis (not a specific local mandi)",
            "source": "Agmarknet (live)",
        }
        if live.get("price_change_pct") is not None:
            result["change_vs_previous_day"] = f"{live['price_change_pct']:+.1f}%"
        if live.get("msp_price"):
            result["msp_per_quintal"] = f"₹{live['msp_price']:,.0f}"
        return result

    # Live request failed or had no price today - fall back to the last
    # daily snapshot (same store the market trend chart uses).
    try:
        snapshot = await get_latest_snapshot()
    except Exception as e:
        logger.warning(f"Snapshot fallback failed in chat tool: {e}")
        snapshot = None
    price = (snapshot or {}).get("prices", {}).get(name)
    if price:
        return {
            "found": True,
            "commodity": name,
            "price_per_quintal": f"₹{price:,.0f}",
            "date": snapshot["date"],
            "scope": "all-India average across reporting mandis",
            "source": "Agmarknet (last saved snapshot - today's live data unavailable)",
        }
    return {"found": False, "commodity": name, "message": "No price is available for this commodity right now."}


# --- Weather forecast --------------------------------------------------------

async def _geocode(place: str) -> Optional[Dict[str, Any]]:
    """Free-text Indian place -> coordinates via Open-Meteo's geocoder (no API key)."""
    parts = [p.strip() for p in place.split(",") if p.strip()]
    if not parts:
        return None
    data = await _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": parts[0], "count": 10, "countryCode": "IN", "language": "en"},
    )
    results = data.get("results") or []
    if not results:
        return None
    # "Nashik, Maharashtra": prefer the match in the named state/district
    hints = [p.lower() for p in parts[1:]]
    for res in results:
        admin = " ".join(str(res.get(k, "")) for k in ("admin1", "admin2", "admin3")).lower()
        if any(h in admin for h in hints):
            return res
    return results[0]


async def get_weather_forecast(latitude: Optional[float], longitude: Optional[float],
                               location_label: Optional[str], place: Optional[str] = None) -> Dict[str, Any]:
    """Current conditions plus a 7-day daily forecast from Open-Meteo."""
    label = location_label
    try:
        if place:
            geo = await _geocode(place)
            if not geo:
                return {"error": f"Couldn't find the place '{place}'. Ask the user for their district and state."}
            latitude, longitude = geo["latitude"], geo["longitude"]
            label = ", ".join(str(geo[k]) for k in ("name", "admin2", "admin1") if geo.get(k))
        elif latitude is None or longitude is None:
            if not location_label:
                return {"error": "The user hasn't shared a location. Ask for their village/district and state, "
                                 "or suggest turning on location in the chat."}
            return await get_weather_forecast(None, None, location_label, place=location_label)

        data = await _get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 7,
            "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "precipitation_probability_max,wind_speed_10m_max",
        })
    except Exception as e:
        logger.warning(f"Weather forecast tool failed: {e}")
        return {"error": "The weather service couldn't be reached right now."}

    cur, daily = data.get("current", {}), data.get("daily", {})
    days = []
    for i, date in enumerate(daily.get("time", [])):
        day = datetime.strptime(date, "%Y-%m-%d")
        days.append({
            "date": f"{day.strftime('%a')} {day.day} {day.strftime('%b')}",
            "temp_c": f"{daily['temperature_2m_min'][i]:.0f}–{daily['temperature_2m_max'][i]:.0f}",
            "rain_mm": daily["precipitation_sum"][i],
            "rain_chance_pct": daily["precipitation_probability_max"][i],
            "max_wind_kmh": daily["wind_speed_10m_max"][i],
        })
    return {
        "location": label or f"{latitude:.3f}, {longitude:.3f}",
        "now": {
            "temp_c": cur.get("temperature_2m"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "rain_mm": cur.get("precipitation"),
            "wind_kmh": cur.get("wind_speed_10m"),
        },
        "next_7_days": days,
        "source": "Open-Meteo",
        "spraying_note": "Spraying is usually best on dry days with wind under ~15 km/h and no rain expected for "
                         "several hours afterwards.",
    }


# --- Yield & income estimate -------------------------------------------------

YIELD_CROPS = [
    "Rice", "Wheat", "Maize", "Jowar", "Bajra", "Ragi", "Gram", "Tur", "Groundnut", "Soyabean",
    "Sunflower", "Safflower", "Nigerseed", "Cotton", "Sugarcane", "Potato", "Onion", "Tobacco",
]
YIELD_STATES = [
    "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
    "Jammu And Kashmir", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
]


def _current_season() -> str:
    month = datetime.now().month
    if 6 <= month <= 10:
        return "Kharif"
    if month >= 11 or month <= 2:
        return "Rabi"
    return "Summer"


def _inr(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    if abs(value) >= 1e5:
        return f"₹{value / 1e5:.2f} lakh"
    return f"₹{value:,.0f}"


async def estimate_yield_and_income(crop: str, area: float, state: str, area_unit: str = "acres",
                                    district: Optional[str] = None, season: Optional[str] = None,
                                    latitude: Optional[float] = None, longitude: Optional[float] = None) -> Dict[str, Any]:
    """Run CropIQ's yield predictor with typical soil/input values, plus income."""
    # Imported here: the yield service loads the ML model at import time.
    from app.models.yield_model import YieldInput
    from app.services.yield_prediction_service import predict_yield_detailed
    from app.services.agronomy import typical_inputs
    from app.services.yield_economics import get_crop_price, compute_economics

    if crop not in YIELD_CROPS:
        return {"error": f"Yield estimates are available for: {', '.join(YIELD_CROPS)}."}
    if state not in YIELD_STATES:
        return {"error": f"Unknown state '{state}'."}
    if not area or area <= 0:
        return {"error": "Ask the user how much land (acres or hectares) they're planting."}

    typical = typical_inputs(crop)
    yield_input = YieldInput(
        crop=crop, area=area, area_unit=area_unit, state=state, district=district,
        season=season or _current_season(), annual_rainfall=0, latitude=latitude, longitude=longitude,
        **typical,
    )
    try:
        result, price = await asyncio.gather(
            asyncio.to_thread(predict_yield_detailed, yield_input),
            get_crop_price(crop),
        )
    except Exception as e:
        logger.exception("Yield tool failed")
        return {"error": f"The yield estimate couldn't be calculated right now ({type(e).__name__})."}

    out: Dict[str, Any] = {
        "crop": result["resolved_crop"],
        "season": result["resolved_season"],
        "area_hectares": round(result["area_hectares"], 2),
        "yield_t_per_ha": round(result["yield"], 2),
        "total_production_tonnes": round(result["estimated_production"], 2),
        "model": "trained on government crop records" if result["model_source"] == "ml"
                 else "simplified estimate (no historical data for this crop/state)",
        "assumptions": "Typical soil and input levels for the area. For an estimate using the farmer's own "
                       "soil test and fertilizer numbers, suggest the Yield Predictor page in CropIQ.",
    }
    if result.get("yield_low") is not None:
        out["likely_range_t_per_ha"] = f"{result['yield_low']:.1f}–{result['yield_high']:.1f}"
    if result.get("model_median_error_pct"):
        out["typical_error"] = f"within about {result['model_median_error_pct']:.0f}% of actual yields"
    if result.get("resolved_district"):
        out["district_used"] = result["resolved_district"]
        if result.get("district_median_yield"):
            out["district_typical_yield_t_per_ha"] = round(result["district_median_yield"], 2)
    if result.get("state_median_yield"):
        out["state_typical_yield_t_per_ha"] = round(result["state_median_yield"], 2)
    notes = [r for r in result["recommendations"] if r.startswith("Note:")]
    if notes:
        out["notes"] = notes

    if price:
        econ = compute_economics(
            crop=crop, production_t=result["estimated_production"], area_ha=result["area_hectares"],
            price_per_quintal=price["price_per_quintal"], conversion=price["conversion"], cost_per_ha=None,
            fertilizer=typical["fertilizer"], pesticide=typical["pesticide"],
        )
        out["income"] = {
            "price_used": f"₹{price['price_per_quintal']:,.0f}/quintal of {price['commodity']} ({price['source']})",
            "revenue": _inr(econ["revenue"]),
            "typical_cultivation_cost": _inr(econ["cost"]),
            "estimated_profit": _inr(econ["profit"]),
            "caveat": "Cost is a typical figure; actual profit depends on the farmer's own costs and selling price.",
        }
    return out


# --- Web search --------------------------------------------------------------

async def search_web(client, model_name: str, query: str) -> Dict[str, Any]:
    """Google-Search-grounded lookup in a separate model call (search grounding
    can't be combined with function declarations in one request)."""
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=f"Search the web and summarise the current facts for an Indian farmer: {query}",
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                               temperature=0.2),
        )
    except Exception as e:
        logger.warning(f"search_web tool failed: {e}")
        return {"error": "Web search is unavailable right now - answer from general knowledge and say so."}

    sources: List[Dict[str, str]] = []
    try:
        meta = response.candidates[0].grounding_metadata
        for chunk in (meta.grounding_chunks or []) if meta else []:
            if chunk.web and chunk.web.uri and all(s["url"] != chunk.web.uri for s in sources):
                sources.append({"title": chunk.web.title or chunk.web.uri, "url": chunk.web.uri})
    except Exception:
        pass
    return {"summary": response.text or "", "sources": sources[:5]}


# --- Declarations ------------------------------------------------------------

S = types.Schema
TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_market_prices",
        description="Today's mandi price (Rs per quintal, all-India average) and MSP for a crop. Use for any "
                    "question about crop prices, rates, bhav, or whether to sell.",
        parameters=S(type="OBJECT", properties={
            "commodity": S(type="STRING", description="Crop name in English, e.g. 'wheat', 'paddy', 'onion', 'chana'"),
        }, required=["commodity"]),
    ),
    types.FunctionDeclaration(
        name="get_weather_forecast",
        description="Current weather and a 7-day daily forecast (rain, temperature, wind). Use for weather "
                    "questions and timing decisions like spraying, irrigation, sowing or harvesting. Uses the "
                    "user's saved location unless they name another place.",
        parameters=S(type="OBJECT", properties={
            "place": S(type="STRING", description="Only if the user names a place, e.g. 'Nashik, Maharashtra'"),
        }),
    ),
    types.FunctionDeclaration(
        name="estimate_yield_and_income",
        description="Estimate yield, total production and expected income for the user's own field using "
                    "CropIQ's trained yield model and live prices. Needs crop, land area and state - ask the "
                    "user for any of these you don't know before calling.",
        parameters=S(type="OBJECT", properties={
            "crop": S(type="STRING", enum=YIELD_CROPS),
            "area": S(type="NUMBER", description="Land area"),
            "area_unit": S(type="STRING", enum=["acres", "hectares"]),
            "state": S(type="STRING", enum=YIELD_STATES),
            "district": S(type="STRING", description="District, if known"),
            "season": S(type="STRING", enum=["Kharif", "Rabi", "Summer", "Whole Year"],
                        description="Omit to use the current season"),
        }, required=["crop", "area", "state"]),
    ),
    types.FunctionDeclaration(
        name="search_web",
        description="Search the web for current information not covered by the other tools: government "
                    "schemes and subsidies, new regulations, recent pest outbreaks, agri news.",
        parameters=S(type="OBJECT", properties={
            "query": S(type="STRING", description="Search query in English"),
        }, required=["query"]),
    ),
])

# Which provider each tool's data comes from, for the "From ..." label in the UI
TOOL_PROVIDERS = {
    "get_market_prices": "Agmarknet",
    "get_weather_forecast": "Open-Meteo",
    "estimate_yield_and_income": "CropIQ yield model",
}
