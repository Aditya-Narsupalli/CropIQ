import asyncio

from app.core.chat_agent import ChatAgent
from app.core.multi_agent import AgentType, Message


def test_chat_agent_returns_fallback_response_when_gemini_is_unavailable():
    agent = ChatAgent()
    message = Message(
        sender=AgentType.COORDINATOR,
        receiver=AgentType.CHAT_ASSISTANT,
        content={"message": "How do I treat pests on my tomato crop?"},
        message_type="chat",
        context={"session_id": "test-session"},
    )

    response = asyncio.run(agent.handle_chat(message))

    assert response is not None
    assert response.message_type == "chat_response"
    assert isinstance(response.content, dict)
    assert "response" in response.content
    assert "pest" in response.content["response"].lower() or "crop" in response.content["response"].lower()
