"""
Farming-focused AI Chat Agent for CropIQ
This module provides a sophisticated chat agent with specialized knowledge
across crop health, weather, and markets, scoped to farming-related topics.
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
import json
import asyncio
import re
import time

from app.core.config import get_settings
from app.core.multi_agent import Agent, AgentType, Message, coordinator, context_protocol
from app.core import chat_tools

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - library may be missing in some environments
    genai = None
    types = None

try:
    from upstash_vector import Index as UpstashVectorIndex
except Exception:  # pragma: no cover - library may be missing in some environments
    UpstashVectorIndex = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load settings
settings = get_settings()

_LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu",
    "kn": "Kannada", "gu": "Gujarati", "bn": "Bengali", "pa": "Punjabi", "ml": "Malayalam",
}

# Tool-call rounds per answer (e.g. weather -> prices -> answer). Bounded so a
# confused model can't loop and burn quota.
MAX_TOOL_ROUNDS = 3

# Server-side history kept per session (messages, not exchanges)
MAX_HISTORY_MESSAGES = 30


_FOLLOWUPS_LINE = re.compile(r"\n?[ \t*_]*FOLLOWUPS?[ \t*_]*:[ \t*_]*(.+?)[ \t*_]*$", re.IGNORECASE)


def _split_followups(text: str) -> Tuple[str, List[str]]:
    """Separate the trailing 'FOLLOWUPS: a | b | c' line from the answer."""
    match = _FOLLOWUPS_LINE.search(text.rstrip())
    if not match:
        return text, []
    questions = [q.strip(" -*\"'") for q in match.group(1).split("|")]
    return text[:match.start()].rstrip(), [q for q in questions if 2 < len(q) <= 120][:3]


def _to_number(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _flag_unverified_numbers(response: str, trusted_text: str) -> str:
    """Cross-check ₹ amounts and percentages the model cited in its answer
    against the real tool data it was given. The system prompt already tells
    it not to invent numbers, but that's a request, not a constraint - models
    still slip occasionally. This is a blunt safety net for exactly that
    failure mode: it won't catch every fabrication, but it catches the
    specific, highest-risk case of a confident price/percentage sitting right
    next to real ones.

    Matching is tolerant of formatting and rounding: "₹2,450" matches 2450,
    "₹1.01 lakh" matches 101,375, and anything within 1% of a real figure
    counts as quoted rather than invented.
    """
    trusted = [n for n in (_to_number(m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", trusted_text)) if n is not None]

    def is_trusted(value: float) -> bool:
        return any(abs(value - t) <= max(0.01 * abs(t), 0.051) for t in trusted)

    unverified = []
    for amount, unit in re.findall(r"₹\s?(\d[\d,]*(?:\.\d+)?)\s*(lakh|crore)?", response, flags=re.IGNORECASE):
        value = _to_number(amount)
        if value is None:
            continue
        scaled = value * {"lakh": 1e5, "crore": 1e7}.get(unit.lower(), 1) if unit else value
        if not (is_trusted(value) or is_trusted(scaled)):
            unverified.append(f"₹{amount}{' ' + unit if unit else ''}")
    for pct in re.findall(r"(\d+(?:\.\d+)?)\s?%", response):
        value = _to_number(pct)
        if value is not None and not is_trusted(value):
            unverified.append(f"{pct}%")

    if unverified:
        logger.warning(f"chat_assistant cited figures not present in its tool data: {unverified}")
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
        self.general_system_prompt += (
            "\nPlease do not ask users to upload photos in chat. Instead, request clear text descriptions "
            "of symptoms, crop type, and location. For photo-based diagnosis, point them to CropIQ's "
            "Disease Detector page."
        )

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
            "names, or dates that were not given to you in this conversation or by a "
            "tool. If you don't have a real figure, say so plainly and give general "
            "guidance instead of a fabricated one.\n"
            "- If you're not sure about something, say you're not sure rather than "
            "guessing confidently."
        )

        # Tools (see chat_tools.py). The model decides when to call them, in
        # any language, with the conversation in view - so follow-ups like
        # "and tomorrow?" after a weather question still get real data.
        self.general_system_prompt += (
            "\n\nYou have tools that fetch real, current data. Use them instead of answering "
            "from memory whenever they apply - including for follow-up questions:\n"
            "- get_market_prices: any question about a crop's price, rate, bhav, MSP, or whether to sell.\n"
            "- get_weather_forecast: weather, rain, temperature, and timing decisions (spraying, "
            "irrigation, sowing, harvesting). Base timing advice on the actual daily forecast.\n"
            "- estimate_yield_and_income: when the user asks how much they'll harvest or earn. If "
            "you don't know their crop, land area, or state yet, ask for them first (one short "
            "question), then call it.\n"
            "- search_web: current government schemes/subsidies, regulations, outbreaks, or news.\n"
            "Always pass tool arguments in English, whatever language the user writes in. Treat "
            "tool results as ground truth, quote their figures as given, and briefly name the "
            "source (e.g. 'per Agmarknet', 'per Open-Meteo', 'per CropIQ's yield model'). Market "
            "prices are all-India averages, not a specific local mandi - say so. If a tool returns "
            "an error or no data, say so plainly instead of inventing figures."
        )

        # Suggested next questions, shown as tappable chips under the answer.
        # Split off by _split_followups before the text is shown or stored.
        self.general_system_prompt += (
            "\n\nAt the very end of every reply, add one final line in exactly this format:\n"
            "FOLLOWUPS: <question 1> | <question 2> | <question 3>\n"
            "with 2-3 short questions (under 10 words each) the farmer would naturally ask you "
            "next, written from the farmer's point of view, in the same language as your reply. "
            "Skip the line only for greetings or when you declined an off-topic question."
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
            "that exact figure was given to you in this conversation, by a tool, or in "
            "a search result you're citing."
        )

        # How to treat retrieved KCC archive material. Worth stating explicitly:
        # retrieval makes old advice *available*, not *current* - a dosage
        # pulled from a 2018 call log is still an unverified figure, just
        # fetched instead of remembered.
        self.general_system_prompt += (
            "\n\nIf a [REFERENCE] block of past Kisan Call Centre answers is provided, "
            "treat it as real expert practice from India's national farmer helpline "
            "archive - it's a genuine reference point, not a guess. If the user's "
            "location is known, use it: adapt region-specific details like sowing dates, "
            "varieties, or local practices to what actually fits that location, rather "
            "than repeating the archived answer's specifics if they were logged from "
            "elsewhere in India. If the user's location isn't known, answer generally and "
            "suggest they share their location or district for advice tailored to their area. "
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
        # gracefully" treatment as everything else here. If unset, farming-
        # advice questions just skip archive grounding.
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

            chat_history = await self._get_chat_history(session_id)

            # Location and language: explicit per-message values win over
            # whatever is stored for the session.
            location = latitude = longitude = None
            language = "en"
            try:
                session_ctx = context_protocol.get_context(session_id) or {}
                if isinstance(session_ctx, dict):
                    location = session_ctx.get('location') or session_ctx.get('auto_location')
                    latitude = session_ctx.get('latitude')
                    longitude = session_ctx.get('longitude')
                    language = session_ctx.get('language') or language
                if message.context:
                    location = message.context.get('location') or location
                    latitude = message.context.get('latitude') if message.context.get('latitude') is not None else latitude
                    longitude = message.context.get('longitude') if message.context.get('longitude') is not None else longitude
                    language = message.context.get('language') or language
            except Exception:
                # don't fail chat if context lookup errors
                pass
            # "hi-IN" (voice) and "hi" (text chat) mean the same thing here
            language = (language or "en").split("-")[0].lower()
            user_ctx = {"location": location, "latitude": latitude, "longitude": longitude}

            # Background grounding from the KCC archive (how real helpline
            # experts answered similar questions). Only added to this turn's
            # model input - never stored in history, so it can't go stale or
            # pile up across turns.
            model_input = user_message
            rag_sources: List[Dict[str, Any]] = []
            try:
                kcc_result = await self._get_kcc_reference_context(user_message)
                if kcc_result:
                    kcc_block, rag_sources = kcc_result
                    model_input = f"{kcc_block}\n\n{user_message}"
            except Exception as e:
                logger.warning(f"KCC grounding skipped due to error: {e}")

            tool_log: List[Dict[str, Any]] = []
            model_ok = False
            suggestions: List[str] = []
            if self.gemini_client:
                response, tool_log, model_ok = await self._chat_with_gemini(
                    model_input, chat_history, user_ctx, language=language
                )
                if model_ok:
                    response, suggestions = _split_followups(response)
                data_text = " ".join(
                    json.dumps(t["result"], ensure_ascii=False)
                    for t in tool_log if t["name"] in chat_tools.TOOL_PROVIDERS
                )
                if model_ok and data_text:
                    # Only cross-check when real data was fetched to grade
                    # against - plain advice answers have nothing to compare to.
                    response = _flag_unverified_numbers(response, data_text + " " + user_message)
            else:
                response = self._fallback_response(user_message, not_configured=True)

            source_info = self._build_source_info(rag_sources, tool_log, model_ok)

            # Store what the user actually typed, not the model input with
            # reference blocks - and only real answers, not error text.
            if model_ok:
                await self._update_chat_history(session_id, user_message, response)

            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"response": response, "sources": source_info, "suggestions": suggestions},
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

    async def _get_kcc_reference_context(self, user_message: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        """Retrieve similar past Kisan Call Centre expert Q&A pairs from
        Upstash Vector, for background grounding on farming-advice questions.

        Deliberately labeled [REFERENCE], not live data: this is historical
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

        # Score threshold is a rough starting point, not a tuned value -
        # watch actual retrieval quality and adjust if it's too strict/loose.
        # It also keeps price/weather questions from dragging in unrelated
        # archive entries, now that every message is looked up.
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
        sources: List[Dict[str, Any]] = []
        for i, m in enumerate(matches, 1):
            past_question = m.data or ""
            meta = m.metadata or {}
            past_answer = meta.get("answer", "")
            if past_question and past_answer:
                lines.append(f"{i}. Past Q: \"{past_question}\" -> Past A: \"{past_answer}\"")
                # Structured copy of what was retrieved, so the UI can show
                # the user exactly which archive entries backed the answer.
                sources.append({
                    "title": past_question,
                    "snippet": past_answer if len(past_answer) <= 220 else past_answer[:217].rstrip() + "...",
                    "crop": meta.get("crop"),
                    "score": round(float(m.score), 2),
                })
        if not sources:
            return None
        return "\n".join(lines), sources

    @staticmethod
    def _build_source_info(
        rag_sources: List[Dict[str, Any]],
        tool_log: List[Dict[str, Any]],
        model_ok: bool,
    ) -> Optional[Dict[str, Any]]:
        """Decide what provenance label the UI shows under the answer.

        Priority: RAG (KCC archive had relevant matches) -> live data the
        tools actually fetched -> Gemini (with web citations, if it searched).
        No label at all if the model never answered (error/fallback text
        isn't "from" anything)."""
        if not model_ok:
            return None
        web: List[Dict[str, Any]] = []
        providers: List[str] = []
        for call in tool_log:
            result = call["result"] or {}
            if call["name"] == "search_web":
                web.extend(s for s in result.get("sources", []) if s not in web)
            elif call["name"] in chat_tools.TOOL_PROVIDERS and "error" not in result and result.get("found", True):
                provider = chat_tools.TOOL_PROVIDERS[call["name"]]
                if provider not in providers:
                    providers.append(provider)

        if rag_sources:
            extra = providers or (["Gemini"] if web else [])
            return {
                "type": "rag",
                "label": " + ".join(["From RAG"] + extra),
                "citations": rag_sources,
                "web": web,
            }
        if providers:
            return {"type": "live_data", "label": "From " + " + ".join(providers), "citations": [], "web": web}
        return {"type": "gemini", "label": "From Gemini", "citations": [], "web": web}

    async def _run_tool(self, call, user_ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one function call requested by the model."""
        args = dict(call.args or {})
        try:
            if call.name == "get_market_prices":
                return await chat_tools.get_market_prices(args.get("commodity", ""))
            if call.name == "get_weather_forecast":
                return await chat_tools.get_weather_forecast(
                    user_ctx.get("latitude"), user_ctx.get("longitude"), user_ctx.get("location"),
                    place=args.get("place"),
                )
            if call.name == "estimate_yield_and_income":
                return await chat_tools.estimate_yield_and_income(
                    crop=args.get("crop"), area=float(args.get("area") or 0), state=args.get("state"),
                    area_unit=args.get("area_unit") or "acres", district=args.get("district"),
                    season=args.get("season"),
                    latitude=user_ctx.get("latitude"), longitude=user_ctx.get("longitude"),
                )
            if call.name == "search_web":
                return await chat_tools.search_web(self.gemini_client, self.gemini_model_name, args.get("query", ""))
        except Exception as e:
            logger.exception(f"Chat tool {call.name} failed")
            return {"error": f"The {call.name} tool failed ({type(e).__name__})."}
        return {"error": f"Unknown tool {call.name}"}

    async def _chat_with_gemini(
        self,
        user_message: str,
        chat_history: List[Dict[str, Any]],
        user_ctx: Dict[str, Any],
        language: str = "en",
    ) -> Tuple[str, List[Dict[str, Any]], bool]:
        """Generate a response using Gemini with tool calling, retry-with-
        backoff, and fallback models if the primary is overloaded.
        Returns (text, tool_log, model_ok)."""
        # Prior turns only. The system prompt is passed as a proper
        # system_instruction so it stays in effect for every turn.
        history_contents = [
            types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part(text=m["content"])])
            for m in chat_history
        ]

        system_instruction = self.general_system_prompt
        if user_ctx.get("location") or user_ctx.get("latitude") is not None:
            where = user_ctx.get("location") or f"{user_ctx['latitude']:.3f}, {user_ctx['longitude']:.3f}"
            system_instruction += (
                f"\n\nThe user's location: {where}. Consider local climatic conditions when answering, "
                "and use it for weather and yield questions unless they name another place."
            )
        else:
            system_instruction += (
                "\n\nThe user hasn't shared a location. For weather, timing or region-specific questions, "
                "ask for their district and state."
            )
        if language and language != "en":
            lang_name = _LANGUAGE_NAMES.get(language, language)
            system_instruction += (
                f"\n\nRespond in {lang_name} ({language}), regardless of what language the "
                f"conversation history above is in, unless the user explicitly asks for a "
                f"different language."
            )

        # Tool results cached per request, so a retry or fallback model
        # doesn't refetch the same prices/forecast.
        tool_cache: Dict[str, Dict[str, Any]] = {}

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

        async def _generate(model_name: str, allow_tools: bool) -> Tuple[str, List[Dict[str, Any]], bool]:
            """One full answer: model call, any tool calls it asks for, repeat."""
            contents = history_contents + [types.Content(role="user", parts=[types.Part(text=user_message)])]
            tool_log: List[Dict[str, Any]] = []
            for round_no in range(MAX_TOOL_ROUNDS + 1):
                # Last round: force a text answer from what's been gathered
                tools_now = allow_tools and round_no < MAX_TOOL_ROUNDS
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    # Lower than Gemini's ~1.0 default - factual farming
                    # advice should stay close to what the model knows.
                    temperature=0.3,
                    tools=[chat_tools.TOOL_DECLARATIONS] if tools_now else None,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if tools_now else None,
                )
                response = await asyncio.to_thread(
                    self.gemini_client.models.generate_content,
                    model=model_name, contents=contents, config=config,
                )
                candidate = response.candidates[0] if response.candidates else None
                parts = (candidate.content.parts if candidate and candidate.content else None) or []
                calls = [p.function_call for p in parts if p.function_call]
                if not calls:
                    text = "".join(p.text for p in parts if p.text) or (response.text or "")
                    return text.strip() or "(No response)", tool_log, True

                contents.append(candidate.content)
                results = []
                for call in calls:
                    key = f"{call.name}:{json.dumps(dict(call.args or {}), sort_keys=True)}"
                    if key not in tool_cache:
                        tool_cache[key] = await self._run_tool(call, user_ctx)
                    results.append(tool_cache[key])
                    tool_log.append({"name": call.name, "args": dict(call.args or {}), "result": tool_cache[key]})
                    logger.info(f"chat tool {call.name}({dict(call.args or {})})")
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=call.name, response={"result": result})
                    for call, result in zip(calls, results)
                ]))
            return "(No response)", tool_log, True

        async def _send_with_retries(model_name: str, max_retries: int = 1, allow_tools: bool = True):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await _generate(model_name, allow_tools)
                except Exception as e:
                    last_exc = e
                    category = _classify_error(str(e))
                    if category == "other":
                        raise
                    if category == "quota_exhausted":
                        # A daily/monthly cap won't clear up in the next few
                        # seconds - fail fast so the caller can move on to the
                        # fallback model (which may have separate quota).
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
            # Only 2 attempts (1 retry) on the primary - with two more
            # independently-quota'd tiers below to fall through to,
            # hammering the same possibly-overloaded model just adds latency.
            return await _send_with_retries(self.gemini_model_name, max_retries=2)
        except Exception as e1:
            category = _classify_error(str(e1))
            logger.warning(f"chat_assistant primary model failed: {e1} (category={category})")
            if category not in ("quota_exhausted", "rate_limited"):
                logger.error(f"chat_assistant non-retryable error: {e1}")
                return self._fallback_response(user_message, error=str(e1)), [], False

            try:
                return await _send_with_retries(self.fallback_model_name, max_retries=1)
            except Exception as e2:
                category2 = _classify_error(str(e2))
                logger.warning(f"chat_assistant fallback model failed: {e2} (category={category2})")
                if not self.safety_net_model_name or category2 not in ("quota_exhausted", "rate_limited"):
                    logger.error(f"chat_assistant fallback model also failed: {e2}")
                    return self._fallback_response(user_message, error=str(e2)), [], False

                try:
                    # Third tier - a separate, much-higher-daily-quota model.
                    # Tools are skipped here: the safety-net model is
                    # typically an open Gemma model without function calling.
                    return await _send_with_retries(self.safety_net_model_name, max_retries=1, allow_tools=False)
                except Exception as e3:
                    logger.error(f"chat_assistant safety-net model also failed: {e3}")
                    return self._fallback_response(user_message, error=str(e3)), [], False

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
        return context_protocol.get_context(f"chat_history_{session_id}") or []

    async def _update_chat_history(self, session_id: str, user_message: str, ai_response: str):
        """Append one exchange to the session's history (wall-clock timestamps)."""
        chat_history_key = f"chat_history_{session_id}"
        chat_history = context_protocol.get_context(chat_history_key) or []
        now = time.time()
        chat_history.append({"role": "user", "content": user_message, "timestamp": now})
        chat_history.append({"role": "assistant", "content": ai_response, "timestamp": now})
        # Keep the most recent messages to prevent context overflow
        context_protocol.set_context(chat_history_key, chat_history[-MAX_HISTORY_MESSAGES:])


def seed_history_if_missing(session_id: str, client_history: Optional[List[Dict[str, Any]]]) -> None:
    """If the server has no history for this session (e.g. the backend
    restarted or the free-tier host slept), rebuild it from the copy the
    browser sends with every message, so the assistant doesn't silently
    forget the conversation."""
    key = f"chat_history_{session_id}"
    if context_protocol.get_context(key) or not client_history:
        return
    now = time.time()
    cleaned = [
        {"role": m["role"], "content": m["content"][:4000], "timestamp": now}
        for m in client_history
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str) and m["content"].strip()
    ]
    # Gemini expects the conversation to start with a user turn
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    if cleaned:
        context_protocol.set_context(key, cleaned[-MAX_HISTORY_MESSAGES:])


# Function to create and register the chat agent
def init_chat_agent():
    """Initialize and register the chat agent"""
    chat_agent = ChatAgent()
    coordinator.register_agent(chat_agent)
    return chat_agent
