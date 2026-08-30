from fastapi import APIRouter, HTTPException, Depends, Query, Header
from app.core.ai_services import get_market_summary_ai
from app.services.market_scraper import get_all_prices, get_scraper, record_todays_snapshot_if_needed
from app.core.multi_agent import AgentType, Message, coordinator, context_protocol
from app.core.config import get_settings
import uuid
import logging
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic model for market listings
class MarketListing(BaseModel):
    crop: str
    quantity: str  # e.g., "10 quintals"
    price_expected: int
    contact: str
    location: Optional[str] = "Baramati"
    notes: Optional[str] = None

@router.get("/prices", status_code=200)
async def get_market_prices(crop: Optional[str] = None, location: Optional[str] = None):
    """Returns market prices from scraped sources for crops in specified locations."""
    try:
        # Create a session ID for context tracking
        session_id = str(uuid.uuid4())
        
        # Set up request context
        context_protocol.set_context(session_id, {
            "request_type": "market_prices",
            "crop": crop,
            "location": location or "Baramati"
        })
        
        # Send message to market agent
        message = await coordinator.route_message(
            Message(
                sender=AgentType.COORDINATOR,
                receiver=AgentType.MARKET_ANALYZER,
                content={
                    "crop": crop,
                    "location": location or "Baramati",
                    "force_refresh": True  # Always get fresh data for API calls
                },
                message_type="get_prices",
                context={"session_id": session_id}
            )
        )
        
        if not message or "error" in message.content:
            error = message.content.get("error", "Unknown error fetching prices") if message else "No response from market agent"
            raise HTTPException(status_code=500, detail=error)
            
        return {"market_data": message.content.get("prices", [])}
        
    except Exception as e:
        print(f"Error fetching market prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/summary", status_code=200)
async def get_market_summary():
    """Generates a brief AI summary of current market data using multi-agent system."""
    try:
        # Create a session ID for context tracking
        session_id = str(uuid.uuid4())
        context_protocol.set_context(session_id, {"request_type": "market_summary"})
        
        # Send message to market agent
        message = await coordinator.route_message(
            Message(
                sender=AgentType.COORDINATOR,
                receiver=AgentType.MARKET_ANALYZER,
                content={},
                message_type="get_summary",
                context={"session_id": session_id}
            )
        )
        
        if not message or "error" in message.content:
            error = message.content.get("error", "Unknown error generating summary") if message else "No response from market agent"
            raise HTTPException(status_code=500, detail=error)
            
        return {"summary": message.content.get("summary", "No market summary available")}
        
    except Exception as e:
        print(f"Error getting market summary: {e}")
        raise HTTPException(status_code=500, detail=f"Could not generate market summary: {str(e)}")

@router.post("/listings", status_code=201)
async def add_market_listing(listing: MarketListing):
    """Allows farmers to create market listings for their crops."""
    try:
        # Create a unique ID for the listing
        new_id = str(uuid.uuid4())[:8]  # Use first 8 chars of UUID for readability
        
        # Create a session ID for context tracking
        session_id = str(uuid.uuid4())
        
        # Store the listing in context for now (in production, this would go to a database)
        listing_dict = listing.dict()
        listing_dict["id"] = new_id
        listing_dict["type"] = "User Listing"  # Differentiate from mandi prices
        
        # Store in context (in memory)
        context_protocol.set_context(f"listing_{new_id}", listing_dict)
        
        # In production, we could analyze the listing using the market agent
        # For example, we could check if the price is reasonable compared to market rates
        
        print(f"Received listing: {listing_dict}")
        return {
            "message": "Listing created successfully",
            "listing_id": new_id,
            "details": listing_dict
        }
        
    except Exception as e:
        print(f"Error creating market listing: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trends/{crop}", status_code=200, deprecated=True)
async def get_market_trends_path_param(crop: str):
    """Deprecated: kept only for backward compatibility with any old
    bookmarked/cached links. Real Agmarknet commodity names can contain a
    literal '/' (e.g. "Bajra(Pearl Millet/Cumbu)") - even percent-encoded as
    %2F, ASGI servers commonly decode that back to a literal '/' before
    Starlette's router does path matching, so it gets split into extra path
    segments and 404s. A crop name as a path segment can never be fully
    safe for this reason; use GET /trends?crop=... instead (see below),
    which has no such ambiguity for any character."""
    return await get_market_trends(crop)


@router.get("/cron/refresh-snapshot", status_code=200)
async def refresh_snapshot(
    authorization: Optional[str] = Header(None),
    x_cron_secret: Optional[str] = Header(None, alias="X-Cron-Secret"),
):
    """Daily snapshot trigger, meant to be called by an external scheduler
    (GitHub Actions / Vercel Cron / cron-job.org), NOT by the frontend.

    This exists because record_todays_snapshot_if_needed() was previously
    only ever invoked as a side-effect of a real visitor opening the Market
    page and hitting /trends - so on any day nobody opened the app, that
    day's price never got written to Upstash and the "30-day" trend would
    have a gap. Calling this once a day, independent of traffic, closes
    that gap.

    Auth: accepts either
      - Authorization: Bearer <CRON_SECRET>   (this is the header Vercel
        Cron automatically attaches when a project env var named
        CRON_SECRET is set, so it works for free with no extra config if
        you trigger this via a Vercel Cron job hitting the rewritten
        /api/... path)
      - X-Cron-Secret: <CRON_SECRET>          (simplest option for GitHub
        Actions / curl / cron-job.org)

    If CRON_SECRET is not set in the environment, the endpoint is disabled
    (503) rather than silently running unauthenticated - the snapshot log
    is app data anyone could otherwise poke at without a secret configured.
    """
    settings = get_settings()
    if not settings.CRON_SECRET:
        raise HTTPException(
            status_code=503,
            detail="CRON_SECRET is not configured on the server - set it in your environment to enable this endpoint.",
        )

    bearer_token = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[7:]

    if settings.CRON_SECRET not in (bearer_token, x_cron_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")

    try:
        records = await get_all_prices()
        await record_todays_snapshot_if_needed()
        return {
            "status": "ok",
            "commodities_fetched": len(records),
        }
    except Exception as e:
        logger.error(f"Cron snapshot refresh failed: {e}")
        raise HTTPException(status_code=500, detail=f"Snapshot refresh failed: {str(e)}")


@router.get("/trends", status_code=200)
async def get_market_trends(crop: str = Query(..., description="Commodity name, e.g. 'Bajra(Pearl Millet/Cumbu)'")):
    """Analyze market trends for a specific crop."""
    try:
        # Create a session ID for context tracking
        session_id = str(uuid.uuid4())
        context_protocol.set_context(session_id, {"request_type": "market_trends", "crop": crop})
        
        # Send message to market agent
        message = await coordinator.route_message(
            Message(
                sender=AgentType.COORDINATOR,
                receiver=AgentType.MARKET_ANALYZER,
                content={"crop": crop},
                message_type="analyze_trends",
                context={"session_id": session_id}
            )
        )
        
        if not message or "error" in message.content:
            error = message.content.get("error", "Unknown error analyzing trends") if message else "No response from market agent"
            raise HTTPException(status_code=500, detail=error)
            
        # Return both the trend message and the historical data
        return {
            "message": message.content.get("message", "No trend data available"),
            "historical_data": message.content.get("historical_data", [])
        }
        
    except Exception as e:
        print(f"Error analyzing market trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))