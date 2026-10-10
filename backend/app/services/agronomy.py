"""
Soil and input adjustments for the yield estimate.

These are RULES, not learned from data: the yield training data
(yield_training_data.csv) has no soil-test or fertilizer columns, so the ML
model can only learn location/crop/season effects. The rules below are built
on published Indian agronomy norms instead of arbitrary curves:

- Soil nutrient ratings: ICAR soil-test fertility classes used on Soil Health
  Cards - available N (kg/ha) low <280, medium 280-560, high >560;
  available P (Olsen, kg/ha) low <10, medium 10-25, high >25;
  available K (kg/ha) low <110, medium 110-280, high >280;
  organic carbon (%) low <0.5, medium 0.5-0.75, high >0.75.
- Recommended fertilizer doses (N+P2O5+K2O, kg/ha): typical ICAR/state
  package-of-practice figures for irrigated/improved cultivation.
- Fertilizer response: Mitscherlich-type diminishing returns relative to that
  crop's recommended dose. Legumes respond less (they fix their own N).
- pH: no penalty inside the crop's preferred range, then a gradual decline.

Every factor is expressed relative to a typical farm (medium soil, ~80% of
the recommended dose), because the ML base yield already describes a typical
farm in that district.
"""
import json
import math
import os
from typing import Dict, Optional

# Effects measured from ICRISAT district data (app/models/train_agronomy_effects.py).
# Where present, they replace the rule-based fertilizer and rainfall effects
# and add an irrigation effect. Missing file -> rules only.
_EFFECTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "agronomy_effects.json")
try:
    with open(_EFFECTS_PATH, encoding="utf-8") as _f:
        LEARNED = json.load(_f)
except (OSError, ValueError):
    LEARNED = {"crops": {}}

# crop -> preferred pH range, recommended N+P2O5+K2O dose (kg/ha), legume?
CROP_PROFILES = {
    "Rice":      {"ph": (5.5, 7.0), "rdf": 220, "legume": False},
    "Wheat":     {"ph": (6.0, 7.5), "rdf": 220, "legume": False},
    "Maize":     {"ph": (5.5, 7.5), "rdf": 265, "legume": False},
    "Jowar":     {"ph": (6.0, 7.5), "rdf": 160, "legume": False},
    "Bajra":     {"ph": (6.0, 8.0), "rdf": 120, "legume": False},
    "Ragi":      {"ph": (5.0, 7.5), "rdf": 120, "legume": False},
    "Gram":      {"ph": (6.0, 8.0), "rdf": 80,  "legume": True},
    "Tur":       {"ph": (6.0, 7.5), "rdf": 90,  "legume": True},
    "Groundnut": {"ph": (6.0, 7.5), "rdf": 120, "legume": True},
    "Soyabean":  {"ph": (6.0, 7.5), "rdf": 130, "legume": True},
    "Sunflower": {"ph": (6.0, 7.5), "rdf": 210, "legume": False},
    "Safflower": {"ph": (6.0, 8.0), "rdf": 80,  "legume": False},
    "Nigerseed": {"ph": (5.5, 7.5), "rdf": 80,  "legume": False},
    "Cotton":    {"ph": (6.0, 8.0), "rdf": 200, "legume": False},
    "Sugarcane": {"ph": (6.0, 7.5), "rdf": 480, "legume": False},
    "Potato":    {"ph": (5.0, 6.5), "rdf": 360, "legume": False},
    "Onion":     {"ph": (6.0, 7.5), "rdf": 200, "legume": False},
    "Tobacco":   {"ph": (5.5, 7.0), "rdf": 150, "legume": False},
}
DEFAULT_PROFILE = {"ph": (6.0, 7.5), "rdf": 150, "legume": False}

# ICAR rating thresholds: (low/medium boundary, medium/high boundary)
SOIL_RATINGS = {"n": (280, 560), "p": (10, 25), "k": (110, 280), "organic_carbon": (0.5, 0.75)}

# A typical Indian field: medium-rated soil (Soil Health Card surveys put
# most Indian soils in the low-medium N and medium K classes).
TYPICAL_SOIL = {"ph": 6.8, "n": 280, "p": 15, "k": 200, "organic_carbon": 0.5}
TYPICAL_DOSE_FRACTION = 0.8   # typical farmer applies ~80% of the recommended dose
TYPICAL_PESTICIDE = 3


def profile(crop: str) -> Dict:
    return CROP_PROFILES.get(crop, DEFAULT_PROFILE)


def typical_inputs(crop: str) -> Dict[str, float]:
    """Inputs of a typical farm growing this crop - the baseline the ML
    estimate is anchored to."""
    return {
        **TYPICAL_SOIL,
        "fertilizer": round(profile(crop)["rdf"] * TYPICAL_DOSE_FRACTION),
        "pesticide": TYPICAL_PESTICIDE,
    }


def _soil_score(value: float, nutrient: str) -> float:
    """0 at half the low/medium boundary, 0.5 at that boundary, 1 at the
    medium/high boundary; capped a little above 1 for very rich soil."""
    low, high = SOIL_RATINGS[nutrient]
    if value <= low:
        return max(0.0, (value - low / 2) / (low / 2)) * 0.5
    return min(1.2, 0.5 + 0.5 * (value - low) / (high - low))


def _soil_effect(value: float, nutrient: str, weight_span: float) -> float:
    """Multiplier from a soil-test value: 1 - span at very poor soil, 1 at a
    medium-high rating."""
    return 1 - weight_span * (1 - _soil_score(value, nutrient))


def _fertilizer_effect(fertilizer: float, crop: str) -> float:
    """Mitscherlich response to the dose as a fraction of the recommended dose.
    Yield fraction with no fertilizer: ~65% for most crops, ~80% for legumes.
    Beyond 1.5x the recommended dose: slight decline (lodging, salt injury)."""
    prof = profile(crop)
    ratio = max(fertilizer, 0) / prof["rdf"]
    floor = 0.80 if prof["legume"] else 0.65
    effect = 1 - (1 - floor) * math.exp(-3 * ratio)
    if ratio > 1.5:
        effect -= 0.04 * min(ratio - 1.5, 1.5)
    return effect


def _ph_effect(ph: float, crop: str) -> float:
    low, high = profile(crop)["ph"]
    if ph <= 0:
        return 1.0  # unknown
    distance = max(low - ph, ph - high, 0)
    return max(0.7, 1 - 0.08 * distance)


def soil_and_input_components(crop: str, ph: float, n: float, p: float, k: float,
                              organic_carbon: float, fertilizer: float, pesticide: float) -> Dict[str, float]:
    """Multipliers for each soil/input factor (not yet relative to typical)."""
    legume = profile(crop)["legume"]
    # Legumes fix their own nitrogen, so soil N matters less and P/K more.
    weights = {"n": 0.04, "p": 0.08, "k": 0.06} if legume else {"n": 0.10, "p": 0.06, "k": 0.05}
    nutrients = 1.0
    for nutrient, value in (("n", n), ("p", p), ("k", k)):
        nutrients *= _soil_effect(value, nutrient, weights[nutrient])
    return {
        "ph": _ph_effect(ph, crop),
        "nutrients": nutrients,
        "organic_carbon": _soil_effect(organic_carbon, "organic_carbon", 0.06),
        "fertilizer": _fertilizer_effect(fertilizer, crop),
        # Crop protection: losses to pests/disease are commonly 10-20% without
        # any protection; units are self-reported, so the curve is kept mild.
        "pesticide": 1 - 0.08 * math.exp(-max(pesticide, 0) / 1.5),
    }


def learned(crop: str) -> Optional[Dict]:
    return LEARNED.get("crops", {}).get(crop)


def uses_measured(crop: str, factor: str) -> bool:
    """Whether this factor's measured effect passed the quality check in
    training (clear and plausible); otherwise the rule applies."""
    e = learned(crop)
    return bool(e and e.get("use", {}).get(factor, False))


def state_normal_rainfall(state: Optional[str]) -> float:
    return LEARNED.get("state_normal_rainfall_mm", {}).get(state or "", LEARNED.get("national_normal_rainfall_mm", 1000))


def state_irrigated_share(state: Optional[str]) -> float:
    return LEARNED.get("state_irrigated_share", {}).get(state or "", LEARNED.get("national_irrigated_share", 0.46))


def learned_components(crop: str, state: Optional[str], fertilizer: float, rainfall_mm: float,
                       irrigation: Optional[float]) -> Dict[str, float]:
    """Fertilizer, rainfall and irrigation multipliers measured from ICRISAT
    district data, for the crops it covers. Empty dict for other crops.

    - fertilizer: (dose + 10) ** elasticity (relative values are what matter)
    - rainfall: this year's rainfall vs the state's normal, on the fitted
      curve, with both clamped to the range actually observed for the crop
    - irrigation: farmer's irrigated share vs the state's typical share
    Unknown rainfall (0) or irrigation (None) -> no effect (1.0).
    """
    e = learned(crop)
    if not e:
        return {}
    out: Dict[str, float] = {}

    def rain_curve(mm: float) -> float:
        lo, hi = e["rain_range_mm"]
        r = min(max(mm, lo), hi) / 1000
        return e["rain_linear"] * r + e["rain_quadratic"] * r * r

    # Only factors that passed the training quality check; the caller keeps
    # the rule-based value for the others.
    if uses_measured(crop, "fertilizer"):
        out["fertilizer"] = math.exp(e["fertilizer_elasticity"] * math.log(max(fertilizer, 0) + 10))
    if uses_measured(crop, "rainfall"):
        out["rainfall"] = 1.0
        if rainfall_mm and rainfall_mm > 0:
            out["rainfall"] = math.exp(rain_curve(rainfall_mm) - rain_curve(state_normal_rainfall(state)))
    if uses_measured(crop, "irrigation"):
        out["irrigation"] = 1.0
        if irrigation is not None:
            share = min(max(irrigation, 0.0), 1.0)
            out["irrigation"] = math.exp(e["irrigation_coef"] * (share - state_irrigated_share(state)))
    return out


def basis_note(crop: str) -> str:
    prof = profile(crop)
    e = learned(crop)
    measured = [f for f in ("fertilizer", "rainfall", "irrigation") if uses_measured(crop, f)]
    if e and measured:
        named = ", ".join(measured[:-1]) + (" and " if len(measured) > 1 else "") + measured[-1]
        return (f"The {named} effect{'s' if len(measured) > 1 else ''} for {crop} "
                f"{'are' if len(measured) > 1 else 'is'} measured from ICRISAT district data "
                f"({e['n_districts']} districts, {e['years'][0]}–{e['years'][1]}), comparing each district "
                f"with itself across years. Other soil and input effects follow ICAR soil-test ratings and "
                f"recommended doses.")
    return (f"Soil and input effects follow ICAR soil-test ratings, a pH range of "
            f"{prof['ph'][0]}–{prof['ph'][1]} and a recommended dose of about {prof['rdf']} kg/ha "
            f"(N+P+K) for {crop} - rule-based, as no measured data covers this crop yet.")
