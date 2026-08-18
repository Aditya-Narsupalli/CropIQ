from google import genai
from PIL import Image as PILImage
import io
from typing import TYPE_CHECKING

# Import settings using the function
from .config import get_settings

# Conditional import for type hinting to avoid circular dependency issues
if TYPE_CHECKING:
    from app.models.yield_model import YieldInput

# Load settings
settings = get_settings()

# --- Configure APIs ---
gemini_client = None
gemini_vision_model_name = 'models/gemini-flash-latest'  # alias - Google auto-repoints this on deprecations
gemini_text_model_name = 'models/gemini-flash-lite-latest'

def _configure_gemini_client() -> None:
    global gemini_client
    try:
        if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_NOT_SET":
            gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        else:
            print("AI_SERVICES: Gemini API key not configured. Gemini features will not work.")
    except Exception as e:
        print(f"AI_SERVICES: Error configuring Gemini: {e}")
        gemini_client = None

_configure_gemini_client()

async def generate_text(prompt: str) -> str:
    """Generate a text response from Gemini."""
    if not gemini_client:
        return "Error: Gemini text model is not configured."

    try:
        response = gemini_client.models.generate_content(
            model=gemini_text_model_name,
            contents=[prompt]
        )
        return getattr(response, "text", None) or (
            response.candidates[0].content if getattr(response, 'candidates', None) else str(response)
        )
    except Exception as e:
        print(f"Error in Gemini text generation: {e}")
        return f"Error generating text with Gemini: {str(e)}"


# --- Disease Prediction Function ---
async def get_disease_prediction(
    image_bytes: bytes,
    crop_type: str = "crop",
    location: str = ""
) -> str:
    """
    Analyzes an image using Gemini Vision model to detect crop diseases.
    Considers crop type and location for more accurate diagnosis.
    """
    if not gemini_client:
        return "Error: Gemini Vision model is not configured."

    try:
        # Open with PIL for validation AND pass the PIL image itself to generate_content.
        # NOTE: genai.types.Image (used previously) is NOT a valid content part for
        # generate_content()'s `contents` list in this SDK version - only str, PIL.Image,
        # types.Part, or types.File are accepted. Passing types.Image silently failed
        # on every single request, which is why disease detection was never working.
        pil_img = PILImage.open(io.BytesIO(image_bytes))
        location_context = location if location else "India"
        prompt = f"""You are an expert agricultural pathologist analyzing crop diseases in India.

Context: Crop: {crop_type}, Location: {location_context}

Analyze the attached plant image and provide:
1. DISEASE/PEST IDENTIFICATION (with confidence level)
2. VISIBLE SYMPTOMS (describe what you see)
3. LIKELY CAUSES (why this occurs in the given location)
4. TREATMENT RECOMMENDATIONS (organic preferred, then chemical alternatives)
5. PREVENTIVE MEASURES (for future protection)
6. RECOVERY TIMELINE (estimate for improvement)

Be practical for Indian farmers. Use bullet points. If image is unclear, state that.
        """

        response = gemini_client.models.generate_content(
            model=gemini_vision_model_name,
            contents=[prompt, pil_img]
        )
        return getattr(response, "text", None) or (
            response.candidates[0].content if getattr(response, 'candidates', None) else str(response)
        )

    except Exception as e:
        print(f"Error in Gemini disease prediction: {e}")
        return f"Error analyzing image with Gemini: {str(e)}"


# NOTE: A Gemini-based get_yield_estimate() used to live here. Removed -
# it was unreachable (nothing ever actually dispatched a message to
# YieldPredictorAgent, see the routing fix in agents.py::VoiceAssistantAgent)
# and referenced YieldInput fields that don't exist (area_size). Yield
# predictions now go through a single path everywhere - the trained ML
# model in app/services/yield_prediction_service.py::predict_yield - used
# by both the /predict REST endpoint and the chat/voice agents
# (app/core/agents.py::YieldPredictorAgent).


# --- Voice Command Processing Function ---
async def process_voice_command_ai(transcript: str, language: str = "en") -> str:
    """
    Processes a voice transcript using Gemini to understand intent and generate a response.
    """
    if not gemini_client:
        return "Error: Gemini text model is not configured."

    # Basic language code mapping (expand as needed)
    lang_map = {"en": "English", "hi": "Hindi", "mr": "Marathi"}
    language_name = lang_map.get(language, "English") # Default to English if code unknown

    # Context about the app's capabilities
    app_capabilities = """
    The FarmGenius app can:
    1. Provide practical, text-based crop health guidance based on symptoms you describe.
    2. Predict crop yield based on inputs like crop type, area, region, soil, weather.
    3. Provide mock information about local market prices for crops like Wheat and Onion in Baramati.
    """

    try:
        prompt = f"""You are the voice interface for the FarmGenius agricultural app, assisting a farmer in Baramati, Maharashtra.
        The user, speaking {language_name}, said: "{transcript}"

        App Capabilities:
        {app_capabilities}

        Your tasks:
        1. Understand the user's intent based on their statement. Does the user want to:
            - Get analysis of the last uploaded image?
            - Ask for a yield prediction (they might mention crop, area etc.)?
            - Ask about market prices (they might mention crop names)?
            - Something else (greet, ask for help)?
        3. Generate a concise and helpful response **in {language_name}**.
        4. If the intent is clear and relates to an app capability:
            - For crop health: Ask the user to describe symptoms (e.g., yellowing, spots, wilting), crop type, and location rather than requesting photos.
            - For yield prediction: If they provided details, acknowledge them. If not, ask for necessary details like crop type, area, etc.
            - For market prices: Provide the mock data if they ask for Wheat/Onion prices in Baramati, otherwise state which prices are available.
        4. If the intent is unclear or unrelated to app capabilities, politely state what the app can do or ask for clarification.
        5. Keep the response relatively short and easy to understand for a voice interaction.
        """

        # Generate content using the supported SDK method for this version.
        return await generate_text(prompt)

    except Exception as e:
        print(f"Error in Gemini voice processing: {e}")
        # Consider more specific error handling based on potential Gemini exceptions
        return f"Error processing voice command with Gemini: {str(e)}"


# --- (Optional) Market Data AI Summary ---
async def get_market_summary_ai(market_data: list) -> str:
    """
    Generates a brief summary of market data using Gemini.
    """
    if not gemini_client:
        return "Error: Gemini text model is not configured."
    if not market_data:
        return "No market data available to summarize."

    try:
        data_string = "\n".join([f"- {item['crop']}: {item['price_per_quintal']} INR/quintal at {item['location']}" for item in market_data])

        prompt = f"""Here is some recent market data from Baramati Mandi:
        {data_string}

        Provide a very brief (1-2 sentence) summary highlighting any notable price points or trends based ONLY on this data.
        Respond in English.
        """

        return await generate_text(prompt)

    except Exception as e:
        print(f"Error generating market summary: {e}")
        # Consider more specific error handling based on potential Gemini exceptions
        return f"Error generating market summary with Gemini: {str(e)}"