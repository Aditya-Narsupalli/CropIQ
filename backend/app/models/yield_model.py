from pydantic import BaseModel, Field
from typing import Optional, List, Dict

class YieldInput(BaseModel):
    crop: str
    area: float
    season: str
    state: str
    annual_rainfall: float
    fertilizer: float
    pesticide: float
    ph: float
    n: float  # Nitrogen
    p: float  # Phosphorus
    k: float  # Potassium
    organic_carbon: float
    # Share of the field that is irrigated, 0-1 (None = not given)
    irrigation: Optional[float] = Field(None, ge=0, le=1)

    # "hectares" (default) or "acres"; area is converted to hectares
    area_unit: Optional[str] = "hectares"

    # Location data
    district: Optional[str] = None  # free text, matched to the training data's districts
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_name: Optional[str] = None
    
    # Legacy fields for backward compatibility
    crop_type: Optional[str] = None
    region: Optional[str] = None
    soil: Optional[str] = None
    weather: Optional[str] = None

class ScenarioContext(BaseModel):
    """Everything needed to recalculate a prediction for different soil and
    input values without repeating the weather lookup or the ML model call.
    Returned by /yield/predict and sent back to /yield/what-if."""
    crop: str
    state: Optional[str] = None
    area_ha: float
    base_yield: float
    model_source: str
    range_multipliers: Optional[List[float]] = None
    season_multiplier: float = 1.0
    state_multiplier: float = 1.0
    rainfall_mm: float
    weather_effect: float = 1.0
    # Market price (Rs/quintal of marketed produce) and conversion from
    # predicted yield to marketed produce (e.g. rice -> paddy); None if the
    # crop has no market price.
    price_per_quintal: Optional[float] = None
    price_conversion: float = 1.0

class BreakdownItem(BaseModel):
    factor: str
    label: str
    pct: float  # % change this factor made to the yield

class PriceInfo(BaseModel):
    price_per_quintal: float
    commodity: str
    source: str
    date: Optional[str] = None

class Economics(BaseModel):
    revenue: float
    revenue_low: Optional[float] = None
    revenue_high: Optional[float] = None
    marketed_production_t: float
    base_cost_per_ha: Optional[float] = None
    cost: Optional[float] = None
    profit: Optional[float] = None
    profit_per_ha: Optional[float] = None

class WhatIfInput(BaseModel):
    context: ScenarioContext
    ph: float
    n: float
    p: float
    k: float
    organic_carbon: float
    fertilizer: float
    pesticide: float
    irrigation: Optional[float] = Field(None, ge=0, le=1)
    # Farmer's own overrides; defaults come from the context / typical costs
    price_per_quintal: Optional[float] = None
    cost_per_ha: Optional[float] = None

class WhatIfResponse(BaseModel):
    yield_: float = Field(alias="yield")
    estimated_production: float
    yield_low: Optional[float] = None
    yield_high: Optional[float] = None
    base_yield: float
    breakdown: List[BreakdownItem]
    agronomy_basis: Optional[str] = None
    economics: Optional[Economics] = None

    class Config:
        populate_by_name = True

class WeatherData(BaseModel):
    current_temp: float
    current_humidity: float
    current_conditions: str
    monthly_rainfall_estimate: float

class YieldPredictionResponse(BaseModel):
    success: bool = True
    yield_: float = Field(alias="yield")  # Using alias because 'yield' is a Python keyword
    estimated_production: float
    recommendations: List[str]
    weather_data: Optional[Dict] = None

    # Transparency fields: which prediction path produced this number.
    # "ml" = trained XGBoost model (see app/models/train_yield_model.py);
    # "heuristic" = rule-based fallback, used when the crop/state isn't in
    # the training data's vocabulary.
    model_source: Optional[str] = None
    model_r2: Optional[float] = None
    model_median_error_pct: Optional[float] = None

    # Likely range (roughly 80% of outcomes), tonnes/hectare. ML path only.
    yield_low: Optional[float] = None
    yield_high: Optional[float] = None
    area_hectares: Optional[float] = None

    # How the inputs were interpreted by the model
    resolved_crop: Optional[str] = None
    resolved_season: Optional[str] = None
    resolved_district: Optional[str] = None

    # Historical context from the training data (tonnes/hectare)
    district_median_yield: Optional[float] = None
    state_median_yield: Optional[float] = None

    # "Why this number": base yield and the % effect of each factor on it
    base_yield: Optional[float] = None
    breakdown: List[BreakdownItem] = []
    # How the soil/input factors are derived (rule-based, with sources)
    agronomy_basis: Optional[str] = None
    irrigation_baseline: Optional[float] = None

    # Expected income (None when the crop has no market price)
    price: Optional[PriceInfo] = None
    economics: Optional[Economics] = None

    # Sent back to /yield/what-if for instant recalculation
    scenario_context: Optional[ScenarioContext] = None

    class Config:
        populate_by_name = True  # Allow populating model using both alias and field name