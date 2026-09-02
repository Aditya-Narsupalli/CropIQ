from fastapi import APIRouter

# Ensure the imported module names match the filenames
from app.api.endpoints import disease, yield_endpoint, market, voice, chat, tts, microfarm_main

api_router = APIRouter()

# Include routers from endpoint modules with prefixes
api_router.include_router(disease.router, prefix="/disease", tags=["Disease Detection"])
api_router.include_router(yield_endpoint.router, prefix="/yield", tags=["Yield Prediction"])
api_router.include_router(market.router, prefix="/market", tags=["Market Access"])
api_router.include_router(voice.router, prefix="/voice", tags=["Voice Interaction"])
# The main chat assistant (chat.router) handles every language now - it used
# to be split from a separate multilingual_chat pipeline with its own model
# selection, its own memory store, and no live-data grounding or reliability
# safeguards. Consolidated into one implementation so every improvement
# (grounding, retries, anti-hallucination rules) applies regardless of language.
api_router.include_router(chat.router, prefix="/chat", tags=["AI Chat Assistant"])
api_router.include_router(tts.router, prefix="/tts", tags=["Text to Speech"])
api_router.include_router(microfarm_main.router, prefix="/microfarm", tags=["Microfarm"])
# Health check endpoint remains useful
@api_router.get("/health", tags=["Health Check"])
async def health_check():
    return {"status": "ok", "message": "CropIQ backend is running"}