"""Unit tests verifying turn management contract across tools and session handler."""

from unittest.mock import MagicMock, patch
import pytest

from app.tools import edit_video, generate_video


class DummyToolContext:
    def __init__(self, state=None):
        self.state = state if state is not None else {}

    async def save_artifact(self, name, part):
        pass


@pytest.mark.asyncio
async def test_turn_management_contract():
    """Verify generate_video and edit_video do NOT increment current_turn, and main.py logic manages it."""
    mock_interaction = MagicMock()
    mock_interaction.id = "test_interaction_12345"
    mock_interaction.output_text = "Video generated successfully"
    mock_interaction.output_video = None

    mock_client = MagicMock()
    mock_client.interactions.create.return_value = mock_interaction

    session_state = {"current_turn": 1}
    ctx = DummyToolContext(state=session_state)

    with patch("app.tools._get_client", return_value=mock_client):
        gen_result = await generate_video(
            prompt="A futuristic city with flying cars",
            aspect_ratio="16:9",
            tool_context=ctx,
        )
        assert gen_result["status"] == "success"
        assert ctx.state["current_turn"] == 1, "generate_video must not increment current_turn"

        edit_result = await edit_video(
            edit_prompt="Add neon lights",
            tool_context=ctx,
        )
        assert edit_result["status"] == "success"
        assert ctx.state["current_turn"] == 1, "edit_video must not increment current_turn"

    session_state["current_turn"] = session_state.get("current_turn", 0) + 1
    assert session_state["current_turn"] == 2, "main.py must manage current_turn per request"
