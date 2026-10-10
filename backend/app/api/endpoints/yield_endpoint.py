import asyncio
import logging

from fastapi import APIRouter, HTTPException
from app.models.yield_model import YieldInput, YieldPredictionResponse, WhatIfInput, WhatIfResponse
from app.services.yield_prediction_service import predict_yield_detailed, apply_farm_inputs
from app.services.yield_economics import get_crop_price, compute_economics
from app.services.crop_comparison import compare_crops

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/predict", response_model=YieldPredictionResponse, status_code=200)
async def predict_farm_yield(
    yield_input: YieldInput
):
    """
    Receives farm details and returns a yield prediction with recommendations,
    a factor breakdown and expected income.
    """
    try:
        # Handle legacy field mapping if needed
        if yield_input.crop_type and not yield_input.crop:
            yield_input.crop = yield_input.crop_type

        # The prediction makes blocking HTTP calls (weather/geocoding), so it
        # runs in a worker thread; the market price lookup runs alongside it.
        result, price = await asyncio.gather(
            asyncio.to_thread(predict_yield_detailed, yield_input),
            get_crop_price(yield_input.crop),
        )

        context = result["scenario_context"]
        if price:
            context["price_per_quintal"] = price["price_per_quintal"]
            context["price_conversion"] = price["conversion"]
            result["price"] = price
            result["economics"] = _economics(context, result, yield_input.fertilizer, yield_input.pesticide)

        # Explicitly use the field name (yield_) instead of the alias (yield)
        result["yield_"] = result.pop("yield")
        if not result["weather_data"]:
            result.pop("weather_data")
        return YieldPredictionResponse(success=True, **result)
    except Exception:
        logger.exception("Unexpected error in /yield/predict")
        raise HTTPException(
            status_code=500,
            detail="An internal error occurred while generating the yield prediction. Please try again.",
        )


@router.post("/what-if", response_model=WhatIfResponse, status_code=200)
def what_if(body: WhatIfInput):
    """
    Recalculate a prediction for different soil/input values, reusing the
    scenario_context from /predict. Pure computation - no weather or model
    calls - so the UI can call it on every slider move.
    """
    context = body.context.model_dump()
    result = apply_farm_inputs(
        context, body.ph, body.n, body.p, body.k, body.organic_carbon, body.fertilizer, body.pesticide,
        irrigation=body.irrigation,
    )
    if body.price_per_quintal is not None:
        context["price_per_quintal"] = body.price_per_quintal
    if context.get("price_per_quintal"):
        result["economics"] = _economics(context, result, body.fertilizer, body.pesticide, body.cost_per_ha)

    result["yield_"] = result.pop("yield")
    return WhatIfResponse(**result)


@router.post("/compare-crops", status_code=200)
async def compare_crops_for_field(yield_input: YieldInput):
    """Rank the crops grown in this state and season by expected profit per
    hectare, using the farmer's own soil and input values (crop is ignored)."""
    try:
        return await compare_crops(yield_input)
    except Exception:
        logger.exception("Unexpected error in /yield/compare-crops")
        raise HTTPException(status_code=500, detail="Crop comparison is unavailable right now.")


def _economics(context, result, fertilizer, pesticide, cost_per_ha=None):
    area = context["area_ha"]
    return compute_economics(
        crop=context["crop"],
        production_t=result["estimated_production"],
        area_ha=area,
        price_per_quintal=context["price_per_quintal"],
        conversion=context.get("price_conversion", 1.0),
        cost_per_ha=cost_per_ha,
        fertilizer=fertilizer,
        pesticide=pesticide,
        production_low_t=result["yield_low"] * area if result["yield_low"] is not None else None,
        production_high_t=result["yield_high"] * area if result["yield_high"] is not None else None,
    )
