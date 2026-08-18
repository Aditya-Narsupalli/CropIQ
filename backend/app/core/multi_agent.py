"""
Multi-Agent System for FarmGenius
This module implements a multi-agent system architecture that coordinates specialized agents
for crop disease detection, yield prediction, market analysis, and voice interactions.
"""
import asyncio
from typing import Dict, List, Any, Optional, Callable, Union
import logging
from enum import Enum
from dataclasses import dataclass
import json

from app.core.config import get_settings

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AgentType(Enum):
    """Types of specialized agents in the system"""
    COORDINATOR = "coordinator"
    DISEASE_DETECTOR = "disease_detector"
    YIELD_PREDICTOR = "yield_predictor"
    MARKET_ANALYZER = "market_analyzer"
    VOICE_ASSISTANT = "voice_assistant"
    TRANSLATOR = "translator"
    CHAT_ASSISTANT = "chat_assistant"
    MARKET_EXPERT = "market_expert"
    WEATHER_ADVISOR = "weather_advisor"
    CROP_DOCTOR = "crop_doctor"

@dataclass
class Message:
    """Message object for inter-agent communication"""
    sender: AgentType
    receiver: AgentType
    content: Any
    message_type: str
    context: Dict[str, Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary"""
        return {
            "sender": self.sender.value,
            "receiver": self.receiver.value,
            "content": self.content,
            "message_type": self.message_type,
            "context": self.context or {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create message from dictionary"""
        return cls(
            sender=AgentType(data["sender"]),
            receiver=AgentType(data["receiver"]),
            content=data["content"],
            message_type=data["message_type"],
            context=data.get("context", {})
        )

class Agent:
    """Base agent class with common functionality"""
    
    def __init__(self, agent_type: AgentType, coordinator: 'AgentCoordinator' = None):
        self.agent_type = agent_type
        self.coordinator = coordinator
        self.message_handlers: Dict[str, Callable] = {}

    def register_handler(self, message_type: str, handler: Callable):
        """Register a handler for a specific message type"""
        self.message_handlers[message_type] = handler

    async def handle_message(self, message: Message) -> Optional[Message]:
        """Process incoming message and optionally return a response"""
        if message.message_type in self.message_handlers:
            return await self.message_handlers[message.message_type](message)
        else:
            logger.warning(f"Agent {self.agent_type.value} has no handler for message type {message.message_type}")
            return None

    async def send_message(self, receiver: AgentType, content: Any, message_type: str, context: Dict[str, Any] = None) -> Optional[Message]:
        """Send a message to another agent via the coordinator.

        Moved here from CropDoctorAgent (previously the *only* class that had
        it - every other agent inheriting from the base `Agent` class,
        including MarketAnalyzerAgent and VoiceAssistantAgent in agents.py,
        would raise AttributeError the moment they tried to call
        self.send_message(...), silently breaking any inter-agent routing.
        """
        if self.coordinator:
            message = Message(
                sender=self.agent_type,
                receiver=receiver,
                content=content,
                message_type=message_type,
                context=context
            )
            return await self.coordinator.route_message(message)
        else:
            logger.error(f"Agent {self.agent_type.value} has no coordinator to send messages")
            return None

try:
    from google import genai
except Exception:
    genai = None

settings = get_settings()

class MarketExpertAgent(Agent):
    """Specialized agent for market-related queries"""
    def __init__(self, coordinator=None):
        super().__init__(AgentType.MARKET_EXPERT, coordinator)
        self.register_handler("chat", self.handle_chat)
        self.gemini_client = None
        self.gemini_model_name = 'models/gemini-flash-lite-latest'
        if genai and settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_NOT_SET":
            try:
                self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.error(f"Error initializing Gemini client for MarketExpertAgent: {e}")

    async def handle_chat(self, message):
        user_message = message.content.get("message", "")
        system_prompt = (
            "You are MarketExpert, an AI specialized in Indian agricultural markets. "
            "Provide accurate, up-to-date advice on prices, trends, and market strategies. "
            "Use real data if available. If the user asks about a specific crop or location, be specific."
        )
        prompt = f"{system_prompt}\nUser: {user_message}"
        try:
            if not self.gemini_client:
                raise RuntimeError("Gemini client not configured")
            chat = self.gemini_client.chats.create(
                model=self.gemini_model_name,
                history=[{"role": "model", "parts": [{"text": system_prompt}]}]
            )
            response = await asyncio.to_thread(chat.send_message, user_message)
            response_text = getattr(response, "text", None) or (
                response.candidates[0].content if response.candidates else str(response)
            )
        except Exception as e:
            logger.error(f"{self.agent_type.value} Gemini error: {e}")
            response_text = f"Sorry, MarketExpert AI is temporarily unavailable. Error: {e}"
        return Message(
            sender=self.agent_type,
            receiver=message.sender,
            content=response_text,
            message_type="chat_response"
        )



class WeatherAdvisorAgent(Agent):
    """Specialized agent for weather-related queries"""
    def __init__(self, coordinator=None):
        super().__init__(AgentType.WEATHER_ADVISOR, coordinator)
        self.register_handler("chat", self.handle_chat)
        self.gemini_client = None
        self.gemini_model_name = 'models/gemini-flash-latest'
        if genai and settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_NOT_SET":
            try:
                self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.error(f"Error initializing Gemini client for WeatherAdvisorAgent: {e}")

    async def handle_chat(self, message):
        user_message = message.content.get("message", "")
        system_prompt = (
            "You are WeatherAdvisor, an AI expert in Indian agricultural weather. "
            "Provide accurate weather forecasts, climate advice, and explain how weather impacts farming. "
            "Reference real data if available."
        )
        prompt = f"{system_prompt}\nUser: {user_message}"
        try:
            if not self.gemini_client:
                raise RuntimeError("Gemini client not configured")
            chat = self.gemini_client.chats.create(
                model=self.gemini_model_name,
                history=[{"role": "model", "parts": [{"text": system_prompt}]}]
            )
            response = await asyncio.to_thread(chat.send_message, user_message)
            response_text = getattr(response, "text", None) or (
                response.candidates[0].content if response.candidates else str(response)
            )
        except Exception as e:
            logger.error(f"{self.agent_type.value} Gemini error: {e}")
            response_text = f"Sorry, WeatherAdvisor AI is temporarily unavailable. Error: {e}"
        return Message(
            sender=self.agent_type,
            receiver=message.sender,
            content=response_text,
            message_type="chat_response"
        )



class CropDoctorAgent(Agent):
    """Specialized agent for crop and disease-related queries"""
    def __init__(self, coordinator=None):
        super().__init__(AgentType.CROP_DOCTOR, coordinator)
        self.register_handler("chat", self.handle_chat)
        self.gemini_client = None
        self.gemini_model_name = 'models/gemini-2.5-pro'
        if genai and settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "YOUR_GEMINI_API_KEY_NOT_SET":
            try:
                self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.error(f"Error initializing Gemini client for CropDoctorAgent: {e}")

    async def handle_chat(self, message):
        user_message = message.content.get("message", "")
        system_prompt = (
            "You are CropDoctor, an AI expert in Indian crop health, soil, and disease management. "
            "Give actionable, specific advice for crop issues, pest management, and soil health. "
            "Reference real data and best practices for Indian agriculture."
        )
        prompt = f"{system_prompt}\nUser: {user_message}"
        async def _send_with_retries(model_name: str, max_retries: int = 3):
            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    chat = self.gemini_client.chats.create(
                        model=model_name,
                        history=[{"role": "model", "parts": [{"text": system_prompt}]}]
                    )
                    response = await asyncio.to_thread(chat.send_message, user_message)
                    return getattr(response, "text", None) or (
                        response.candidates[0].content if response.candidates else str(response)
                    )
                except Exception as e:
                    last_exc = e
                    err_str = str(e).lower()
                    transient = any(x in err_str for x in ['429', 'too many requests', 'resource_exhausted', 'rate limit', '503', 'unavailable', 'high demand', 'temporarily unavailable'])
                    if not transient:
                        # Non-transient error: re-raise immediately
                        raise
                    if attempt < max_retries:
                        backoff = 0.5 * (2 ** (attempt - 1))
                        logger.warning(f"{self.agent_type.value} {model_name} attempt {attempt} failed: {e}; retrying in {backoff}s")
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(f"{self.agent_type.value} {model_name} all {max_retries} attempts failed: {e}")
            raise last_exc

        try:
            if not self.gemini_client:
                raise RuntimeError("Gemini client not configured")

            # Try primary flash model with retries
            try:
                response_text = await _send_with_retries('models/gemini-flash-lite-latest')
            except Exception as e1:
                err_str = str(e1).lower()
                is_transient = any(x in err_str for x in ['429', 'too many requests', 'resource_exhausted', 'rate limit', '503', 'unavailable', 'high demand'])
                logger.warning(f"{self.agent_type.value} primary model failed after retries: {e1} (transient={is_transient})")
                if is_transient:
                    # Try fallback flash variant (2.5-flash) with retries
                    try:
                        response_text = await _send_with_retries('models/gemini-flash-latest')
                    except Exception as e2:
                        logger.error(f"{self.agent_type.value} fallback model also failed: {e2}")
                        response_text = "CropDoctor AI is experiencing high demand. Please try again in a minute."
                else:
                    logger.error(f"{self.agent_type.value} non-transient error: {e1}")
                    response_text = f"Sorry, CropDoctor AI is temporarily unavailable. Error: {e1}"
        except Exception as e:
            logger.error(f"{self.agent_type.value} unexpected error: {e}")
            response_text = f"Sorry, CropDoctor AI is temporarily unavailable. Error: {e}"
        return Message(
            sender=self.agent_type,
            receiver=message.sender,
            content=response_text,
            message_type="chat_response"
        )

class AgentCoordinator:
    """Central coordinator for managing agent communication"""
    
    def __init__(self):
        self.agents: Dict[AgentType, Agent] = {}
        self.message_queue = asyncio.Queue()
        self.running = False
        
    def register_agent(self, agent: Agent):
        """Register an agent with the coordinator"""
        agent.coordinator = self
        self.agents[agent.agent_type] = agent
        logger.info(f"Registered agent: {agent.agent_type.value}")
        
    async def route_message(self, message: Message) -> Optional[Message]:
        """Route a message to the appropriate agent"""
        if message.receiver not in self.agents:
            logger.error(f"No agent registered for type: {message.receiver.value}")
            return None
            
        try:
            logger.debug(f"Routing message: {message.sender.value} -> {message.receiver.value} ({message.message_type})")
            return await self.agents[message.receiver].handle_message(message)
        except Exception as e:
            logger.error(f"Error routing message: {e}")
            return None
            
    async def broadcast_message(self, sender: AgentType, content: Any, message_type: str, context: Dict[str, Any] = None) -> List[Message]:
        """Send a message to all agents except the sender"""
        responses = []
        for agent_type, agent in self.agents.items():
            if agent_type != sender:
                message = Message(
                    sender=sender,
                    receiver=agent_type,
                    content=content,
                    message_type=message_type,
                    context=context
                )
                response = await agent.handle_message(message)
                if response:
                    responses.append(response)
        return responses
        
    async def start(self):
        """Start processing messages from the queue"""
        self.running = True
        logger.info("Agent coordinator started")
        
    async def stop(self):
        """Stop the coordinator"""
        self.running = False
        logger.info("Agent coordinator stopped")

class ModelContextProtocol:
    """
    Protocol for maintaining context between agent interactions.
    This allows agents to share a common understanding of the conversation state.
    """
    
    def __init__(self):
        self.contexts: Dict[str, Any] = {}
        
    def set_context(self, context_id: str, data: Any):
        """Set context data for a specific ID"""
        self.contexts[context_id] = data
        
    def get_context(self, context_id: str) -> Optional[Any]:
        """Get context data for a specific ID"""
        return self.contexts.get(context_id)
        
    def update_context(self, context_id: str, data: Dict[str, Any]):
        """Update existing context with new data"""
        if context_id in self.contexts:
            if isinstance(self.contexts[context_id], dict):
                self.contexts[context_id].update(data)
            else:
                logger.warning(f"Cannot update non-dict context: {context_id}")
        else:
            self.set_context(context_id, data)
            
    def clear_context(self, context_id: str):
        """Clear context for a specific ID"""
        if context_id in self.contexts:
            del self.contexts[context_id]

# Create global instances for use across the application
coordinator = AgentCoordinator()
context_protocol = ModelContextProtocol()

# Register specialized expert agents
coordinator.register_agent(MarketExpertAgent(coordinator))
coordinator.register_agent(WeatherAdvisorAgent(coordinator))
coordinator.register_agent(CropDoctorAgent(coordinator))

# Example usage
"""
# Create and register agents
disease_agent = DiseaseDetectorAgent()
coordinator.register_agent(disease_agent)

# Set up context for a user session
session_id = "user123"
context_protocol.set_context(session_id, {
    "language": "mr",  # Marathi
    "location": "Baramati"
})

# Send a message from one agent to another
response = await disease_agent.send_message(
    receiver=AgentType.MARKET_ANALYZER,
    content="What's the current price of wheat?",
    message_type="query",
    context={"session_id": session_id}
)
"""
