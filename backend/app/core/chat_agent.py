"""
General-purpose AI Chat Agent for FarmGenius
This module provides a sophisticated chat agent that can engage in general conversations
while having specialized knowledge about agriculture.
"""
import logging
from typing import Dict, List, Any, Optional
import json
import asyncio

from app.core.config import get_settings
from app.core.multi_agent import Agent, AgentType, Message, coordinator, context_protocol

try:
    from google import genai
except Exception:  # pragma: no cover - library may be missing in some environments
    genai = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load settings
settings = get_settings()

class ChatAgent(Agent):
    """
    General-purpose AI chat agent that can have extended conversations
    with users about any topic, with specialized knowledge about agriculture.
    """
    
    def __init__(self):
        super().__init__(AgentType.CHAT_ASSISTANT)
        self.register_handler("chat", self.handle_chat)
        self.register_handler("stream_chat", self.handle_stream_chat)
        
        # Initialize AI models
        self._init_ai_models()
        
        # System prompts
        self.general_system_prompt = """You are FarmGenius, an advanced AI assistant specialized in helping farmers across India.
    You have extensive knowledge about:
    - Crop cultivation techniques for all regions of India
    - Pest and disease management for various climatic zones
    - Weather patterns and climate adaptation across different Indian states
    - Agricultural market trends throughout India's major agricultural markets
    - Sustainable farming practices suited to diverse Indian conditions
    - Knowledge of agriculture across different states of India including crop varieties, local practices and market information

    While you specialize in agricultural topics, you can also have general conversations
    and answer questions on other topics. Always be helpful, accurate, and respectful.
    Provide practical, actionable advice when possible.

    When you don't know something, admit it clearly rather than making up information.
    """
        # Preference: do not ask users to upload photos in chat; request text descriptions of symptoms instead
        self.general_system_prompt += "\nPlease do not ask users to upload photos in chat. Instead, request clear text descriptions of symptoms, crop type, and location."
        
    def _init_ai_models(self):
        """Initialize the AI models for chat"""
        self.gemini_client = None
        self.gemini_model_name = 'models/gemini-flash-lite-latest'
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

            # If a session-level location is stored (e.g., auto-enabled), include it in the prompt
            try:
                session_ctx = context_protocol.get_context(session_id) or {}
                location = None
                if isinstance(session_ctx, dict):
                    # common keys: 'location' or 'auto_location'
                    location = session_ctx.get('location') or session_ctx.get('auto_location')
                # Also check incoming message context for explicit location
                if not location and message.context:
                    location = message.context.get('location')
                if location:
                    # Prepend a short location context so the assistant uses local climatic info
                    user_message = f"Location: {location}. Consider local climatic conditions when answering.\nUser: {user_message}"
            except Exception:
                # don't fail chat if context lookup errors
                pass
            
            # Use Gemini when available; otherwise provide a helpful fallback response.
            if self.gemini_client:
                response = await self._chat_with_gemini(user_message, chat_history)
            else:
                response = self._fallback_response(user_message)
            
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
    
    async def _chat_with_gemini(self, user_message: str, chat_history: List[Dict[str, Any]]) -> str:
        """Generate a response using Gemini model"""
        try:
            # Convert chat history to Gemini format
            gemini_chat = []
            for message in chat_history:
                role = "user" if message["role"] == "user" else "model"
                gemini_chat.append({"role": role, "parts": [{"text": message["content"]}]})

            # Add the system prompt as a model message if there's no history
            if not gemini_chat:
                gemini_chat.append({"role": "model", "parts": [{"text": self.general_system_prompt}]})

            # Create a chat object and send a new message
            chat = self.gemini_client.chats.create(model=self.gemini_model_name, history=gemini_chat)
            response = await asyncio.to_thread(chat.send_message, user_message)
            return getattr(response, "text", None) or (
                response.candidates[0].content if response.candidates else str(response)
            )

        except Exception as e:
            logger.error(f"Error generating Gemini response: {e}")
            return self._fallback_response(user_message, error=str(e))

    def _fallback_response(self, user_message: str, error: Optional[str] = None) -> str:
        """Return a helpful, non-technical fallback response when AI is unavailable."""
        message = user_message.lower()
        if any(word in message for word in ["pest", "disease", "leaf", "fungus", "insect"]):
            response = (
                "For crop health issues, start by inspecting the affected leaves and stems closely. "
                "Remove severely damaged parts, avoid overwatering, and use an appropriate local fungicide or insecticide "
                "only if recommended for that crop. If the damage is spreading quickly, contact a local agriculture officer or extension service."
            )
        elif any(word in message for word in ["soil", "fertilizer", "nutrient", "manure"]):
            response = (
                "For soil and fertility questions, check the crop stage, recent weather, and whether the field has been overwatered or underfed. "
                "A soil test is the best next step for choosing the right fertilizer or amendment."
            )
        elif any(word in message for word in ["market", "price", "sell", "price"]):
            response = (
                "For market and pricing questions, compare current local mandi rates, transport costs, and storage conditions before selling. "
                "Timing and buyer quality requirements can affect the net return significantly."
            )
        else:
            response = (
                "I’m currently running in fallback mode because the AI service key is not configured. "
                "For general farming questions, share the crop, the issue you are facing, and the region, and I can still provide practical guidance."
            )

        if error:
            response += f"\n\nNote: AI service unavailable: {error}"
        return response
    
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
        # Keep the most recent 20 messages (10 exchanges)
        if len(chat_history) > 20:
            chat_history = chat_history[-20:]
        
        # Update context
        context_protocol.set_context(chat_history_key, chat_history)

# Function to create and register the chat agent
def init_chat_agent():
    """Initialize and register the chat agent"""
    chat_agent = ChatAgent()
    coordinator.register_agent(chat_agent)
    return chat_agent
