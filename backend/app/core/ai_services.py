from google import genai
from PIL import Image as PILImage
import io
import asyncio
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

# Same 3-tier chain (and same env vars) as chat_agent.py - see config.py for
# how to pick these. Kept as separate module-level names because this file
# has its own Gemini client, but pulling from the same settings keeps the
# two in sync without needing to duplicate the env vars themselves.
gemini_fallback_model_name = settings.GEMINI_FALLBACK_MODEL
gemini_safety_net_model_name = settings.GEMINI_SAFETY_NET_MODEL or None

# Reused by every disease-related prompt below (image analysis + text
# treatment lookups) - these are the two paths in the app with no live,
# structured data source to ground on (unlike market prices/weather, which
# get real Agmarknet/OpenWeather figures handed to them directly). Search
# grounding plus this instruction is how we keep them honest instead.
_ANTI_HALLUCINATION_NOTE = (
    "\n\nImportant: only state a diagnosis, treatment, product name, dosage, "
    "or statistic if you're reasonably confident it's correct - either from "
    "your own knowledge or from a web search result you actually retrieved. "
    "If the image is unclear, the symptoms described could match more than "
    "one issue, or you're just not sure, say that plainly (e.g. 'this could "
    "be X or Y - I'm not confident enough to say which' or 'I don't have "
    "enough information to answer that confidently') instead of guessing. "
    "Never invent a disease name, product name, dosage, or figure you aren't "
    "sure is real."
)


def _append_grounding_sources(text: str, response) -> str:
    """When Gemini used Google Search grounding, append the real source
    links it cited - shows the user this wasn't answered from memory alone,
    and gives them somewhere to double-check it. Mirrors chat_agent.py's
    version; kept separate since this module has its own Gemini client."""
    try:
        candidate = response.candidates[0] if getattr(response, "candidates", None) else None
        metadata = getattr(candidate, "grounding_metadata", None) if candidate else None
        chunks = getattr(metadata, "grounding_chunks", None) if metadata else None
        if not chunks:
            return text
        seen = set()
        links = []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web and web.uri and web.uri not in seen:
                seen.add(web.uri)
                links.append(f"- [{web.title or web.domain or web.uri}]({web.uri})")
            if len(links) >= 4:
                break
        if links:
            return f"{text}\n\n**Sources:**\n" + "\n".join(links)
    except Exception as e:
        print(f"AI_SERVICES: Could not extract grounding sources: {e}")
    return text

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


def _classify_error(err_str: str) -> str:
    """Distinguish a hard quota cap (won't clear for hours - retrying
    immediately is pointless) from a short-lived rate limit (worth one quick
    retry) from anything else (not worth retrying at all). Mirrors
    chat_agent.py's version - kept in sync manually since the two modules
    use separate Gemini clients."""
    lowered = err_str.lower()
    if "check your plan and billing" in lowered or ("quota" in lowered and "resource_exhausted" in lowered):
        return "quota_exhausted"
    if any(x in lowered for x in ['429', 'too many requests', 'rate limit', '503', 'unavailable', 'high demand', 'temporarily unavailable']):
        return "rate_limited"
    return "other"


async def _generate_with_fallback(
    contents: list,
    primary_model: str,
    use_search: bool = False,
    include_safety_net: bool = True,
) -> str:
    """Try `primary_model`, then the configured fallback model, then
    (optionally) the configured safety-net model - each an independent
    quota pool - only moving on when a tier is quota-exhausted or
    rate-limited, not for other errors (retrying elsewhere won't fix a bad
    request). Raises on total failure so each caller can produce its own
    friendly, on-brand error string.

    include_safety_net=False skips the third tier entirely - use this for
    image content, since the safety-net model (typically an open Gemma
    model) most likely can't process images the way Gemini can, and there's
    no point spending a call finding that out.
    """

    async def _attempt(model_name: str, max_retries: int, allow_search: bool) -> str:
        kwargs = {"model": model_name, "contents": contents}
        if use_search and allow_search:
            kwargs["config"] = {"tools": [{"google_search": {}}]}
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await asyncio.to_thread(gemini_client.models.generate_content, **kwargs)
                text = getattr(response, "text", None) or (
                    response.candidates[0].content if getattr(response, "candidates", None) else str(response)
                )
                return _append_grounding_sources(text, response) if (use_search and allow_search) else text
            except Exception as e:
                last_exc = e
                category = _classify_error(str(e))
                if category in ("other", "quota_exhausted"):
                    # "other": retrying won't help. "quota_exhausted": a
                    # daily/monthly cap won't clear in the next few seconds -
                    # fail fast so the caller can move to the next tier
                    # (which may have separate quota) instead of burning
                    # retries here for no benefit.
                    raise
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        raise last_exc

    try:
        # 2 attempts (1 retry) on the primary - with other tiers to fall
        # through to, hammering the same possibly-overloaded model
        # repeatedly just adds latency for little benefit.
        return await _attempt(primary_model, 2, allow_search=True)
    except Exception as e1:
        category = _classify_error(str(e1))
        if category not in ("quota_exhausted", "rate_limited"):
            raise
        try:
            # Only one attempt on the fallback model - if the primary is
            # quota-exhausted or rate limited, hammering the fallback with
            # retries too just adds delay.
            return await _attempt(gemini_fallback_model_name, 1, allow_search=True)
        except Exception as e2:
            category2 = _classify_error(str(e2))
            if not include_safety_net or not gemini_safety_net_model_name or category2 not in ("quota_exhausted", "rate_limited"):
                raise
            # Search grounding is skipped on the safety-net tier: it's
            # typically an open Gemma model, which doesn't support Gemini's
            # Search grounding tool the same way.
            return await _attempt(gemini_safety_net_model_name, 1, allow_search=False)

async def generate_text(prompt: str, use_search: bool = False) -> str:
    """Generate a text response from Gemini, automatically falling through
    the configured fallback and safety-net models if the primary is
    rate-limited or its daily quota is exhausted (see _generate_with_fallback).

    use_search=True gives the model Google Search as an available tool - it
    decides on its own whether a given prompt actually needs a search, so
    this doesn't force a web lookup on every call, just makes one possible
    for prompts (like disease treatment lookups) that have no other source
    of ground-truth data to draw on.
    """
    if not gemini_client:
        return "Error: Gemini text model is not configured."

    try:
        return await _generate_with_fallback(
            contents=[prompt],
            primary_model=gemini_text_model_name,
            use_search=use_search,
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
        """ + _ANTI_HALLUCINATION_NOTE + (
            "\n\nYou have Google Search available - use it if it would help confirm "
            "an identification you're unsure of, or find a locally relevant treatment "
            "product, rather than guessing from memory alone."
        )

        text = await _generate_with_fallback(
            contents=[prompt, pil_img],
            primary_model=gemini_vision_model_name,
            use_search=True,
            include_safety_net=False,  # safety net is typically text-only Gemma - can't do vision
        )
        return text

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
    The CropIQ app can:
    1. Provide practical, text-based crop health guidance based on symptoms you describe.
    2. Predict crop yield based on inputs like crop type, area, region, soil, weather.
    3. Provide mock information about local market prices for crops like Wheat and Onion in Baramati.
    """

    try:
        prompt = f"""You are the voice interface for the CropIQ agricultural app, assisting a farmer in Baramati, Maharashtra.
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