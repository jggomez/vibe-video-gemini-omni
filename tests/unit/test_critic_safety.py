"""Unit tests verifying that the Critic agent handles blocked production results correctly."""

import contextlib
import pytest
from unittest.mock import MagicMock, patch

from google.adk.apps import App
from google.adk.runners import Runner
from google.genai import types
from google.adk.models import LlmResponse
from app.agent import critic, DynamicGemini
from app.app_utils.services import get_session_service, get_artifact_service
from app.schemas import CriticReview


@pytest.mark.asyncio
async def test_critic_safety_block_handling():
    """Verify Critic agent evaluates blocked production result as needs_refinement with score 0 and suggestions."""
    # 1. Create a dummy app with only the critic agent as the root agent
    critic_app = App(name="critic_app", root_agent=critic)

    # 2. Setup the runner
    session_service = get_session_service()
    artifact_service = get_artifact_service()
    runner = Runner(
        app=critic_app,
        session_service=session_service,
        artifact_service=artifact_service,
        auto_create_session=True,
    )

    # 3. Create session with blocked production result in the state
    user_id = "test_user_critic"
    session_id = "test_critic_session"

    await session_service.create_session(
        app_name="critic_app",
        user_id=user_id,
        session_id=session_id,
        state={
            "optimized_prompt": "A prohibited prompt with forbidden elements",
            "production_result": {
                "status": "blocked",
                "error": "Request blocked due to prohibited content guidelines."
            },
            "current_turn": 1,
        }
    )

    # 4. Mock the Critic's model's generate_content_async call
    mock_review = CriticReview(
        score=0,
        status="needs_refinement",
        summary="The video generation was blocked by safety policy filters.",
        feedback_points=["Prohibited content detected in generation request"],
        refinement_suggestions=["Sanitize action descriptions and use metaphoric visual descriptors"],
        turn_drift_warning=False,
    )

    json_text = mock_review.model_dump_json()

    async def mock_generate_content_async(self, llm_request, stream=False):
        # Verify the prompt instruction contains the safety block handling instructions
        system_instruction = llm_request.config.system_instruction
        assert "Safety & Content Block Handling" in system_instruction

        # Yield the mock LLM response containing the JSON text
        yield LlmResponse(
            content=types.Content(
                parts=[types.Part.from_text(text=json_text)],
                role="model"
            )
        )

    # We patch DynamicGemini's class method generate_content_async
    with patch("app.agent.DynamicGemini.generate_content_async", mock_generate_content_async):
        message = types.Content(parts=[types.Part(text="run")], role="user")
        async with contextlib.aclosing(
            runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=message,
            )
        ) as generator:
            async for _ in generator:
                pass

    # 5. Load session and verify the critic_review state was updated correctly
    session = await session_service.get_session(
        app_name="critic_app",
        user_id=user_id,
        session_id=session_id
    )

    critic_review = session.state.get("critic_review")
    assert critic_review is not None
    assert critic_review["status"] == "needs_refinement"
    assert critic_review["score"] == 0
    assert "blocked" in critic_review["summary"].lower()
    assert len(critic_review["feedback_points"]) > 0
    assert len(critic_review["refinement_suggestions"]) > 0
