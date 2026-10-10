import numpy as np
import pandas as pd
import joblib
import difflib
from typing import Dict, List, Tuple, Optional
import re
import requests
import os
from datetime import datetime, timedelta
from app.models.yield_model import YieldInput
from app.core.config import get_settings
from app.services import agronomy

# Load settings
settings = get_settings()

# --- Trained ML model (see app/models/train_yield_model.py) ---
# Predicts tonnes/hectare from State, District, Crop and Season, trained on
# real government crop-wise area/production/yield records. Falls back to the coefficient-based heuristic below for crops
# that aren't in the training data's vocabulary (e.g. aggregate categories
# like "Other Vegetables"/"Total Foodgrains", or units the source data
# reports inconsistently - see the Coconut note in the training script).
_models_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
_YIELD_MODEL_PATH = os.path.join(_models_dir, "yield_xgb_model.json")
_YIELD_META_PATH = os.path.join(_models_dir, "yield_model_meta.pkl")

yield_model = None
yield_meta = None
try:
    from xgboost import XGBRegressor
    yield_model = XGBRegressor()
    yield_model.load_model(_YIELD_MODEL_PATH)  # native format: robust across machines/xgboost versions
    yield_meta = joblib.load(_YIELD_META_PATH)
    if yield_meta.get("version", 1) < 2:
        raise ValueError("model metadata is from an older training script - retrain the yield model")
    print(f"Loaded ML yield model (R2={yield_meta['metrics']['r2']:.3f}, "
          f"trained on {yield_meta['metrics']['n_train']} rows)")
except FileNotFoundError:
    yield_model = None
    yield_meta = None
    print("ML yield model not found - run `python -m app.models.train_yield_model` "
          "from backend/. Falling back to heuristic-only predictions.")
except Exception as e:
    # Covers a corrupted/partially-downloaded model file (e.g. XGBoostError:
    # input stream corrupted) - degrade to the heuristic instead of crashing
    # the whole app on import. Must explicitly reset to None: on failure,
    # `yield_model` may still be bound to an *unfitted* XGBRegressor from the
    # line above, which would silently pass the `is None` check elsewhere
    # and blow up later at predict() time instead of failing cleanly here.
    yield_model = None
    yield_meta = None
    print(f"Failed to load ML yield model ({type(e).__name__}: {e}). "
          "The model file may be corrupted/incomplete - try re-downloading it "
          "or re-running `python -m app.models.train_yield_model`. "
          "Falling back to heuristic-only predictions.")

# Frontend crop labels -> dataset crop labels, where they don't already match
# exactly. Crops not listed here either match directly (e.g. "Rice",
# "Wheat") or have no clean single-crop equivalent in the training data.
CROP_NAME_TO_DATASET = {
    "Tur": "Arhar/Tur",
    "Nigerseed": "Niger Seed",
    "Cotton": "Cotton(Lint)",
}

# Aggregate/ambiguous categories that must NOT be resolved via fuzzy string
# matching - e.g. "Other Vegetables" is textually close to "Other Cereals"
# but agronomically unrelated, and would silently produce a wrong-crop
# prediction. These always use the heuristic fallback instead.
CROP_HEURISTIC_ONLY = {"Other Pulses", "Other Vegetables", "Fruits", "Total Foodgrains"}

# API Keys
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', settings.GOOGLE_MAPS_API_KEY if hasattr(settings, 'GOOGLE_MAPS_API_KEY') else None)
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY', settings.OPENWEATHER_API_KEY if hasattr(settings, 'OPENWEATHER_API_KEY') else None)

# Outbound API calls must not hang a prediction request indefinitely.
HTTP_TIMEOUT_S = 8

ACRES_TO_HECTARES = 0.404686

# Crop coefficients for yield calculation (simplified model)
# These values represent the base yield potential for each crop in tons/hectare
CROP_COEFFICIENTS = {
    "Rice": 4.5,
    "Jowar": 2.8,
    "Bajra": 2.5,
    "Maize": 5.2,
    "Ragi": 2.1,
    "Wheat": 4.0,
    "Gram": 1.8,
    "Tur": 1.5,
    "Other Pulses": 1.6,
    "Groundnut": 2.0,
    "Sunflower": 1.8,
    "Soyabean": 2.2,
    "Safflower": 1.2,
    "Nigerseed": 0.8,
    "Other Oilseeds": 1.5,
    "Cotton": 2.5,
    "Sugarcane": 75.0,
    "Tobacco": 2.0,
    "Potato": 22.0,
    "Onion": 25.0,
    "Other Vegetables": 20.0,
    "Fruits": 18.0,
    "Total Foodgrains": 3.5,
}

# Annual rainfall range (mm) within which each crop does well without a
# rainfall penalty. Outside it the penalty grows gradually; it's kept mild
# because much of Indian wheat, sugarcane, potato etc. is irrigated, so low
# rainfall alone doesn't mean low yield.
CROP_RAINFALL_RANGE_MM = {
    "Rice": (1000, 2500),
    "Jowar": (400, 1000),
    "Bajra": (250, 800),
    "Maize": (500, 1200),
    "Ragi": (500, 1200),
    "Wheat": (350, 1100),
    "Gram": (350, 900),
    "Tur": (600, 1400),
    "Other Pulses": (400, 1000),
    "Groundnut": (500, 1250),
    "Sunflower": (400, 1000),
    "Soyabean": (600, 1200),
    "Safflower": (300, 800),
    "Nigerseed": (800, 1500),
    "Other Oilseeds": (400, 1000),
    "Cotton": (500, 1200),
    "Sugarcane": (1000, 2500),
    "Tobacco": (500, 1200),
    "Potato": (300, 1200),
    "Onion": (350, 1000),
}
DEFAULT_RAINFALL_RANGE_MM = (500, 1500)

# Season coefficients (multiplier effect)
SEASON_COEFFICIENTS = {
    "Kharif": 1.0,
    "Rabi": 1.1,
    "Summer": 0.9,
}

# State coefficients (representing regional productivity differences)
STATE_COEFFICIENTS = {
    "Maharashtra": 1.0,
    "Karnataka": 1.05,
    "Gujarat": 1.1,
    "Madhya Pradesh": 0.95,
    "Punjab": 1.3,
    "Haryana": 1.25,
    "Uttar Pradesh": 1.1,
    "Bihar": 0.9,
    "West Bengal": 1.15,
    "Tamil Nadu": 1.1,
    "Andhra Pradesh": 1.15,
    "Telangana": 1.05,
}

# State center coordinates (approximate) for weather data when specific coordinates aren't provided
STATE_COORDINATES = {
    "Maharashtra": {"lat": 19.7515, "lon": 75.7139},
    "Karnataka": {"lat": 15.3173, "lon": 75.7139},
    "Gujarat": {"lat": 22.2587, "lon": 71.1924},
    "Madhya Pradesh": {"lat": 23.4733, "lon": 77.9473},
    "Punjab": {"lat": 31.1471, "lon": 75.3412},
    "Haryana": {"lat": 29.0588, "lon": 76.0856},
    "Uttar Pradesh": {"lat": 26.8467, "lon": 80.9462},
    "Bihar": {"lat": 25.0961, "lon": 85.3131},
    "West Bengal": {"lat": 22.9868, "lon": 87.8550},
    "Tamil Nadu": {"lat": 11.1271, "lon": 78.6569},
    "Andhra Pradesh": {"lat": 15.9129, "lon": 79.7400},
    "Telangana": {"lat": 18.1124, "lon": 79.0193},
    "Assam": {"lat": 26.2006, "lon": 92.9376},
    "Chhattisgarh": {"lat": 21.2787, "lon": 81.8661},
    "Goa": {"lat": 15.2993, "lon": 74.1240},
    "Himachal Pradesh": {"lat": 31.1048, "lon": 77.1734},
    "Jammu And Kashmir": {"lat": 33.7782, "lon": 76.5762},
    "Jharkhand": {"lat": 23.6102, "lon": 85.2799},
    "Kerala": {"lat": 10.8505, "lon": 76.2711},
    "Manipur": {"lat": 24.6637, "lon": 93.9063},
    "Meghalaya": {"lat": 25.4670, "lon": 91.3662},
    "Mizoram": {"lat": 23.1645, "lon": 92.9376},
    "Nagaland": {"lat": 26.1584, "lon": 94.5624},
    "Odisha": {"lat": 20.9517, "lon": 85.0985},
    "Rajasthan": {"lat": 27.0238, "lon": 74.2179},
    "Sikkim": {"lat": 27.5330, "lon": 88.5122},
    "Tripura": {"lat": 23.9408, "lon": 91.9882},
    "Uttarakhand": {"lat": 30.0668, "lon": 79.0193},
}

# Crop-specific recommendations
CROP_RECOMMENDATIONS = {
    "Rice": [
        "Maintain proper water levels in the field",
        "Apply nitrogen fertilizer in split doses",
        "Monitor for pests like stem borers and leaf folders",
        "Ensure proper drainage during heavy rainfall periods",
    ],
    "Wheat": [
        "Ensure timely irrigation, especially at crown root initiation and flowering stages",
        "Apply balanced fertilizers with emphasis on nitrogen",
        "Watch for rust and powdery mildew diseases",
        "Maintain optimal plant spacing for better yields",
    ],
    "Maize": [
        "Ensure adequate soil moisture during tasseling and silking stages",
        "Apply nitrogen in split doses for better utilization",
        "Monitor for fall armyworm and stem borer",
        "Maintain proper plant population for optimal yields",
    ],
    "Cotton": [
        "Implement integrated pest management for bollworms",
        "Maintain optimal soil moisture during flowering and boll formation",
        "Consider foliar application of micronutrients",
        "Monitor for pink bollworm and whitefly",
    ],
    "Sugarcane": [
        "Ensure proper irrigation scheduling throughout the growth period",
        "Apply balanced fertilizers based on soil test results",
        "Monitor for early shoot borer and top borer",
        "Maintain proper row spacing and planting density",
    ],
    "Potato": [
        "Ensure adequate soil moisture during tuber formation",
        "Monitor for late blight disease, especially in humid conditions",
        "Apply potassium for better tuber development",
        "Practice proper hilling to prevent greening of tubers",
    ],
    "Onion": [
        "Maintain consistent soil moisture for bulb development",
        "Apply sulfur-containing fertilizers for better flavor and storage",
        "Monitor for thrips and purple blotch disease",
        "Ensure proper curing before storage",
    ],
}

# Default recommendations for crops not in the specific list
DEFAULT_RECOMMENDATIONS = [
    "Monitor soil moisture regularly",
    "Apply fertilizers based on soil test results",
    "Implement integrated pest management practices",
    "Consider weather forecasts for planning farm operations",
]

# Weather-based recommendations
WEATHER_RECOMMENDATIONS = {
    "heavy_rain": "Consider drainage measures to prevent waterlogging",
    "drought": "Implement water conservation techniques and mulching",
    "high_temp": "Increase irrigation frequency and consider shade for sensitive crops",
    "low_temp": "Protect crops from frost with covers or smoke",
    "high_humidity": "Monitor for fungal diseases and ensure proper spacing",
    "low_humidity": "Increase irrigation and consider mulching to retain moisture",
}

def get_geocode_data(address: str) -> Optional[Dict]:
    """
    Get latitude and longitude from an address using Google Maps Geocoding API
    """
    if not GOOGLE_MAPS_API_KEY:
        print("Google Maps API key not configured. Skipping geocoding.")
        return None
        
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "key": GOOGLE_MAPS_API_KEY},
            timeout=HTTP_TIMEOUT_S,
        )
        data = response.json()
        
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            return {
                'lat': location['lat'],
                'lon': location['lng']
            }
        else:
            print(f"Geocoding error: {data['status']}")
            return None
    except Exception as e:
        print(f"Error in geocoding: {e}")
        return None

def get_weather_data(lat: float, lon: float) -> Optional[Dict]:
    """
    Get weather data from OpenWeather API
    """
    if not OPENWEATHER_API_KEY:
        print("OpenWeather API key not configured. Skipping weather data.")
        return None
        
    try:
        # Current weather
        current_url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
        current_response = requests.get(current_url, timeout=HTTP_TIMEOUT_S)
        current_data = current_response.json()

        # 5-day forecast
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
        forecast_response = requests.get(forecast_url, timeout=HTTP_TIMEOUT_S)
        forecast_data = forecast_response.json()
        
        # Process and return relevant weather data
        if current_response.status_code == 200 and forecast_response.status_code == 200:
            # Calculate average rainfall from forecast (convert from mm to cm)
            total_rain = 0
            rain_days = 0
            
            for item in forecast_data['list']:
                if 'rain' in item and '3h' in item['rain']:
                    total_rain += item['rain']['3h']
                    rain_days += 1
            
            # Convert 5-day rainfall to estimated monthly rainfall (cm)
            monthly_rainfall_estimate = (total_rain / 5) * 30 / 10 if rain_days > 0 else 0
            
            # Current conditions
            current_temp = current_data['main']['temp']
            current_humidity = current_data['main']['humidity']
            current_conditions = current_data['weather'][0]['main']
            
            return {
                'current_temp': current_temp,
                'current_humidity': current_humidity,
                'current_conditions': current_conditions,
                'monthly_rainfall_estimate': monthly_rainfall_estimate
            }
        else:
            print(f"Weather API error: {current_response.status_code}, {forecast_response.status_code}")
            return None
    except Exception as e:
        print(f"Error in weather data: {e}")
        return None

def get_weather_based_recommendations(weather_data: Dict) -> List[str]:
    """
    Generate weather-specific recommendations based on current conditions
    """
    recommendations = []
    
    if not weather_data:
        return recommendations
        
    # Temperature-based recommendations
    if weather_data['current_temp'] > 35:
        recommendations.append(WEATHER_RECOMMENDATIONS['high_temp'])
    elif weather_data['current_temp'] < 10:
        recommendations.append(WEATHER_RECOMMENDATIONS['low_temp'])
        
    # Humidity-based recommendations
    if weather_data['current_humidity'] > 80:
        recommendations.append(WEATHER_RECOMMENDATIONS['high_humidity'])
    elif weather_data['current_humidity'] < 30:
        recommendations.append(WEATHER_RECOMMENDATIONS['low_humidity'])
        
    # Rainfall-based recommendations
    if weather_data['monthly_rainfall_estimate'] > 25:
        recommendations.append(WEATHER_RECOMMENDATIONS['heavy_rain'])
    elif weather_data['monthly_rainfall_estimate'] < 5:
        recommendations.append(WEATHER_RECOMMENDATIONS['drought'])

    return recommendations


def _resolve_category(value: str, valid_values: List[str], name_map: Optional[Dict[str, str]] = None,
                       cutoff: float = 0.75) -> Optional[str]:
    """Resolve a user-supplied category (crop/state/season name) to the closest
    matching label the ML model was trained on. Tries: exact match -> known
    alias map -> fuzzy match -> gives up (None), in which case the caller
    should fall back to the heuristic."""
    if not value:
        return None
    if value in CROP_HEURISTIC_ONLY:
        return None
    if value in valid_values:
        return value
    if name_map and value in name_map and name_map[value] in valid_values:
        return name_map[value]
    # Fuzzy matching is a last resort for genuine spelling/formatting
    # variants (e.g. "Cotton" -> "Cotton(Lint)"). It's deliberately blocked
    # for generic "Other ..."/"Total ..." labels, which read as textually
    # similar to unrelated dataset categories (see CROP_HEURISTIC_ONLY) -
    # a high string-similarity score there doesn't mean the crops match.
    if value.lower().startswith(("other ", "total ")):
        return None
    close = difflib.get_close_matches(value, valid_values, n=1, cutoff=cutoff)
    return close[0] if close else None


def _normalize_place(name: str) -> str:
    """'Ludhiana District' / 'ludhiana  dist.' -> 'ludhiana'."""
    name = re.sub(r"\b(district|dist\.?|zila|zilla)\b", " ", name.lower())
    return re.sub(r"[^a-z]+", " ", name).strip()


def _resolve_district(district: Optional[str], state: str) -> Optional[str]:
    """Match a free-text district (e.g. from OSM reverse geocoding) to a
    district the model was trained on, searching only within the given state.
    Returns None when there's no confident match - the model then gives a
    state-level estimate rather than borrowing some other district's pattern."""
    if not district:
        return None
    candidates = yield_meta["state_districts"].get(state, [])
    by_norm = {_normalize_place(d): d for d in candidates}
    target = _normalize_place(district)
    if target in by_norm:
        return by_norm[target]
    close = difflib.get_close_matches(target, list(by_norm), n=1, cutoff=0.8)
    return by_norm[close[0]] if close else None


def _resolve_season(crop: str, state: str, season: str) -> Tuple[str, Optional[str]]:
    """Pick the season label the data actually records this crop under.
    Some crops are only reported under seasons the form doesn't offer -
    sugarcane is almost always "Whole Year" - and predicting them under
    "Kharif" puts them in a corner of the data with few or no examples.
    Returns (season, note) where note explains any substitution."""
    resolved = _resolve_category(season, yield_meta["valid_seasons"])
    known = yield_meta["crop_state_seasons"].get((crop, state)) or yield_meta["crop_seasons"].get(crop, [])
    if resolved and (not known or resolved in known):
        return resolved, None
    if known:
        note = (f"{crop} is recorded under the '{known[0]}' season in this region's data, "
                f"so the estimate uses that instead of '{season}'.")
        return known[0], note
    return resolved or "Kharif", None


def get_ml_yield_estimate(crop: str, state: str, season: str, district: Optional[str] = None) -> Optional[Dict]:
    """
    Predict tonnes/hectare using the trained XGBoost model
    (app/models/train_yield_model.py), if the model is loaded and the crop
    and state can be matched to the training data's vocabulary.
    Returns a dict with the prediction and how inputs were resolved, or None
    to signal the caller should use the heuristic fallback instead.
    """
    if yield_model is None or yield_meta is None:
        return None

    resolved_crop = _resolve_category(crop, yield_meta["valid_crops"], CROP_NAME_TO_DATASET)
    if resolved_crop is None:
        return None  # crop isn't in the training vocabulary (e.g. aggregate categories, Coconut)
    resolved_state = _resolve_category(state, yield_meta["valid_states"])
    if resolved_state is None:
        return None  # don't guess some other state's yields

    resolved_season, season_note = _resolve_season(resolved_crop, resolved_state, season)
    resolved_district = _resolve_district(district, resolved_state)

    categories = yield_meta["categories"]
    row = {
        "State Name": resolved_state,
        "District Name": resolved_district,  # None -> model's learned "unknown district" branch
        "Crop Name": resolved_crop,
        "Season": resolved_season,
    }
    X = pd.DataFrame([row])
    for col in yield_meta["features"]:
        X[col] = pd.Categorical(X[col], categories=categories[col])
    yield_per_hectare = max(float(np.expm1(yield_model.predict(X[yield_meta["features"]])[0])), 0.05)

    range_key = "known_district" if resolved_district else "unknown_district"
    return {
        "yield": yield_per_hectare,
        "range_multipliers": yield_meta["range_multipliers"][range_key],
        "crop": resolved_crop,
        "state": resolved_state,
        "season": resolved_season,
        "district": resolved_district,
        "season_note": season_note,
        "district_median": yield_meta["district_median"].get(
            (resolved_crop, resolved_state, resolved_district, resolved_season)) if resolved_district else None,
        "state_median": yield_meta["state_median"].get((resolved_crop, resolved_state, resolved_season)),
    }


def _rainfall_effect(crop: str, rainfall_mm: float) -> float:
    """1.0 inside the crop's comfortable rainfall range, easing down to 0.8
    as rainfall moves well outside it."""
    low, high = CROP_RAINFALL_RANGE_MM.get(crop, DEFAULT_RAINFALL_RANGE_MM)
    if rainfall_mm <= 0:
        return 1.0  # unknown - don't penalise
    if rainfall_mm < low:
        shortfall = (low - rainfall_mm) / low          # 0..1
        return max(0.8, 1.0 - 0.4 * shortfall)
    if rainfall_mm > high:
        excess = (rainfall_mm - high) / high
        return max(0.8, 1.0 - 0.2 * excess)
    return 1.0


# Inputs of an ordinary Indian farm; the ML estimate is anchored to these.
# Crop-specific (fertilizer is ~80% of that crop's recommended dose) - use
# agronomy.typical_inputs(crop). This generic copy is kept for callers that
# have no crop.
TYPICAL_FARM_INPUTS = agronomy.typical_inputs("")

# Display labels for the "why this number" breakdown, in display order.
FACTOR_LABELS = {
    "season": "Season",
    "state": "State",
    "ph": "Soil pH",
    "nutrients": "Soil N-P-K",
    "organic_carbon": "Soil organic carbon",
    "fertilizer": "Fertilizer use",
    "pesticide": "Crop protection",
    "rainfall": "Rainfall vs normal",
    "irrigation": "Irrigation",
    "weather": "Current weather",
}


def _agronomic_components(crop: str, ph: float, n: float, p: float, k: float, organic_carbon: float,
                          fertilizer: float, pesticide: float, rainfall_mm: float,
                          state: Optional[str] = None, irrigation: Optional[float] = None) -> Dict[str, float]:
    """Individual multipliers from soil health, inputs, rainfall and irrigation.
    Soil/input rules are in agronomy.py (ICAR ratings, crop-specific doses);
    for crops covered by ICRISAT district data, fertilizer, rainfall and
    irrigation effects are the measured ones instead."""
    components = {
        **agronomy.soil_and_input_components(crop, ph, n, p, k, organic_carbon, fertilizer, pesticide),
        "rainfall": _rainfall_effect(crop, rainfall_mm),
    }
    components.update(agronomy.learned_components(crop, state, fertilizer, rainfall_mm, irrigation))
    return components


_FETCH_WEATHER = object()


def build_prediction_context(input_data: YieldInput, weather_data=_FETCH_WEATHER) -> Dict:
    """
    The slow part of a prediction: weather lookup and the ML model. Everything
    that depends only on location/crop/season, not on the farmer's soil and
    input numbers. The returned context (minus weather_data/ml) is all
    apply_farm_inputs needs, which is what lets the what-if sliders
    recalculate instantly without repeating these calls.

    Pass weather_data (possibly None) to reuse an existing lookup, e.g. when
    comparing many crops for the same field.
    """
    crop = input_data.crop
    if not crop and input_data.crop_type:
        crop = input_data.crop_type

    area_ha = input_data.area
    if (input_data.area_unit or "").lower().startswith("acre"):
        area_ha = input_data.area * ACRES_TO_HECTARES

    # Location for weather: the farmer's own coordinates if given, else a
    # geocoded region, else the state's centre.
    if input_data.latitude and input_data.longitude:
        location_coords = {"lat": input_data.latitude, "lon": input_data.longitude}
    else:
        location_coords = STATE_COORDINATES.get(input_data.state, {"lat": 19.7515, "lon": 75.7139})
        if input_data.region:
            geocode_data = get_geocode_data(f"{input_data.region}, {input_data.state}, India")
            if geocode_data:
                location_coords = geocode_data

    if weather_data is _FETCH_WEATHER:
        weather_data = get_weather_data(location_coords['lat'], location_coords['lon'])

    # Base yield: trained ML model first, coefficient heuristic as fallback
    # when the crop/state can't be matched to the training vocabulary.
    ml = get_ml_yield_estimate(crop, input_data.state, input_data.season, input_data.district)
    if ml is not None:
        base_yield = ml["yield"]
        model_source = "ml"
    else:
        base_yield = CROP_COEFFICIENTS.get(crop, 3.0)  # Default to 3.0 if crop not found
        model_source = "heuristic"

    # The farmer's annual rainfall (the form auto-fills the last 12 months
    # for their location) is judged against their state's normal - see
    # agronomy.learned_components. Short-range forecasts and today's
    # temperature are deliberately NOT turned into yield multipliers: a few
    # days of weather says little about a whole season's harvest, and those
    # rules were hand-made rather than measured. Live weather still drives
    # the weather-based recommendations.
    rainfall = input_data.annual_rainfall
    weather_effect = 1.0

    return {
        "crop": crop,
        "state": input_data.state,
        "area_ha": area_ha,
        "base_yield": base_yield,
        "model_source": model_source,
        "range_multipliers": ml["range_multipliers"] if ml else None,
        "season_multiplier": SEASON_COEFFICIENTS.get(input_data.season, 1.0),
        "state_multiplier": STATE_COEFFICIENTS.get(input_data.state, 1.0),
        "rainfall_mm": rainfall,
        "weather_effect": weather_effect,
        # Not needed by apply_farm_inputs; stripped before sending to the client
        "weather_data": weather_data,
        "ml": ml,
    }


def apply_farm_inputs(context: Dict, ph: float, n: float, p: float, k: float, organic_carbon: float,
                      fertilizer: float, pesticide: float, irrigation: Optional[float] = None) -> Dict:
    """
    The fast, pure part of a prediction: adjust the base yield for the
    farmer's soil and inputs. No network or model calls.
    Returns yield, production, likely range and a per-factor breakdown
    (percent change each factor contributed).
    """
    crop = context["crop"]
    state = context.get("state")
    components = _agronomic_components(crop, ph, n, p, k, organic_carbon, fertilizer, pesticide,
                                       context["rainfall_mm"], state=state, irrigation=irrigation)
    components["weather"] = context["weather_effect"]

    # Both base yields (ML model and crop coefficients) describe a typical
    # farm, so the farmer's soil and inputs are compared against a typical
    # farm (not an ideal one): average inputs leave the estimate unchanged.
    typical = _agronomic_components(crop, rainfall_mm=0, state=state, **agronomy.typical_inputs(crop))
    typical["weather"] = 1.0
    ratios = {f: components[f] / typical[f] for f in components}

    # Bound the farm-input adjustment so a handful of self-reported fields
    # can't swamp the base estimate: -25%/+30% around the ML model's learned
    # number (wide enough for measured irrigation/drought effects), a little
    # wider around the much cruder heuristic.
    lo, hi = (0.75, 1.3) if context["model_source"] == "ml" else (0.65, 1.35)
    raw = float(np.prod(list(ratios.values())))
    adjusted = max(lo, min(hi, raw))
    # If the cap kicked in, shrink every factor proportionally (in log
    # space) so the breakdown still multiplies out to the real result.
    if raw != adjusted and raw > 0:
        scale = np.log(adjusted) / np.log(raw)
        ratios = {f: float(np.exp(np.log(r) * scale)) for f, r in ratios.items()}
    combined = adjusted

    if context["model_source"] != "ml":
        # Heuristic path: state/season are not otherwise accounted for.
        ratios = {"season": context["season_multiplier"], "state": context["state_multiplier"], **ratios}
        combined *= context["season_multiplier"] * context["state_multiplier"]

    yield_per_hectare = context["base_yield"] * combined
    total_production = yield_per_hectare * context["area_ha"]

    yield_low = yield_high = None
    if context.get("range_multipliers"):
        lo_mult, hi_mult = context["range_multipliers"]
        yield_low, yield_high = yield_per_hectare * lo_mult, yield_per_hectare * hi_mult

    breakdown = [
        {"factor": f, "label": FACTOR_LABELS[f], "pct": (ratios[f] - 1.0) * 100}
        for f in FACTOR_LABELS if f in ratios
    ]

    return {
        "yield": yield_per_hectare,
        "estimated_production": total_production,
        "yield_low": yield_low,
        "yield_high": yield_high,
        "area_hectares": context["area_ha"],
        "base_yield": context["base_yield"],
        "breakdown": breakdown,
        "agronomy_basis": agronomy.basis_note(crop),
    }


def predict_yield_detailed(input_data: YieldInput) -> Dict:
    """
    Predict crop yield based on input parameters.
    Returns a dict with yield, production, likely range, factor breakdown,
    recommendations, model provenance, historical context, the weather data
    used, and a scenario_context for fast what-if recalculation.
    """
    context = build_prediction_context(input_data)
    ml, weather_data, crop = context["ml"], context["weather_data"], context["crop"]

    result = apply_farm_inputs(
        context, input_data.ph, input_data.n, input_data.p, input_data.k,
        input_data.organic_carbon, input_data.fertilizer, input_data.pesticide,
        irrigation=input_data.irrigation,
    )

    # Recommendations: time-sensitive weather advice first, then crop advice.
    recommendations = get_weather_based_recommendations(weather_data) if weather_data else []
    recommendations += [r for r in CROP_RECOMMENDATIONS.get(crop, DEFAULT_RECOMMENDATIONS)
                        if r not in recommendations]
    recommendations = recommendations[:4]

    # Notes about how the estimate was produced are always kept.
    if ml is not None and ml["season_note"]:
        recommendations.append(f"Note: {ml['season_note']}")
    if ml is None:
        recommendations.append(
            f"Note: '{crop}' in {input_data.state} isn't in our historical training data, so this "
            "estimate uses a simplified agronomic model rather than the trained yield model."
        )

    scenario_context = {k: v for k, v in context.items() if k not in ("weather_data", "ml")}

    return {
        **result,
        "recommendations": recommendations,
        "model_source": context["model_source"],
        "model_r2": yield_meta["metrics"]["r2"] if ml else None,
        "model_median_error_pct": (yield_meta["metrics"]["next_year"]["median_ape"] * 100) if ml else None,
        "resolved_crop": ml["crop"] if ml else crop,
        "resolved_season": ml["season"] if ml else input_data.season,
        "resolved_district": ml["district"] if ml else None,
        "district_median_yield": ml["district_median"] if ml else None,
        "state_median_yield": ml["state_median"] if ml else None,
        "weather_data": weather_data,
        "scenario_context": scenario_context,
        # Typical irrigated share in this state, for crops with measured
        # irrigation effects (None otherwise) - the UI's starting point
        "irrigation_baseline": agronomy.state_irrigated_share(context["state"])
        if agronomy.uses_measured(crop, "irrigation") else None,
    }


def predict_yield(input_data: YieldInput) -> Tuple[float, float, List[str], str, Optional[float]]:
    """
    Backwards-compatible wrapper around predict_yield_detailed.
    Returns: (yield_per_hectare, total_production, recommendations, model_source, model_r2)
    """
    r = predict_yield_detailed(input_data)
    return r["yield"], r["estimated_production"], r["recommendations"], r["model_source"], r["model_r2"]
