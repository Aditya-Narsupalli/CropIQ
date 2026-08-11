from fastapi import FastAPI
from app.api.api import api_router
from app.core.config import get_settings
import asyncio

# Import multi-agent system
from app.core.multi_agent import coordinator, context_protocol
from app.core.agents import init_agents
from app.core.chat_agent import init_chat_agent
from app.core.db import init_db
from app.core.scheduler import start_price_collection_task

from fastapi.middleware.cors import CORSMiddleware

settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI Assistant for Sustainable Agriculture and Farm Management",
    version="0.1.0"
)

# -------------------- CORS --------------------
origins = [
    # Local Development
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://localhost:5182",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",

    # Production Frontend
    "https://crop-iq-azure.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ------------------------------------------------

# Include API routes
app.include_router(api_router, prefix="/api/v1")

# Root endpoint
@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Welcome to the CropIQ API!"}

# Health endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}

@app.on_event("startup")
async def startup_event():
    print("Starting up CropIQ API...")

    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_NOT_SET":
        print("STARTUP WARNING: Gemini API key is not configured!")

    # Remove this if you no longer use Groq
    if hasattr(settings, "GROQ_API_KEY"):
        if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "YOUR_GROQ_API_KEY_NOT_SET":
            print("STARTUP WARNING: Groq API key is not configured!")

    print(f"CORS allowed origins: {origins}")

    # Initialize the PostgreSQL market price history table.
    print("Initializing market price history database...")
    try:
        await init_db()
        # Kick off the background job that takes a daily snapshot of live
        # commodity prices (Agmarknet only exposes "today") and purges rows
        # older than the 30-day retention window.
        app.state.price_collection_task = start_price_collection_task()
        print("Market price history database ready; daily price collection scheduled.")
    except Exception as e:
        print(f"STARTUP WARNING: Could not initialize market price database: {e}")

    # Initialize multi-agent system
    print("Initializing multi-agent system...")
    coord = init_agents()
    await coord.start()

    # Initialize chat agent
    print("Initializing AI chat assistant...")
    init_chat_agent()
    print("AI chat assistant initialized")

    print("Multi-agent system initialized")

    context_protocol.set_context(
        "supported_languages",
        {
            "en": "English",
            "hi": "Hindi",
            "mr": "Marathi",
        },
    )

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down CropIQ API...")
    task = getattr(app.state, "price_collection_task", None)
    if task:
        task.cancel()
