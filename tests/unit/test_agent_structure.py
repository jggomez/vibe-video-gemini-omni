"""Unit tests verifying ADK agent hierarchy and configuration without network API calls."""

from app.agent import root_agent
from app.schemas import CriticReview


def test_root_agent_structure():
    """Verify root SequentialAgent configuration."""
    assert root_agent.name == "vibe_video_pipeline"
    assert len(root_agent.sub_agents) == 3


def test_sub_agents_order_and_output_keys():
    """Verify exact agent sequence and state output keys."""
    alignment_loop, producer, critic = root_agent.sub_agents

    assert alignment_loop.name == "prompt_alignment_loop"
    assert alignment_loop.max_iterations == 3
    assert len(alignment_loop.sub_agents) == 2

    creative_dir_agent, architect = alignment_loop.sub_agents
    assert creative_dir_agent.name == "creative_director"
    assert creative_dir_agent.output_key == "creative_director_review"

    assert architect.name == "prompt_architect"
    assert architect.output_key == "optimized_prompt"
    assert len(architect.tools) >= 1

    assert producer.name == "video_producer"
    assert producer.output_key == "production_result"
    assert len(producer.tools) >= 2

    assert critic.name == "critic"
    assert critic.output_key == "critic_review"
    assert critic.output_schema == CriticReview


def test_critic_callback_signature():
    """Verify _critic_after_agent_callback handles callback_context keyword arg without error."""
    from unittest.mock import MagicMock
    from app.agent import _critic_after_agent_callback

    mock_ctx = MagicMock()
    mock_ctx.state.get.return_value = {"status": "approved"}
    
    # Must not raise TypeError when called with callback_context keyword arg
    _critic_after_agent_callback(callback_context=mock_ctx)
    assert mock_ctx.actions.escalate is True

