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
    # Add other settings if needed
    PROJECT_NAME: str = "FarmGenius Backend"
    MAX_FILE_SIZE_MB: int = 5 # Max file size in Megabytes for uploads

    # --- PostgreSQL (market price history) ---
    # Async SQLAlchemy connection string, e.g.
    # postgresql+asyncpg://user:password@localhost:5432/cropiq
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/cropiq",
    )
    # How many days of daily price rows to keep before they expire.
    PRICE_HISTORY_RETENTION_DAYS: int = int(os.getenv("PRICE_HISTORY_RETENTION_DAYS", "30"))
    # How often (seconds) the background job re-fetches live prices and
    # purges expired rows. Defaults to once every 24h.
    PRICE_COLLECTION_INTERVAL_SECONDS: int = int(os.getenv("PRICE_COLLECTION_INTERVAL_SECONDS", str(24 * 60 * 60)))


# Use lru_cache to load settings only once
@lru_cache
def get_settings() -> Settings:
    return Settings()

