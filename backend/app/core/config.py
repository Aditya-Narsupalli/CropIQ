import os
from dotenv import load_dotenv
from functools import lru_cache

# Load environment variables from .env file
load_dotenv()

class Settings:
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_NOT_SET")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "YOUR_GROQ_API_KEY_NOT_SET")
    OPENWEATHER_API_KEY: str = os.getenv("OPENWEATHER_API_KEY", "")
    # NOTE: Live market prices (market_scraper.py) call agmarknet.gov.in's
    # public dashboard-data API directly - no API key is required.

    # Upstash Redis (free tier) - used to persist the daily price snapshot
    # log across deploys/restarts. Render's filesystem is ephemeral (a
    # redeploy, or a free-tier service waking from sleep, wipes local disk
    # changes), so a local JSON file alone can't survive there. If these are
    # unset, market_scraper.py falls back to a local file - fine for local
    # dev, NOT fine for production on Render without them set.
    UPSTASH_REDIS_REST_URL: str = os.getenv("UPSTASH_REDIS_REST_URL", "")
    UPSTASH_REDIS_REST_TOKEN: str = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    # Add other settings if needed
    PROJECT_NAME: str = "FarmGenius Backend"
    MAX_FILE_SIZE_MB: int = 5 # Max file size in Megabytes for uploads


# Use lru_cache to load settings only once
@lru_cache
def get_settings() -> Settings:
    return Settings()

