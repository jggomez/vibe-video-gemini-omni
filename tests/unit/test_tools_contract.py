"""Unit tests verifying tool function signatures and contracts."""

import inspect
import pytest

from app.tools import edit_video, generate_video, get_video_artifact


class DummyToolContext:
    def __init__(self, state=None):
        self.state = state if state is not None else {}

    async def save_artifact(self, name, part):
        pass


def test_tool_signatures():
    """Verify tool parameters match ADK expectations."""
    gen_sig = inspect.signature(generate_video)
    assert "prompt" in gen_sig.parameters
    assert "aspect_ratio" in gen_sig.parameters
    assert "tool_context" in gen_sig.parameters

    edit_sig = inspect.signature(edit_video)
    assert "edit_prompt" in edit_sig.parameters
    assert "tool_context" in edit_sig.parameters

    artifact_sig = inspect.signature(get_video_artifact)
    assert "artifact_name" in artifact_sig.parameters
    assert "tool_context" in artifact_sig.parameters


def test_get_video_artifact_contract():
    """Verify get_video_artifact return structure."""
    ctx = DummyToolContext(state={"last_artifact_name": "video_123.mp4"})
    result = get_video_artifact("video_123.mp4", tool_context=ctx)
    assert result["status"] == "success"
    assert result["exists"] is True
    assert result["current_artifact"] == "video_123.mp4"


@pytest.mark.asyncio
async def test_generate_video_safety_blocked_exception():
    """Verify generate_video catches safety block exceptions and returns a blocked status payload."""
    import pytest
    from unittest.mock import MagicMock, patch
    from app.constants import user_api_key_var

    ctx = DummyToolContext(state={"current_turn": 1})
    token = user_api_key_var.set("test_key")

    mock_client = MagicMock()
    mock_client.interactions.create.side_effect = Exception("Request blocked due to prohibited content guidelines.")

    with patch("app.tools._get_client", return_value=mock_client):
        result = await generate_video("a prohibited video", "16:9", ctx)
        assert result["status"] == "blocked"
        assert "prohibited content" in result["error"]
        assert ctx.state["production_result"]["status"] == "blocked"

    user_api_key_var.reset(token)


@pytest.mark.asyncio
async def test_edit_video_safety_blocked_exception():
    """Verify edit_video catches safety block exceptions and returns a blocked status payload."""
    import pytest
    from unittest.mock import MagicMock, patch
    from app.constants import user_api_key_var

    ctx = DummyToolContext(state={"current_turn": 2, "last_interaction_id": "prev_123"})
    token = user_api_key_var.set("test_key")

    mock_client = MagicMock()
    mock_client.interactions.create.side_effect = Exception("Request blocked due to prohibited content guidelines during edit.")

    with patch("app.tools._get_client", return_value=mock_client):
        result = await edit_video("Edit this keeping everything else identical. Make it prohibited.", ctx)
        assert result["status"] == "blocked"
        assert "prohibited content" in result["error"]
        assert ctx.state["production_result"]["status"] == "blocked"

    user_api_key_var.reset(token)
