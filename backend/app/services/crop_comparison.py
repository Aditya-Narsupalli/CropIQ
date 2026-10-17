"""
"Best crops for my field": run the yield model and income estimate for every
crop that is actually grown in the farmer's state and season, with their own
soil and input values, and rank them by expected profit per hectare.

Only crops with historical records for that state + season are compared - the
model has nothing real to say about, say, sugarcane in a state where the data
has none - so the list reflects what's genuinely grown there.
"""
import asyncio
from typing import Any, Dict, List

from app.models.yield_model import YieldInput
from app.services import yield_prediction_service as yps
from app.services.yield_economics import CROP_MARKET, get_crop_price, compute_economics


def _season_names(season: str, crop: str) -> set:
    """Season labels in the data that mean the farmer's season for this crop.
    Eastern states use local names: "Autumn" is early kharif (aus); "Winter"
    is the main kharif rice crop (aman) for rice, but the rabi season for
    other crops such as potato."""
    if season == "Kharif":
        return {"Kharif", "Autumn"} | ({"Winter"} if crop == "Rice" else set())
    if season == "Rabi":
        return {"Rabi"} | (set() if crop == "Rice" else {"Winter"})
    return {season}


def _candidate_crops(state: str, season: str) -> List[Dict[str, Any]]:
    """Crops (by app label) recorded in this state for this season, or year-round."""
    meta = yps.yield_meta
    if meta is None:
        return []
    out = []
    for label in CROP_MARKET:
        dataset_crop = yps._resolve_category(label, meta["valid_crops"], yps.CROP_NAME_TO_DATASET)
        seasons = meta["crop_state_seasons"].get((dataset_crop, state), []) if dataset_crop else []
        if _season_names(season, label) & set(seasons):
            out.append({"crop": label, "year_round": False})
        elif "Whole Year" in seasons:
            out.append({"crop": label, "year_round": True})
    return out


async def compare_crops(base: YieldInput, limit: int = 8) -> Dict[str, Any]:
    state = yps._resolve_category(base.state, yps.yield_meta["valid_states"]) if yps.yield_meta else None
    if not state:
        return {"crops": [], "message": "Crop comparison isn't available for this state."}
    candidates = _candidate_crops(state, base.season)
    if not candidates:
        return {"crops": [], "message": f"No crop records for {base.season} in {state}."}

    # One weather lookup for the whole comparison, not one per crop
    probe = yps.build_prediction_context(base.model_copy(update={"crop": candidates[0]["crop"]}))
    weather = probe["weather_data"]

    def predict(crop: str) -> Dict[str, Any]:
        ctx = yps.build_prediction_context(base.model_copy(update={"crop": crop}), weather_data=weather)
        result = yps.apply_farm_inputs(ctx, base.ph, base.n, base.p, base.k, base.organic_carbon,
                                       base.fertilizer, base.pesticide, irrigation=base.irrigation)
        return {"ctx": ctx, "result": result}

    predictions = await asyncio.gather(*(asyncio.to_thread(predict, c["crop"]) for c in candidates))
    prices = await asyncio.gather(*(get_crop_price(c["crop"]) for c in candidates))

    rows = []
    for cand, pred, price in zip(candidates, predictions, prices):
        ctx, result = pred["ctx"], pred["result"]
        if ctx["model_source"] != "ml" or not price:
            continue
        econ = compute_economics(
            crop=cand["crop"], production_t=result["yield"], area_ha=1.0,  # per hectare
            price_per_quintal=price["price_per_quintal"], conversion=price["conversion"], cost_per_ha=None,
            fertilizer=base.fertilizer, pesticide=base.pesticide,
        )
        ml = ctx["ml"] or {}
        rows.append({
            "crop": cand["crop"],
            "year_round": cand["year_round"],
            "yield_t_per_ha": result["yield"],
            "district_median_yield": ml.get("district_median"),
            "price_per_quintal": price["price_per_quintal"],
            "price_source": price["source"],
            "revenue_per_ha": econ["revenue"],
            "cost_per_ha": econ["cost"],
            "profit_per_ha": econ["profit"],
        })

    rows.sort(key=lambda r: r["profit_per_ha"] if r["profit_per_ha"] is not None else float("-inf"), reverse=True)
    return {
        "state": state,
        "season": base.season,
        "district_used": (probe["ml"] or {}).get("district"),
        "crops": rows[:limit],
        "compared": len(rows),
        "note": "Profit uses typical cultivation costs and today's all-India average prices. Rotation, water "
                "availability, market access and your own experience matter as much as these numbers.",
    }
