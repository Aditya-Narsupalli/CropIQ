import asyncio

from app.core.chat_agent import ChatAgent
from app.core.multi_agent import AgentType, Message, context_protocol


def test_chat_agent_returns_honest_fallback_when_gemini_is_unavailable():
    agent = ChatAgent()
    agent.gemini_client = None  # simulate a missing/invalid API key
    agent.kcc_index = None
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
    # A plain "not available" message - not keyword-guessed advice - and no
    # source label, since nothing actually answered.
    assert "isn't set up" in response.content["response"]
    assert response.content["sources"] is None
    # Failed turns aren't saved as conversation history
    assert not context_protocol.get_context("chat_history_test-session")
