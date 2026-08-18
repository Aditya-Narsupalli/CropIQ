"""
Specialized agents for the FarmGenius multi-agent system.
Each agent is responsible for a specific domain of expertise.
"""
import asyncio
from typing import Dict, List, Any, Optional, Callable, Union
import logging
import json
import io
from PIL import Image
from datetime import datetime, timedelta
import random

from app.core.multi_agent import Agent, AgentType, Message, coordinator, context_protocol
from app.core.ai_services import (
    get_disease_prediction, 
    process_voice_command_ai, 
    get_market_summary_ai,
    generate_text,
)
from app.models.yield_model import YieldInput
from app.services.yield_prediction_service import predict_yield
from app.services.market_scraper import get_all_prices, get_scraper, record_todays_snapshot_if_needed, get_local_price_history
from app.core.config import get_settings

# Initialize settings
settings = get_settings()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DiseaseDetectorAgent(Agent):
    """Agent specializing in crop disease detection from images"""
    
    def __init__(self):
        super().__init__(AgentType.DISEASE_DETECTOR)
        self.register_handler("analyze_image", self.handle_analyze_image)
        self.register_handler("get_treatment", self.handle_get_treatment)
        
    async def handle_analyze_image(self, message: Message) -> Optional[Message]:
        """Analyze image to detect crop diseases"""
        try:
            # Extract image data from message
            image_bytes = message.content.get("image_bytes")
            if not image_bytes:
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": "No image data provided"},
                    message_type="error"
                )
                
            # Call AI service for disease detection
            result = await get_disease_prediction(image_bytes)
            
            # If needed, we could also request market info for treatment options
            if not result.startswith("Error:"):
                # Get context for additional processing if needed
                context_id = message.context.get("session_id") if message.context else None
                if context_id:
                    # Save disease detection result to context
                    context_protocol.update_context(context_id, {
                        "last_disease_detection": result
                    })
                    
                    # We could enhance this by asking the market agent for product prices
                    # if treatments are mentioned
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"result": result},
                message_type="analysis_result",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error in disease detection: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error analyzing image: {str(e)}"},
                message_type="error"
            )
            
    async def handle_get_treatment(self, message: Message) -> Optional[Message]:
        """Get treatment recommendations for detected disease"""
        disease_name = message.content.get("disease_name")
        crop_type = message.content.get("crop_type", "unknown crop")
        
        # Use context if available
        context_id = message.context.get("session_id") if message.context else None
        language = "en"
        
        if context_id:
            context = context_protocol.get_context(context_id)
            if context:
                language = context.get("language", "en")
        
        # Generate treatment recommendation using Gemini
        try:
            prompt = f"""Provide organic and conventional treatment options for {disease_name} in {crop_type}. 
            Include locally available options common in Maharashtra, India. Keep it brief and practical."""
            
            treatment = await generate_text(prompt)
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"treatment": treatment},
                message_type="treatment_recommendation",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error getting treatment recommendation: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error getting treatment recommendation: {str(e)}"},
                message_type="error"
            )

class YieldPredictorAgent(Agent):
    """Agent specializing in crop yield predictions.

    Wired to the same trained ML model used by the /predict REST endpoint
    (app/services/yield_prediction_service.py::predict_yield), so the chat
    assistant and the yield prediction form give consistent answers instead
    of two independently-drifting implementations. There used to be a
    second, Gemini-based estimate here (ai_services.py::get_yield_estimate) -
    it's been removed: it was never actually reachable (see the routing note
    in VoiceAssistantAgent below) and referenced fields that don't exist on
    YieldInput (yield_input.area_size).
    """

    def __init__(self):
        super().__init__(AgentType.YIELD_PREDICTOR)
        self.register_handler("predict_yield", self.handle_predict_yield)
        
    async def handle_predict_yield(self, message: Message) -> Optional[Message]:
        """Generate yield prediction from farmer input"""
        try:
            # content["yield_input"] can be a YieldInput instance or a plain
            # dict (e.g. built from partial info extracted in chat) - accept
            # either, filling in required-but-unknown fields with neutral
            # defaults rather than failing the whole request.
            raw_input = message.content.get("yield_input")
            if not raw_input:
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": "No yield input data provided"},
                    message_type="error"
                )

            if isinstance(raw_input, YieldInput):
                yield_input = raw_input
            else:
                defaults = dict(
                    area=1.0, season="Kharif", state="Maharashtra", annual_rainfall=800.0,
                    fertilizer=100.0, pesticide=3.0, ph=6.5, n=120.0, p=50.0, k=100.0,
                    organic_carbon=0.5,
                )
                defaults.update(raw_input)
                yield_input = YieldInput(**defaults)

            yield_per_hectare, total_production, recommendations, model_source, model_r2 = predict_yield(yield_input)
            result = (
                f"Estimated yield for {yield_input.crop} in {yield_input.state} ({yield_input.season}): "
                f"{yield_per_hectare:.2f} tonnes/hectare, ~{total_production:.2f} tonnes total "
                f"over {yield_input.area} hectares. "
                f"{'(Backed by our trained yield model.)' if model_source == 'ml' else '(Estimated using a simplified model - limited historical data for this crop.)'}"
            )

            # Store the result in context if session_id is provided
            context_id = message.context.get("session_id") if message.context else None
            if context_id:
                context_protocol.update_context(context_id, {
                    "last_yield_prediction": {
                        "crop": yield_input.crop,
                        "area": yield_input.area,
                        "prediction": result,
                        "model_source": model_source,
                    }
                })
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={
                    "result": result,
                    "yield_per_hectare": yield_per_hectare,
                    "estimated_production": total_production,
                    "recommendations": recommendations,
                    "model_source": model_source,
                },
                message_type="prediction_result",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error in yield prediction: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error making yield prediction: {str(e)}"},
                message_type="error"
            )

class MarketAnalyzerAgent(Agent):
    """Agent specializing in market data analysis and price tracking"""
    
    def __init__(self):
        super().__init__(AgentType.MARKET_ANALYZER)
        self.register_handler("get_prices", self.handle_get_prices)
        self.register_handler("analyze_trends", self.handle_analyze_trends)
        self.register_handler("get_summary", self.handle_get_summary)
        self.last_update = None
        self.cached_prices = []
        
    async def handle_get_prices(self, message: Message) -> Optional[Message]:
        """Get current market prices for crops"""
        try:
            # Check if specific crop is requested
            crop = message.content.get("crop")
            location = message.content.get("location", "Baramati")
            force_refresh = message.content.get("force_refresh", False)
            
            # Get live prices using the scraper (real Agmarknet data).
            # Note: Agmarknet's dashboard-data API returns a national
            # summary per commodity, not per-district, so `location` is
            # currently informational only and doesn't narrow the result.
            if crop:
                # Get specific crop prices
                scraper = get_scraper("agmarknet")
                prices = await scraper.get_prices(crop, district=location)
            else:
                # Get all prices (potentially from cache)
                if not self.cached_prices or force_refresh:
                    self.cached_prices = await get_all_prices()
                    self.last_update = asyncio.get_event_loop().time()
                    
                prices = self.cached_prices
            
            # Store the result in context if session_id is provided
            context_id = message.context.get("session_id") if message.context else None
            if context_id:
                context_protocol.update_context(context_id, {
                    "last_market_query": {
                        "crop": crop,
                        "location": location,
                        "prices": prices
                    }
                })
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"prices": prices},
                message_type="price_data",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error getting market prices: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error getting market prices: {str(e)}"},
                message_type="error"
            )
    
    async def handle_analyze_trends(self, message: Message) -> Optional[Message]:
        """Analyze market trends for a specific crop using real Agmarknet data.

        Earlier versions tried: (1) fake random prices, then (2) a 30-day
        loop that assumed varying the `date` request field would return that
        day's historical snapshot. Both produced misleading charts - Agmarknet's
        dashboard-data endpoint doesn't support arbitrary historical lookups;
        the raw record only ever has today's price and yesterday's price.

        There is no live endpoint that can hand us a real 30-day series on
        demand - so we build one ourselves over time: every trend request
        records today's real prices to a local log
        (market_scraper.py::record_todays_snapshot_if_needed), and this reads
        back whatever real days have accumulated so far
        (get_local_price_history). Immediately after deploy that's just 1-2
        real points; it genuinely grows to a real 30-day window after 30 days
        of the app being used. On day one, we bootstrap with the one extra
        real historical point Agmarknet's snapshot itself provides
        (yesterday's price) so the chart isn't a single dot from the start.
        """
        try:
            crop = message.content.get("crop", "unknown crop")
            logger.info(f"Analyzing real trend data for: {crop}")

            await record_todays_snapshot_if_needed()
            historical_prices = await get_local_price_history(crop, days=180)

            # Bootstrap: if our local log doesn't yet reach back to
            # "yesterday" (e.g. this is the first day the log has run),
            # splice in the one extra real historical point Agmarknet's own
            # snapshot gives us for free, so day one still shows a real
            # 2-point trend instead of a single dot.
            matches = await get_scraper().get_prices(crop)
            record = matches[0] if matches else None
            if record and record.get("price_1d_ago") is not None:
                today_date = record["date"]
                yesterday_date = (datetime.strptime(today_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                have_dates = {h["date"] for h in historical_prices}
                if yesterday_date not in have_dates:
                    historical_prices = sorted(
                        historical_prices + [{"date": yesterday_date, "price": record["price_1d_ago"]}],
                        key=lambda h: h["date"]
                    )

            if len(historical_prices) >= 2:
                start_price = historical_prices[0]["price"]
                end_price = historical_prices[-1]["price"]
                trend_percentage = ((end_price - start_price) / start_price) * 100
                span_days = len(historical_prices)
                span = f"{historical_prices[0]['date']} to {historical_prices[-1]['date']}"

                coverage_note = (
                    "" if span_days >= 25 else
                    f" (We started tracking real daily prices recently, so this covers {span_days} "
                    "real recorded days so far rather than a full 30 - it'll keep growing.)"
                )

                if trend_percentage > 5:
                    trend_summary = f"Prices for {crop} have risen by approximately {trend_percentage:.1f}% ({span}).{coverage_note}"
                elif trend_percentage < -5:
                    trend_summary = f"Prices for {crop} have fallen by approximately {abs(trend_percentage):.1f}% ({span}).{coverage_note}"
                else:
                    trend_summary = f"Prices for {crop} have stayed relatively stable (change of {trend_percentage:.1f}%, {span}).{coverage_note}"
            elif len(historical_prices) == 1:
                trend_summary = (
                    f"Today's price for {crop} is ₹{historical_prices[0]['price']:.0f} per quintal. "
                    "We've just started tracking daily prices for this feature - check back tomorrow for a real trend."
                )
            else:
                trend_summary = (
                    f"We couldn't find real market data for '{crop}' on Agmarknet right now. "
                    "Try a different crop name, or check back later."
                )

            # Store result in context if needed
            context_id = message.context.get("session_id") if message.context else None
            if context_id:
                context_protocol.update_context(context_id, {
                    f"trend_analysis_{crop}": {
                        "summary": trend_summary,
                        "historical_data": historical_prices
                    }
                })

            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={
                    "message": trend_summary, 
                    "historical_data": historical_prices
                },
                message_type="trend_analysis_result",
                context=message.context
            )

        except Exception as e:
            logger.error(f"Error analyzing trends for {crop}: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error analyzing trends for {crop}: {str(e)}"},
                message_type="error"
            )
    
    async def handle_get_summary(self, message: Message) -> Optional[Message]:
        """Get a summary of current market conditions"""
        try:
            # Ensure we have fresh prices
            if not self.cached_prices:
                self.cached_prices = await get_all_prices()
                self.last_update = asyncio.get_event_loop().time()
                
            # Get AI-generated summary
            summary = await get_market_summary_ai(self.cached_prices)
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"summary": summary},
                message_type="market_summary",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error getting market summary: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error getting market summary: {str(e)}"},
                message_type="error"
            )

class VoiceAssistantAgent(Agent):
    """Agent specializing in voice interaction and language processing"""
    
    def __init__(self):
        super().__init__(AgentType.VOICE_ASSISTANT)
        self.register_handler("process_command", self.handle_process_command)
        self.register_handler("text_to_speech", self.handle_text_to_speech)
        
        # Supported languages
        self.languages = {
            "en": "English",
            "hi": "Hindi",
            "mr": "Marathi"
        }
        
    async def handle_process_command(self, message: Message) -> Optional[Message]:
        """Process voice command transcripts"""
        try:
            transcript = message.content.get("transcript")
            if not transcript:
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": "No transcript provided"},
                    message_type="error"
                )
                
            # Get language preference from context if available
            context_id = message.context.get("session_id") if message.context else None
            language = "en"  # Default to English
            
            if context_id:
                context = context_protocol.get_context(context_id)
                if context:
                    language = context.get("language", "en")
            
            # Call AI service to process the voice command
            result = await process_voice_command_ai(transcript, language)
            
            # Analyze the command to determine if we need to route to other agents
            # For a sophisticated implementation, we could use an intent classifier here
            
            # Simple keyword-based routing for demo purposes
            should_route = False
            target_agent = None
            
            if any(word in transcript.lower() for word in ["disease", "infection", "spots", "leaf", "analyze"]):
                # This is likely a disease-related question
                should_route = True
                target_agent = AgentType.DISEASE_DETECTOR
                # We'd need image data for a real analysis though
                
            elif any(word in transcript.lower() for word in ["yield", "harvest", "production", "how much"]):
                # This is likely a yield prediction question
                should_route = True
                target_agent = AgentType.YIELD_PREDICTOR

                # Simplified keyword extraction, same spirit as the market
                # branch below - a voice transcript doesn't give us structured
                # area/season/state, so we pass what we can detect (crop) and
                # let YieldPredictorAgent fill sensible defaults for the rest.
                common_crops = ["wheat", "rice", "cotton", "sugarcane", "soybean", "maize", "onion", "potato"]
                crop = next((c for c in common_crops if c in transcript.lower()), None)

                if crop:
                    yield_response = await self.send_message(
                        receiver=AgentType.YIELD_PREDICTOR,
                        content={"yield_input": {"crop": crop.capitalize()}},
                        message_type="predict_yield",
                        context=message.context
                    )
                    if yield_response and "result" in yield_response.content:
                        result = yield_response.content["result"]
                else:
                    result = (
                        f"{result} To estimate yield I'll also need to know the crop - "
                        "could you say which crop you mean?"
                    )
                
            elif any(word in transcript.lower() for word in ["price", "market", "sell", "cost", "mandi"]):
                # This is likely a market-related question
                should_route = True
                target_agent = AgentType.MARKET_ANALYZER
                
                # Extract crop name if present
                # This is simplified - would need better NLP in production
                common_crops = ["wheat", "onion", "soybean", "sugarcane", "rice", "cotton"]
                crop = next((crop for crop in common_crops if crop in transcript.lower()), None)
                
                if crop and target_agent == AgentType.MARKET_ANALYZER:
                    # Route to market agent asking for specific crop price
                    market_response = await self.send_message(
                        receiver=AgentType.MARKET_ANALYZER,
                        content={"crop": crop},
                        message_type="get_prices",
                        context=message.context
                    )
                    
                    if market_response:
                        # Format the market response nicely for voice
                        prices = market_response.content.get("prices", [])
                        if prices:
                            price_texts = []
                            for price in prices:
                                if "price_per_quintal" in price:
                                    price_texts.append(f"{price['crop']} is {price['price_per_quintal']} rupees per quintal")
                                elif "price_per_tonne" in price:
                                    price_texts.append(f"{price['crop']} is {price['price_per_tonne']} rupees per tonne")
                            
                            if price_texts:
                                result = f"Here are the current prices: {', '.join(price_texts)}"
            
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={
                    "response": result,
                    "should_route": should_route,
                    "target_agent": target_agent.value if target_agent else None
                },
                message_type="voice_response",
                context=message.context
            )
                
        except Exception as e:
            logger.error(f"Error processing voice command: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error processing voice command: {str(e)}"},
                message_type="error"
            )
    
    async def handle_text_to_speech(self, message: Message) -> Optional[Message]:
        """Generate text-to-speech audio (mock implementation)"""
        text = message.content.get("text")
        if not text:
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": "No text provided for speech synthesis"},
                message_type="error"
            )
            
        # Get language preference from context if available
        context_id = message.context.get("session_id") if message.context else None
        language = "en"  # Default to English
        
        if context_id:
            context = context_protocol.get_context(context_id)
            if context:
                language = context.get("language", "en")
        
        # In a real implementation, this would call a TTS service
        # For the hackathon, we'll return a mock response
        return Message(
            sender=self.agent_type,
            receiver=message.sender,
            content={
                "message": f"Text-to-speech synthesis would happen here in {self.languages.get(language, 'English')}"
            },
            message_type="tts_response",
            context=message.context
        )

class TranslatorAgent(Agent):
    """Agent specializing in language translation for multilingual support"""
    
    def __init__(self):
        super().__init__(AgentType.TRANSLATOR)
        self.register_handler("translate", self.handle_translate)
        
        # Supported languages
        self.languages = {
            "en": "English",
            "hi": "Hindi",
            "mr": "Marathi"
        }
        
    async def handle_translate(self, message: Message) -> Optional[Message]:
        """Translate text between languages"""
        try:
            text = message.content.get("text")
            target_language = message.content.get("target_language", "en")
            source_language = message.content.get("source_language")
            
            if not text:
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": "No text provided for translation"},
                    message_type="error"
                )
            
            # Validate language codes
            if target_language not in self.languages:
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": f"Unsupported target language: {target_language}"},
                    message_type="error"
                )
            
            # Use Gemini for translation
            try:
                source_lang_name = self.languages.get(source_language, "the source language")
                target_lang_name = self.languages.get(target_language, "English")
                
                prompt = f"""Translate the following text from {source_lang_name} to {target_lang_name}.
                Only return the translated text, nothing else.
                
                Text to translate: {text}"""
                
                translated_text = await generate_text(prompt)
                
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"translated_text": translated_text},
                    message_type="translation_result",
                    context=message.context
                )
                    
            except Exception as e:
                logger.error(f"Error in translation: {e}")
                return Message(
                    sender=self.agent_type,
                    receiver=message.sender,
                    content={"error": f"Error in translation: {str(e)}"},
                    message_type="error"
                )
                
        except Exception as e:
            logger.error(f"Error in translation: {e}")
            return Message(
                sender=self.agent_type,
                receiver=message.sender,
                content={"error": f"Error in translation: {str(e)}"},
                message_type="error"
            )

# Initialize all agents
def init_agents():
    """Initialize and register all specialized agents"""
    disease_agent = DiseaseDetectorAgent()
    coordinator.register_agent(disease_agent)
    
    yield_agent = YieldPredictorAgent()
    coordinator.register_agent(yield_agent)
    
    market_agent = MarketAnalyzerAgent()
    coordinator.register_agent(market_agent)
    
    voice_agent = VoiceAssistantAgent()
    coordinator.register_agent(voice_agent)
    
    translator_agent = TranslatorAgent()
    coordinator.register_agent(translator_agent)
    
    return coordinator
