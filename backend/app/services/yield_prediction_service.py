import numpy as np
import pandas as pd
import joblib
import difflib
from typing import Dict, List, Tuple, Optional
import random
import requests
import os
from datetime import datetime, timedelta
from app.models.yield_model import YieldInput
from app.core.config import get_settings

# Load settings
settings = get_settings()

# --- Trained ML model (see app/models/train_yield_model.py) ---
# Predicts tonnes/hectare from State, District, Crop, Crop Type, Season,
# Area and Year, trained on real government crop-wise area/production/yield
# records. Falls back to the coefficient-based heuristic below for crops
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
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url)
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
        current_response = requests.get(current_url)
        current_data = current_response.json()
        
        # 5-day forecast
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&units=metric&appid={OPENWEATHER_API_KEY}"
        forecast_response = requests.get(forecast_url)
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

def get_soil_data(lat: float, lon: float) -> Dict:
    """
    Get soil data based on location
    Note: This is a placeholder. In a real implementation, this would connect to a soil database or API.
    """
    # For now, return default values with slight randomization to simulate real data
    return {
        'ph': round(random.uniform(6.0, 7.5), 1),
        'n': round(random.uniform(120, 160)),
        'p': round(random.uniform(40, 60)),
        'k': round(random.uniform(180, 220)),
        'organic_carbon': round(random.uniform(0.4, 0.8), 1)
    }

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


def _encode_or_unseen(encoder, value: str) -> int:
    """LabelEncoder.transform, but maps categories unseen during training to
    a fixed fallback class instead of raising."""
    if value in encoder.classes_:
        return int(encoder.transform([value])[0])
    return int(encoder.transform([encoder.classes_[0]])[0])


def get_ml_yield_estimate(crop: str, state: str, season: str, area: float) -> Optional[Tuple[float, str]]:
    """
    Predict tonnes/hectare using the trained XGBoost model
    (app/models/train_yield_model.py), if the model is loaded and the crop
    can be matched to the training data's vocabulary.
    Returns (yield_per_hectare, resolved_crop_name) or None to signal the
    caller should use the heuristic fallback instead.
    """
    if yield_model is None or yield_meta is None:
        return None

    resolved_crop = _resolve_category(crop, yield_meta["valid_crops"], CROP_NAME_TO_DATASET)
    if resolved_crop is None:
        return None  # crop isn't in the training vocabulary (e.g. aggregate categories, Coconut)

    resolved_state = _resolve_category(state, yield_meta["valid_states"]) or yield_meta["valid_states"][0]
    resolved_season = _resolve_category(season, yield_meta["valid_seasons"]) or "Kharif"
    crop_type = yield_meta["crop_to_type"].get(resolved_crop, "Cereals")

    encoders = yield_meta["encoders"]
    row = {
        "State Name": _encode_or_unseen(encoders["State Name"], resolved_state),
        "District Name": _encode_or_unseen(encoders["District Name"], "__unseen__"),
        "Crop Name": _encode_or_unseen(encoders["Crop Name"], resolved_crop),
        "Crop Type": _encode_or_unseen(encoders["Crop Type"], crop_type),
        "Season": _encode_or_unseen(encoders["Season"], resolved_season),
        "Area": float(area) if area else float(yield_meta["state_avg_area"].get(resolved_state, 10.0)),
        "YearStart": datetime.now().year,
    }
    X = pd.DataFrame([row])[yield_meta["features"]]
    log_pred = yield_model.predict(X)[0]
    yield_per_hectare = float(np.expm1(log_pred))
    return max(yield_per_hectare, 0.05), resolved_crop


def predict_yield(input_data: YieldInput) -> Tuple[float, float, List[str], str, Optional[float]]:
    """
    Predict crop yield based on input parameters.
    Returns: (yield_per_hectare, total_production, recommendations, model_source, model_r2)
    """
    # Get location data - try to get coordinates from state if not provided
    location_coords = STATE_COORDINATES.get(input_data.state, {"lat": 19.7515, "lon": 75.7139})  # Default to Maharashtra
    
    # Try to get more precise location if region is provided
    if hasattr(input_data, 'region') and input_data.region:
        location_string = f"{input_data.region}, {input_data.state}, India"
        geocode_data = get_geocode_data(location_string)
        if geocode_data:
            location_coords = geocode_data
    
    # Get weather data if possible
    weather_data = get_weather_data(location_coords['lat'], location_coords['lon'])
    
    # Get base yield for the crop - try the trained ML model first, and fall
    # back to the coefficient-based heuristic when the crop/state can't be
    # matched to the training data's vocabulary (see get_ml_yield_estimate).
    crop = input_data.crop
    if not crop and hasattr(input_data, 'crop_type') and input_data.crop_type:
        crop = input_data.crop_type

    ml_result = get_ml_yield_estimate(crop, input_data.state, input_data.season, input_data.area)
    if ml_result is not None:
        base_yield, resolved_crop_name = ml_result
        model_source = "ml"
        model_r2 = yield_meta["metrics"]["r2"]
    else:
        base_yield = CROP_COEFFICIENTS.get(crop, 3.0)  # Default to 3.0 if crop not found
        model_source = "heuristic"
        model_r2 = None
    
    # Apply season effect
    season_multiplier = SEASON_COEFFICIENTS.get(input_data.season, 1.0)
    
    # Apply state/region effect
    state_multiplier = STATE_COEFFICIENTS.get(input_data.state, 1.0)
    
    # Calculate soil health effect (pH, NPK, organic carbon)
    # Optimal pH is around 6.5-7.0 for most crops
    ph_effect = 1.0 - abs(input_data.ph - 6.7) * 0.1  # Penalize deviation from optimal pH
    ph_effect = max(0.7, min(1.1, ph_effect))  # Limit effect between 0.7 and 1.1
    
    # NPK effect - higher values generally better up to a point
    n_effect = min(1.2, input_data.n / 150)  # Normalize to 1.0 at 150 kg/ha
    p_effect = min(1.15, input_data.p / 60)  # Normalize to 1.0 at 60 kg/ha
    k_effect = min(1.15, input_data.k / 120)  # Normalize to 1.0 at 120 kg/ha
    
    # Organic carbon effect - higher is better up to about 1%
    oc_effect = min(1.2, input_data.organic_carbon / 0.8)
    
    # Rainfall effect - depends on crop but generally follows a bell curve
    rainfall = input_data.annual_rainfall
    
    # If we have weather data with rainfall estimate, use it to refine our prediction
    if weather_data and weather_data['monthly_rainfall_estimate'] > 0:
        # Adjust annual rainfall estimate based on current forecast
        current_month = datetime.now().month
        # Weight the real-time data more heavily during growing season
        if (input_data.season == "Kharif" and 6 <= current_month <= 10) or \
           (input_data.season == "Rabi" and (current_month >= 11 or current_month <= 3)) or \
           (input_data.season == "Summer" and 3 <= current_month <= 6):
            # During growing season, give more weight to current rainfall
            rainfall = (rainfall * 0.7) + (weather_data['monthly_rainfall_estimate'] * 30 * 0.3)
    
    # Calculate rainfall effect
    rainfall_effect = 1.0 - abs(rainfall - 900) / 1500
    rainfall_effect = max(0.7, min(1.2, rainfall_effect))
    
    # Fertilizer and pesticide effects - diminishing returns
    fertilizer_effect = min(1.25, 0.8 + input_data.fertilizer / 200)
    pesticide_effect = min(1.15, 0.9 + input_data.pesticide / 10)
    
    # Weather effect from real-time data
    weather_effect = 1.0
    if weather_data:
        # Temperature effect varies by crop
        temp = weather_data['current_temp']
        if crop in ["Rice", "Maize", "Cotton", "Sugarcane"]:
            # Warm-weather crops
            if temp < 15:
                weather_effect *= 0.8  # Too cold
            elif 25 <= temp <= 35:
                weather_effect *= 1.1  # Ideal
            elif temp > 40:
                weather_effect *= 0.9  # Too hot
        elif crop in ["Wheat", "Potato"]:
            # Cool-weather crops
            if temp < 5:
                weather_effect *= 0.85  # Too cold
            elif 15 <= temp <= 25:
                weather_effect *= 1.1  # Ideal
            elif temp > 30:
                weather_effect *= 0.8  # Too hot
    
    # Combine soil/nutrient/rainfall/weather effects into a single adjustment
    # multiplier on top of the base yield (state and season are already
    # baked into the ML prediction when model_source == "ml", so they're
    # excluded from the multiplier in that case to avoid double-counting).
    agronomic_effect = (
        ph_effect *
        ((n_effect + p_effect + k_effect) / 3) *
        oc_effect *
        rainfall_effect *
        fertilizer_effect *
        pesticide_effect *
        weather_effect
    )

    if model_source == "ml":
        # The ML model already encodes state/season/crop-driven yield
        # differences learned from real data. Let the farmer's specific soil
        # and input choices nudge that number, but keep the nudge bounded
        # (+/-20%) so a handful of self-reported fields can't swamp a
        # prediction backed by ~30k historical records.
        combined_effect = max(0.8, min(1.2, agronomic_effect))
    else:
        # Heuristic path (unchanged): state/season are not otherwise
        # accounted for, so fold them into the multiplier here.
        combined_effect = season_multiplier * state_multiplier * agronomic_effect

    # Add a small random variation (±5%)
    random_factor = 0.95 + random.random() * 0.1
    
    # Calculate final yield per hectare
    yield_per_hectare = base_yield * combined_effect * random_factor
    
    # Calculate total production based on area
    total_production = yield_per_hectare * input_data.area
    
    # Get recommendations for the crop
    recommendations = CROP_RECOMMENDATIONS.get(crop, DEFAULT_RECOMMENDATIONS).copy()

    # Add weather-based recommendations if available
    if weather_data:
        weather_recs = get_weather_based_recommendations(weather_data)
        if weather_recs:
            recommendations.extend(weather_recs)

    if model_source == "heuristic":
        recommendations.append(
            f"Note: '{crop}' isn't in our historical training data, so this estimate "
            "uses a simplified agronomic model rather than the trained yield model."
        )

    # Ensure we don't return more than 4 recommendations
    if len(recommendations) > 4:
        recommendations = recommendations[:4]

    return yield_per_hectare, total_production, recommendations, model_source, model_r2
