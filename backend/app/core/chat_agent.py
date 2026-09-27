"""
Farming-focused AI Chat Agent for CropIQ
This module provides a sophisticated chat agent with specialized knowledge
across crop health, weather, and markets, scoped to farming-related topics.
"""
import logging
from typing import Dict, List, Any, Optional
import json
import asyncio
import re

from app.core.config import get_settings
from app.core.multi_agent import Agent, AgentType, Message, coordinator, context_protocol
from app.services.market_scraper import get_scraper, get_all_prices, get_latest_snapshot
from app.services.yield_prediction_service import get_geocode_data, get_weather_data, CROP_COEFFICIENTS

try:
    from google import genai
except Exception:  # pragma: no cover - library may be missing in some environments
    genai = None

try:
    from upstash_vector import Index as UpstashVectorIndex
except Exception:  # pragma: no cover - library may be missing in some environments
    UpstashVectorIndex = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load settings
settings = get_settings()

# Crop vocabulary reused from the yield model's coefficient table, so intent
# detection recognizes the same crop names the rest of the app already knows
# about rather than maintaining a second, drifting list.
_KNOWN_CROPS = sorted(CROP_COEFFICIENTS.keys(), key=len, reverse=True)

_MARKET_KEYWORDS = ["price", "prices", "market", "mandi", "sell", "selling", "rate", "rates", "cost", "quintal"]
_WEATHER_KEYWORDS = ["weather", "forecast", "rain", "rainfall", "temperature", "climate", "humidity", "monsoon", "storm"]


_LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
    "kn": "Kannada", "gu": "Gujarati", "bn": "Bengali", "pa": "Punjabi", "ml": "Malayalam",
}


def _detect_intent(text: str) -> str:
    """Cheap keyword-based intent check - good enough to decide which live
    data source (if any) to ground the answer in before calling Gemini.
    This mirrors the routing already used for voice commands in agents.py."""
    lowered = text.lower()
    if any(word in lowered for word in _MARKET_KEYWORDS):
        return "market"
    if any(word in lowered for word in _WEATHER_KEYWORDS):
        return "weather"
    return "general"


def _extract_crop(text: str) -> Optional[str]:
    """Word-boundary match against known crop names - a plain substring
    check would misfire on things like "market prices" containing "rice"."""
    lowered = text.lower()
    for crop in _KNOWN_CROPS:
        if re.search(r'\b' + re.escape(crop.lower()) + r'\b', lowered):
            return crop
    return None


def _flag_unverified_numbers(response: str, live_data_block: str) -> str:
    """Cross-check ₹ amounts and percentages the model cited in its answer
    against the real [LIVE DATA] block it was given. The system prompt
    already tells it not to invent numbers, but that's a request, not a
    constraint - models still slip occasionally. This is a blunt safety
    net for exactly that failure mode: it won't catch every fabrication
    (e.g. a wrong number disguised as a date, or hallucinated prose with no
    digits), but it catches the specific, highest-risk case of a confident
    price/percentage sitting right next to real ones.

    Numbers are compared with commas stripped so formatting differences
    (e.g. "2,450" vs "2450") don't cause false positives.
    """
    normalize = lambda s: s.replace(',', '').strip()
    trusted = set(re.findall(r'\d+(?:\.\d+)?', live_data_block.replace(',', '')))

    rupee_claims = [normalize(m) for m in re.findall(r'₹\s?([\d,]+(?:\.\d+)?)', response)]
    pct_claims = [normalize(m) for m in re.findall(r'(\d+(?:\.\d+)?)\s?%', response)]

    unverified = [f"₹{c}" for c in rupee_claims if c not in trusted]
    unverified += [f"{c}%" for c in pct_claims if c not in trusted]

    if unverified:
        logger.warning(f"chat_assistant cited figures not present in the live data it was given: {unverified}")
        response += (
            "\n\n_(Note: please double-check the figures above against Agmarknet or "
            "your local mandi/weather source before relying on them.)_"
        )
    return response


class ChatAgent(Agent):
    """
    Farming-focused AI chat agent with specialized knowledge across crop
    health, weather, and markets - scoped to agricultural topics, not a
    general-purpose chatbot.
    """
    
    def __init__(self):
        super().__init__(AgentType.CHAT_ASSISTANT)
        self.register_handler("chat", self.handle_chat)
        self.register_handler("stream_chat", self.handle_stream_chat)
        
        # Initialize AI models
        self._init_ai_models()
        
        # System prompt
        # This used to be split across four separate agents/personas (general
        # assistant, market expert, weather advisor, crop doctor), each with
        # its own Gemini client, its own model string, and no shared memory
        # between them - switching "mode" mid-conversation silently lost
        # context. They've been merged into one assistant with one unified
        # prompt that carries all four areas of expertise, so the model
        # itself figures out which knowledge is relevant per message instead
        # of requiring the user to pick a persona.
        self.general_system_prompt = """You are CropIQ, an advanced AI assistant specialized in helping farmers across India.
    You have extensive, integrated knowledge across:
    - Crop cultivation techniques for all regions of India
    - Pest and disease management, soil health, and crop treatment for various climatic zones
    - Weather patterns, forecasts, and climate adaptation across different Indian states, including how weather affects specific crops
    - Agricultural market trends, mandi prices, and selling strategy throughout India's major agricultural markets
    - Sustainable farming practices suited to diverse Indian conditions
    - Knowledge of agriculture across different states of India including crop varieties, local practices and market information

    Draw on whichever of these areas is relevant to what the user is asking - a single
    conversation may move between crop health, weather, and market questions, and you
    should carry context across that shift rather than treating each topic separately.

    You're a farming assistant, not a general-purpose chatbot - stay scoped to
    farming and its immediate adjacent topics (crops, soil, pests and disease,
    weather, market prices, government agri-schemes, farm equipment, rural
    livelihoods, sustainable practices). Brief greetings, thanks, or small talk
    ("hi", "thank you", "who are you") are fine to answer normally and briefly.
    For anything clearly unrelated to farming - sports, entertainment, general
    trivia, celebrities, coding help, politics unrelated to agriculture, and so
    on - politely decline and steer back to what you can help with, rather than
    answering the off-topic question. For example: "I'm built specifically for
    farming questions, so I can't help with that - but I'm happy to help with
    anything about your crops, soil, weather, or market prices." Don't answer
    the off-topic question first and then add a redirect - decline directly.

    Always be helpful, accurate, and respectful within that scope. Provide
    practical, actionable advice when possible.

    When you don't know something, admit it clearly rather than making up information.
    """
        # Preference: do not ask users to upload photos in chat; request text descriptions of symptoms instead
        self.general_system_prompt += "\nPlease do not ask users to upload photos in chat. Instead, request clear text descriptions of symptoms, crop type, and location."

        # Anti-hallucination and anti-repetition guardrails. The greeting
        # instruction matters most when session memory is intact (see
        # _get_chat_history) - with real history present, there's no reason
        # for the model to keep re-introducing itself turn after turn.
        self.general_system_prompt += (
            "\n\nImportant behavioral rules:\n"
            "- Introduce yourself ('I'm CropIQ...') at most once, only if this is "
            "clearly the very first message of a new conversation. Never repeat a "
            "greeting or self-introduction in later replies - respond to the question "
            "directly instead.\n"
            "- Don't pad answers with filler openers like 'Great question!' or restating "
            "the user's question back to them before answering.\n"
            "- Never invent specific numbers, prices, statistics, study results, place "
            "names, or dates that were not given to you in this conversation or in a "
            "[LIVE DATA] block. If you don't have a real figure, say so plainly and give "
            "general guidance instead of a fabricated one.\n"
            "- If you're not sure about something, say you're not sure rather than "
            "guessing confidently."
        )

        # How to use live data blocks (see _get_market_context / _get_weather_context
        # below) that get prepended to the user's message for market/weather questions.
        self.general_system_prompt += (
            "\n\nSometimes a message will include a block starting with '[LIVE DATA'. "
            "That block contains real, current figures fetched moments ago from a real "
            "data source (Agmarknet for market prices, OpenWeather for weather). Treat "
            "those numbers as ground truth - build your quantitative answer on them rather "
            "than estimating your own, and briefly mention the source (e.g. 'per Agmarknet' "
            "or 'per OpenWeather') so the user knows it's live data, not a guess. If the "
            "block says no data was found, say so plainly instead of inventing figures."
        )

        # Extra-strict rule for the two categories where a confident-but-wrong
        # number causes real harm rather than just an inaccurate answer: an
        # incorrect pesticide/fertilizer dose can damage a crop, and scheme
        # amounts change every budget cycle so a remembered figure is often
        # stale even when it sounds authoritative.
        self.general_system_prompt += (
            "\n\nFor chemical/fertilizer dosages and government scheme amounts "
            "specifically: never state an exact quantity, rate, or rupee amount from "
            "memory. Describe the general approach instead, and tell the user to "
            "confirm the precise figure with their local Krishi Vigyan Kendra, "
            "agriculture extension officer, or the scheme's official page - unless "
            "that exact figure was given to you in this conversation, a [LIVE DATA] "
            "block, or a search result you're citing."
        )

        # How to treat retrieved KCC archive material. Worth stating explicitly:
        # retrieval makes old advice *available*, not *current* - a dosage
        # pulled from a 2018 call log is still an unverified figure, just
        # fetched instead of remembered.
        self.general_system_prompt += (
            "\n\nIf a [REFERENCE] block of past Kisan Call Centre answers is provided, "
            "treat it as real expert practice from India's national farmer helpline "
            "archive - it's a genuine reference point, not a guess. If the user's "
            "location is known (given earlier in the message as 'Location: ...'), use "
            "it: adapt region-specific details like sowing dates, varieties, or local "
            "practices to what actually fits that location, rather than repeating the "
            "archived answer's specifics if they were logged from elsewhere in India. "
            "If the user's location isn't known, answer generally and suggest they "
            "share their location or district for advice tailored to their area. "
            "Regardless of location, treat dosages, chemical names, and amounts from "
            "the archive as unverified - describe the general approach and tell the "
            "user to confirm the exact figure locally or against a current source, "
            "since pesticide formulations and scheme amounts change over time in a way "
            "location doesn't fix. Never mention the reference block itself to the user."
        )

        # Fallback model used if the primary model is transiently overloaded
        # or has hit its daily quota. Configurable via GEMINI_FALLBACK_MODEL
        # so a better-quota model can be swapped in without a code change -
        # see config.py for guidance on picking one.
        self.fallback_model_name = settings.GEMINI_FALLBACK_MODEL

        # Optional third tier: a much-higher-daily-quota safety net (e.g. an
        # open Gemma model), only ever tried if both the primary and
        # fallback models above are exhausted. Unset by default.
        self.safety_net_model_name = settings.GEMINI_SAFETY_NET_MODEL or None
        
    def _init_ai_models(self):
        """Initialize the AI models for chat"""
        self.gemini_client = None
        self.gemini_model_name = 'models/gemini-flash-latest'
        if not genai:
            logger.warning("google-genai is unavailable; chat will use fallback responses")
            return

        # Gemini setup - using only Gemini as requested
        if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_NOT_SET":
            try:
                self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
                logger.info("Gemini chat client initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing Gemini client: {e}")
                self.gemini_client = None
        else:
            logger.warning("Gemini API key not configured; chat will use fallback responses")

        # KCC archive (RAG) via Upstash Vector - optional, same "degrade
        # gracefully" treatment as everything else here. If unset, general
        # farming-advice questions just skip archive grounding and fall
        # through to search-grounded/plain answers as before.
        self.kcc_index = None
        if UpstashVectorIndex and settings.UPSTASH_VECTOR_REST_URL and settings.UPSTASH_VECTOR_REST_TOKEN:
            try:
                self.kcc_index = UpstashVectorIndex(
                    url=settings.UPSTASH_VECTOR_REST_URL,
                    token=settings.UPSTASH_VECTOR_REST_TOKEN,
                )
                logger.info("KCC archive (Upstash Vector) initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing Upstash Vector index: {e}")
                self.kcc_index = None
        else:
            logger.info("Upstash Vector not configured; chat will skip KCC-archive grounding")
    
    async def _classify_query(self, user_message: str) -> tuple:
        """Decide which live data source (if any) this message needs.

        NOTE: this previously made a separate forced-function-call Gemini
        request to classify intent (to catch paraphrases like "what will I
        get for my onions" that keyword matching misses). That doubled
        Gemini API usage on every single chat message - one call to
        classify, one to answer - which caused quota exhaustion in
        production on the very first message of the day. Reverted to plain
        keyword/regex matching, which costs zero extra API calls. If this
        gets revisited, the right fix is folding classification into the
        SAME generation call (via function declarations the model can
        choose to invoke inline) rather than a separate preceding call -
        but that needs to be verified against the live API first, not
        shipped speculatively.
        """
        return _detect_intent(user_message), _extract_crop(user_message)

    async def handle_chat(self, message: Message) -> Optional[Message]:
        """
        Handle a chat message from the user and generate a response
        """
        try:
            # Extract message content and context
            user_message = message.content.get("message", "")
            if not user_message:
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": "No message provided"},
                    message_type="error"
                )
            
            # Get session ID from context
            session_id = message.context.get("session_id") if message.context else None
            if not session_id:
                logger.warning("No session ID provided for chat")
                session_id = "default_session"
            
            # Get chat history from context
            chat_history = await self._get_chat_history(session_id)

            original_message = user_message

            # If a session-level location is stored (e.g., auto-enabled), include it in the prompt
            location = None
            latitude = None
            longitude = None
            language = "en"
            try:
                session_ctx = context_protocol.get_context(session_id) or {}
                if isinstance(session_ctx, dict):
                    # common keys: 'location' or 'auto_location'
                    location = session_ctx.get('location') or session_ctx.get('auto_location')
                    latitude = session_ctx.get('latitude')
                    longitude = session_ctx.get('longitude')
                    language = session_ctx.get('language') or language
                # Also check incoming message context for explicit location
                if message.context:
                    location = location or message.context.get('location')
                    latitude = latitude or message.context.get('latitude')
                    longitude = longitude or message.context.get('longitude')
                    language = message.context.get('language') or language
                if location:
                    # Prepend a short location context so the assistant uses local climatic info
                    user_message = f"Location: {location}. Consider local climatic conditions when answering.\nUser: {user_message}"
            except Exception:
                # don't fail chat if context lookup errors
                pass

            # Intent-aware grounding: for market/weather questions, fetch real
            # data first and hand it to Gemini as a labeled block rather than
            # letting the model guess prices or forecasts on its own. For
            # anything else, let Gemini ground itself with a live Google
            # Search instead of answering purely from training memory.
            intent = "general"
            live_data_block = None
            try:
                intent, crop_hint = await self._classify_query(original_message)
                if intent == "market":
                    live_data_block = await self._get_market_context(original_message, crop_hint=crop_hint)
                elif intent == "weather":
                    live_data_block = await self._get_weather_context(location, latitude, longitude)
                else:
                    # General farming-advice questions (pest/disease/practice/
                    # scheme queries) get background grounding from the KCC
                    # archive, on top of the live Google Search Gemini already
                    # does for "general" below - the two are complementary,
                    # not exclusive: search finds current info, the archive
                    # finds how real KCC experts have answered similar
                    # questions before.
                    kcc_block = await self._get_kcc_reference_context(original_message)
                    if kcc_block:
                        user_message = f"{kcc_block}\n\n{user_message}"
                if live_data_block:
                    user_message = f"{live_data_block}\n\n{user_message}"
            except Exception as e:
                # Live-data grounding is a bonus, not a requirement - if it
                # fails for any reason, fall through to a plain Gemini answer
                # rather than breaking the chat turn.
                logger.warning(f"Live-data grounding skipped due to error: {e}")

            # Use Gemini when available; otherwise provide a helpful fallback response.
            if self.gemini_client:
                response = await self._chat_with_gemini(
                    user_message, chat_history, use_search=(intent == "general"), language=language
                )
                if live_data_block:
                    # Only cross-check when we actually handed the model a
                    # ground-truth block to be graded against - search-grounded
                    # general answers legitimately cite figures (e.g. scheme
                    # amounts) that won't appear verbatim in any block here.
                    response = _flag_unverified_numbers(response, live_data_block)
            else:
                response = self._fallback_response(user_message, not_configured=True)
            
            # Update chat history in context
            await self._update_chat_history(session_id, user_message, response)
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"response": response},
                message_type="chat_response",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error in chat handler: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error processing chat: {str(e)}"},
                message_type="error"
            )
    
    async def handle_stream_chat(self, message: Message) -> Optional[Message]:
        """
        Handle a streaming chat message from the user
        """
        # This is just a placeholder - in a real implementation
        # this would use the streaming capabilities of Gemini
        return await self.handle_chat(message)
    
    async def _get_market_context(self, user_message: str, crop_hint: Optional[str] = None) -> Optional[str]:
        """Fetch real market prices relevant to the question and format them
        as a labeled block for Gemini to reason over, instead of asking
        Gemini to recall or guess prices from its training data.

        Tries the live Agmarknet call first (freshest, but can fail - rate
        limits, transient outages, or the endpoint blocking a given
        server's IP). Falls back to the Redis-backed daily snapshot log
        (the same store the trend chart reads from, kept current by the
        /market/cron/refresh-snapshot job) so a live-request hiccup doesn't
        mean the assistant has no real numbers at all.
        """
        # Prefer the crop the classifier already extracted (handles
        # paraphrases/multi-word names) and only fall back to the plain
        # regex if the classifier didn't return one.
        crop = crop_hint or _extract_crop(user_message)
        records = []
        try:
            if crop:
                scraper = get_scraper("agmarknet")
                records = await scraper.get_prices(crop)
            else:
                # No specific crop mentioned - give a small general snapshot
                records = (await get_all_prices())[:8]
        except Exception as e:
            logger.warning(f"Live Agmarknet fetch failed for chat, will try Redis snapshot: {e}")
            records = []

        if records:
            lines = []
            for r in records[:8]:
                price = r.get("price_per_quintal")
                if price is None:
                    continue
                change = r.get("price_change_pct")
                change_str = f", {change:+.1f}% vs yesterday" if change is not None else ""
                msp = r.get("msp_price")
                msp_str = f", MSP ₹{msp:.0f}/quintal" if msp else ""
                lines.append(f"- {r.get('crop')}: ₹{price:.0f}/quintal{change_str}{msp_str} (as of {r.get('date')})")
            if lines:
                return "[LIVE DATA: market, source=Agmarknet]\n" + "\n".join(lines)

        # Live fetch came back empty or failed - fall back to the last
        # snapshot we already have cached in Redis.
        try:
            snapshot = await get_latest_snapshot()
        except Exception as e:
            logger.error(f"Redis snapshot fallback also failed for chat: {e}")
            snapshot = None

        if not snapshot:
            target = crop or "that commodity"
            return (
                f"[LIVE DATA: market] No current Agmarknet listing and no cached snapshot found for {target} - "
                "answer cautiously and say prices should be confirmed locally."
            )

        prices = snapshot["prices"]
        if crop:
            matches = {name: p for name, p in prices.items() if crop.lower() in name.lower()}
        else:
            matches = dict(list(prices.items())[:8])

        if not matches:
            target = crop or "that commodity"
            return (
                f"[LIVE DATA: market] No cached price found for {target} either - "
                "answer cautiously and say prices should be confirmed locally."
            )

        lines = [f"- {name}: ₹{price:.0f}/quintal" for name, price in matches.items()]
        return (
            f"[LIVE DATA: market, source=Agmarknet (cached snapshot from {snapshot['date']}, "
            "today's live request failed)]\n" + "\n".join(lines)
        )

    async def _get_weather_context(
        self, location: Optional[str], latitude: Optional[float], longitude: Optional[float]
    ) -> Optional[str]:
        """Fetch real current conditions + a short-range rainfall estimate
        from OpenWeather and format them as a labeled block for Gemini,
        instead of asking Gemini to guess a forecast."""
        lat, lon = latitude, longitude
        try:
            if lat is None or lon is None:
                if not location:
                    return (
                        "[LIVE DATA: weather] No location is set for this chat, so no live "
                        "forecast could be fetched - ask the user for their village/district/state."
                    )
                geo = await asyncio.to_thread(get_geocode_data, location)
                if not geo:
                    return f"[LIVE DATA: weather] Could not resolve the location '{location}' to fetch a live forecast."
                lat, lon = geo.get("lat"), geo.get("lon")

            weather = await asyncio.to_thread(get_weather_data, lat, lon)
        except Exception as e:
            logger.error(f"Error fetching live weather data for chat: {e}")
            return "[LIVE DATA: weather] Could not reach OpenWeather right now - answer from general seasonal knowledge and flag that it isn't a live forecast."

        if not weather:
            return "[LIVE DATA: weather] OpenWeather returned no data for this location right now."

        where = f" near {location}" if location else ""
        return (
            f"[LIVE DATA: weather, source=OpenWeather{where}]\n"
            f"- Current temperature: {weather['current_temp']}°C\n"
            f"- Current humidity: {weather['current_humidity']}%\n"
            f"- Current conditions: {weather['current_conditions']}\n"
            f"- Estimated rainfall over the next month (from 5-day forecast trend): "
            f"{weather['monthly_rainfall_estimate']:.1f} cm"
        )

    async def _get_kcc_reference_context(self, user_message: str) -> Optional[str]:
        """Retrieve similar past Kisan Call Centre expert Q&A pairs from
        Upstash Vector, for background grounding on general farming-advice
        questions (pest/disease/practice/scheme queries that aren't live
        market or weather questions).

        Deliberately labeled [REFERENCE], not [LIVE DATA]: this is historical
        call-log data from the Kisan Call Centre archive - India's national
        farmer helpline program (circa 2015-2021) - not a live or
        verified-current source. The system prompt tells the model to treat
        any dosage/figure from this block the same as anything else it isn't
        certain is current - restate the approach and tell the user to
        confirm locally, rather than quote it as settled fact.

        Note on coverage: KCC is a national program, but this particular
        extract is not an evenly distributed national sample - see
        KCC_RAG_SETUP.md for the measured breakdown. That's why the block
        warns the model not to assume the advice fits the user's region.
        """
        if not self.kcc_index:
            return None
        try:
            results = await asyncio.to_thread(
                self.kcc_index.query,
                data=user_message,
                top_k=3,
                include_metadata=True,
                include_data=True,
            )
        except Exception as e:
            logger.warning(f"KCC archive lookup failed, skipping: {e}")
            return None

        # Score threshold is a rough starting point, not a tuned value - I
        # can't call the live Upstash index from this environment to
        # calibrate it against real query traffic, so watch actual retrieval
        # quality once this is live and adjust if it's too strict/loose.
        matches = [r for r in (results or []) if r.score is not None and r.score >= 0.80]
        if not matches:
            return None

        lines = [
            "[REFERENCE: past answers from India's Kisan Call Centre farmer helpline "
            "archive - real expert practice, but historical (not verified current) and "
            "logged from a specific place. If the user's location is known, adapt any "
            "regional specifics (sowing dates, varieties, local practices) to fit it. "
            "Treat dosages, chemical names, and amounts as unverified regardless of "
            "location - describe the approach and tell the user to confirm the exact "
            "figure locally.]"
        ]
        for i, m in enumerate(matches, 1):
            past_question = m.data or ""
            past_answer = (m.metadata or {}).get("answer", "")
            if past_question and past_answer:
                lines.append(f"{i}. Past Q: \"{past_question}\" -> Past A: \"{past_answer}\"")
        if len(lines) == 1:
            return None
        return "\n".join(lines)

    def _append_grounding_sources(self, text: str, response) -> str:
        """When Gemini used Google Search grounding, append the real source
        links it cited - shows the user this wasn't answered from memory,
        and gives them somewhere to double-check it."""
        try:
            candidate = response.candidates[0] if response.candidates else None
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
            logger.warning(f"Could not extract grounding sources: {e}")
        return text

    async def _chat_with_gemini(
        self,
        user_message: str,
        chat_history: List[Dict[str, Any]],
        use_search: bool = False,
        language: str = "en",
    ) -> str:
        """Generate a response using Gemini, with retry-with-backoff and a
        fallback model if the primary model is transiently overloaded.

        This reliability path used to exist only on the old CropDoctorAgent;
        it's now the one path every chat message goes through, regardless of
        topic.
        """
        # Convert chat history to Gemini format - actual prior turns only.
        # The system prompt is NOT stuffed in here as a fake first turn
        # (that approach silently drops out of context after the first
        # message, since only real turns get persisted to chat_history).
        # It's passed as a proper system_instruction below instead, so it
        # stays in effect for every turn of the whole conversation.
        gemini_chat = []
        for message in chat_history:
            role = "user" if message["role"] == "user" else "model"
            gemini_chat.append({"role": role, "parts": [{"text": message["content"]}]})

        system_instruction = self.general_system_prompt
        if language and language != "en":
            lang_name = _LANGUAGE_NAMES.get(language, language)
            system_instruction += (
                f"\n\nRespond in {lang_name} ({language}), regardless of what language the "
                f"conversation history above is in, unless the user explicitly asks for a "
                f"different language."
            )

        def _build_config(allow_search: bool) -> dict:
            cfg = {
                "system_instruction": system_instruction,
                # Lower than Gemini's ~1.0 default - factual farming
                # advice should stay close to what the model
                # actually knows rather than getting creative.
                "temperature": 0.3,
            }
            if use_search and allow_search:
                # Market and weather questions already get grounded in real
                # Agmarknet/OpenWeather data above - this covers everything
                # else (government schemes, general agri knowledge, current
                # events) by letting Gemini search the live web instead of
                # answering purely from training memory.
                cfg["tools"] = [{"google_search": {}}]
            return cfg

        def _classify_error(err_str: str) -> str:
            """Distinguish a hard quota cap (won't recover for hours - retrying
            immediately is pointless) from a short-lived rate limit (worth a
            quick backoff) from anything else (not worth retrying at all)."""
            lowered = err_str.lower()
            if "check your plan and billing" in lowered or ("quota" in lowered and "resource_exhausted" in lowered):
                return "quota_exhausted"
            if any(x in lowered for x in ['429', 'too many requests', 'rate limit', '503', 'unavailable', 'high demand', 'temporarily unavailable']):
                return "rate_limited"
            return "other"

        async def _send_with_retries(model_name: str, max_retries: int = 1, allow_search: bool = True) -> str:
            call_config = _build_config(allow_search)
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    chat = self.gemini_client.chats.create(
                        model=model_name,
                        history=gemini_chat,
                        config=call_config,
                    )
                    response = await asyncio.to_thread(chat.send_message, user_message)
                    text = getattr(response, "text", None) or (
                        response.candidates[0].content if response.candidates else str(response)
                    )
                    return self._append_grounding_sources(text, response) if (use_search and allow_search) else text
                except Exception as e:
                    last_exc = e
                    category = _classify_error(str(e))
                    if category == "other":
                        raise
                    if category == "quota_exhausted":
                        # A daily/monthly cap won't clear up in the next few
                        # seconds - burning 3 retries here just adds latency
                        # for no benefit. Fail fast so the caller can move on
                        # to the fallback model (which may have separate quota).
                        logger.error(f"chat_assistant {model_name} quota exhausted, not retrying: {e}")
                        raise
                    if attempt < max_retries:
                        backoff = 0.5 * (2 ** (attempt - 1))
                        logger.warning(f"chat_assistant {model_name} attempt {attempt} failed: {e}; retrying in {backoff}s")
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(f"chat_assistant {model_name} all {max_retries} attempts failed: {e}")
            raise last_exc

        try:
            # Only 2 attempts (1 retry) on the primary, not 3 - with two
            # more independently-quota'd tiers below to fall through to,
            # hammering the same possibly-overloaded model repeatedly just
            # adds latency for little extra benefit.
            return await _send_with_retries(self.gemini_model_name, max_retries=2)
        except Exception as e1:
            category = _classify_error(str(e1))
            logger.warning(f"chat_assistant primary model failed: {e1} (category={category})")
            if category not in ("quota_exhausted", "rate_limited"):
                logger.error(f"chat_assistant non-retryable error: {e1}")
                return self._fallback_response(user_message, error=str(e1))

            try:
                # Only one attempt on the fallback model, not a full retry
                # loop - if the primary is quota-exhausted or rate
                # limited, hammering the fallback 3x too just adds delay.
                return await _send_with_retries(
                    self.fallback_model_name,
                    max_retries=1,
                    allow_search=False,
                )
            except Exception as e2:
                category2 = _classify_error(str(e2))
                logger.warning(f"chat_assistant fallback model failed: {e2} (category={category2})")
                if not self.safety_net_model_name or category2 not in ("quota_exhausted", "rate_limited"):
                    logger.error(f"chat_assistant fallback model also failed: {e2}")
                    return self._fallback_response(user_message, error=str(e2))

                try:
                    # Third tier - a separate, much-higher-daily-quota model.
                    # Only reached once both the primary and fallback tiers
                    # above have genuinely run out of quota, not just failed
                    # for some other reason. Search grounding is skipped
                    # here (allow_search=False): the safety-net model is
                    # typically an open Gemma model, which doesn't support
                    # Gemini's Search grounding tool - requesting it would
                    # just add a guaranteed-failing, guaranteed-slow call.
                    return await _send_with_retries(self.safety_net_model_name, max_retries=1, allow_search=False)
                except Exception as e3:
                    logger.error(f"chat_assistant safety-net model also failed: {e3}")
                    return self._fallback_response(user_message, error=str(e3))

    def _fallback_response(self, user_message: str, error: Optional[str] = None, not_configured: bool = False) -> str:
        """Plain, honest message when the AI service can't be reached.

        Deliberately NOT the previous behavior of guessing pseudo-advice from
        keywords in the message and appending a category-specific technical
        explanation (quota/rate-limit/etc). A guessed-at answer dressed up as
        help is worse than plainly saying the assistant is down - the user
        can't tell the difference between real guidance and a keyword-matched
        guess, and the "should clear up on its own" wording was also
        sometimes just wrong (e.g. an expired trial doesn't self-resolve).
        `error` is accepted for signature compatibility with existing call
        sites (which already log the real exception separately) but is
        intentionally not surfaced to the user here.
        """
        if not_configured:
            return "The assistant isn't set up yet. Please check back later."
        return "Sorry, I'm unable to respond right now. Please try again in a little while."
    
    async def _get_chat_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get chat history from context"""
        chat_history_key = f"chat_history_{session_id}"
        chat_history = context_protocol.get_context(chat_history_key)
        return chat_history or []
    
    async def _update_chat_history(self, session_id: str, user_message: str, ai_response: str):
        """Update chat history in context"""
        chat_history_key = f"chat_history_{session_id}"
        chat_history = context_protocol.get_context(chat_history_key) or []
        
        # Add user message
        chat_history.append({
            "role": "user",
            "content": user_message,
            "timestamp": asyncio.get_event_loop().time()
        })
        
        # Add AI response
        chat_history.append({
            "role": "assistant",
            "content": ai_response,
            "timestamp": asyncio.get_event_loop().time()
        })
        
        # Limit history length to prevent context overflow
        # Keep the most recent 30 messages (15 exchanges)
        if len(chat_history) > 30:
            chat_history = chat_history[-30:]
        
        # Update context
        context_protocol.set_context(chat_history_key, chat_history)

# Function to create and register the chat agent
def init_chat_agent():
    """Initialize and register the chat agent"""
    chat_agent = ChatAgent()
    coordinator.register_agent(chat_agent)
    return chat_agent
