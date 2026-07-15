from google import genai
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import uuid
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Configure Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai_client = None
gemini_model_name = 'models/gemini-flash-lite-latest'
if GEMINI_API_KEY:
    try:
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Failed to initialize Gemini: {str(e)}")

# In-memory conversation history per session (can be replaced with Redis, DB, etc.)
conversation_histories = {}

class ChatInput(BaseModel):
    message: str = Field(..., min_length=1, description="User's message to the chat assistant")
    session_id: Optional[str] = Field(None, description="Session ID for continuing conversations")
    language: Optional[str] = Field("en", description="Language code (en, hi, mr, etc.)")

class ChatResponse(BaseModel):
    response: str
    session_id: str
    model_used: str = "models/gemini-flash-latest"
    history: list

@router.post("/message", response_model=ChatResponse, status_code=200)
async def chat_message(chat_input: ChatInput = Body(...)):
    """
    Multilingual Gemini chat endpoint using google-generativeai SDK.
    Stores and uses conversation history per session.
    """
    if not genai_client:
        raise HTTPException(status_code=500, detail="Gemini client not initialized")
    try:
        session_id = chat_input.session_id or str(uuid.uuid4())
        history = conversation_histories.get(session_id, [])
        # Add system prompt if first message
        if not history:
            history.append({
                'role': 'model',
                'parts': [{
                    'text': (
                        f"You are FarmGenius, a professional multilingual AI assistant for Indian agriculture. "
                        f"You ONLY answer questions related to farming, crops, weather, agri-markets, government schemes, or rural livelihoods. "
                        f"If a question is not about agriculture, politely refuse and ask the user to ask a farming-related question.\n"
                        f"Always answer in the user's selected language: {chat_input.language}. "
                        f"Never answer in English unless the user selected English.\n"
                        f"Be friendly, clear, and provide detailed, actionable advice for Indian farmers."
                    )
                }]
            })
        # Add user message
        history.append({'role': 'user', 'parts': [{'text': chat_input.message}]})
        # Start chat and get response with fallback for quota/rate-limit errors
        tried_models = [gemini_model_name, 'models/gemini-flash-latest', 'models/gemini-2.5-flash', 'models/gemini-2.0-flash']
        ai_response = None
        last_error = None
        for model_name in tried_models:
            try:
                chat_session = genai_client.chats.create(model=model_name, history=history)
                response = await asyncio.to_thread(chat_session.send_message, chat_input.message)
                ai_response = getattr(response, 'text', None) or (response.candidates[0].content if response.candidates else str(response))
                gemini_model_used = model_name
                break
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if any(x in err_str for x in ['429', 'resource_exhausted', 'rate limit', 'unavailable', '503']):
                    # Try next fallback model
                    continue
                else:
                    # Non-retryable error, break and surface
                    break
        if ai_response is None:
            # If we exhausted fallbacks, return a friendly message as a normal response
            ai_response = "CropDoctor AI is experiencing high demand. Please try again in a minute."
            gemini_model_used = "none"
        # Add AI response to history
        history.append({'role': 'model', 'parts': [{'text': ai_response}]})
        conversation_histories[session_id] = history
        return ChatResponse(
            response=ai_response,
            session_id=session_id,
            model_used=gemini_model_used if ai_response else gemini_model_name,
            history=history
        )
    except HTTPException:
        # Propagate intended HTTPExceptions (like our 503 fallback message)
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {str(e)}")
