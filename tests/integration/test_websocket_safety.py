"""Integration test verifying WebSocket studio endpoint recovery and event sequence during a safety block exception."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from app.app_utils.services import get_session_service


@pytest.mark.asyncio
async def test_websocket_safety_block_recovery():
    """Verify WebSocket endpoint sends correct events (thinking, done, turn_complete) on safety blocks and does not fail."""
    session_service = get_session_service()
    app_name = "app"
    user_id = "anonymous"
    session_id = "test_safety_ws_session"

    def make_mock_event(author, is_final=False, text=""):
        event = MagicMock()
        event.author = author
        event.is_final_response.return_value = is_final
        event.content = MagicMock()
        event.content.parts = [MagicMock(text=text)]
        return event

    async def mock_run_async(*args, **kwargs):
        # 1. Start prompt_architect thinking
        # Ensure state has None for agent outputs (mutate existing session state created by main.py)
        try:
            canon = session_service.sessions[app_name][user_id][session_id]
            canon.state.update({
                "optimized_prompt": None,
                "production_result": None,
                "critic_review": None,
            })
        except KeyError:
            # Fallback if not yet created by main.py
            await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state={
                    "current_turn": 1,
                    "optimized_prompt": None,
                    "production_result": None,
                    "critic_review": None,
                }
            )
            canon = session_service.sessions[app_name][user_id][session_id]

        yield make_mock_event("prompt_architect", is_final=False)

        # 2. Complete prompt_architect (yields optimized prompt)
        canon.state["optimized_prompt"] = "A beautiful stylized scenery, digital art"
        yield make_mock_event("prompt_architect", is_final=False)

        # 3. Start video_producer thinking
        yield make_mock_event("video_producer", is_final=False)

        # 4. Complete video_producer with safety block
        canon.state["production_result"] = {
            "status": "blocked",
            "error": "Request blocked due to prohibited content guidelines."
        }
        yield make_mock_event("video_producer", is_final=False)

        # 5. Start critic thinking
        yield make_mock_event("critic", is_final=False)

        # 6. Complete critic (rejects with needs_refinement, score 0)
        canon.state["critic_review"] = {
            "status": "needs_refinement",
            "score": 0,
            "summary": "Request was blocked by safety guidelines.",
            "feedback_points": ["Violent keyword detected"],
            "refinement_suggestions": ["Sanitize and rewrite the prompt using abstract terms"],
        }
        yield make_mock_event("critic", is_final=False)

        # 7. Final turn complete event
        yield make_mock_event("pipeline", is_final=True, text="Turn processed with safety block recovery")

    # Patch the Runner.run_async to yield our custom simulated events
    with patch("main.Runner.run_async", side_effect=mock_run_async):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/studio") as websocket:
                # Trigger the studio turn process
                websocket.send_json({
                    "action": "process_turn",
                    "prompt": "A prohibited action movie prompt",
                    "api_key": "dummy_api_key",
                    "session_id": session_id,
                })

                received_events = []
                # Read messages until turn_complete or error
                for _ in range(15):
                    try:
                        msg = websocket.receive_json()
                        received_events.append(msg)
                        if msg.get("step") in ("turn_complete", "error"):
                            break
                    except Exception:
                        break

                # Verify that we received the correct event sequence and turn completed without errors
                steps = [e.get("step") for e in received_events]
                assert "error" not in steps
                assert "agent_thinking" in steps
                assert "agent_done" in steps
                assert "turn_complete" in steps

                # Verify we got thinking and done events for agents
                architect_done = [
                    e for e in received_events 
                    if e.get("step") == "agent_done" and e.get("agent") == "prompt_architect"
                ]
                producer_done = [
                    e for e in received_events 
                    if e.get("step") == "agent_done" and e.get("agent") == "video_producer"
                ]
                critic_done = [
                    e for e in received_events 
                    if e.get("step") == "agent_done" and e.get("agent") == "critic"
                ]

                assert len(architect_done) == 1
                assert len(producer_done) == 1
                assert len(critic_done) == 1

                # Verify the video producer has blocked status in its payload
                prod_res = producer_done[0].get("production_result")
                assert prod_res is not None
                assert prod_res.get("status") == "blocked"

                # Verify the critic has needs_refinement status and score 0
                crit_rev = critic_done[0].get("critic_review")
                assert crit_rev is not None
                assert crit_rev.get("status") == "needs_refinement"
                assert crit_rev.get("score") == 0

                # Verify turn_complete payload properties
                final_event = received_events[-1]
                assert final_event["step"] == "turn_complete"
                assert final_event["session_id"] == session_id
                assert final_event["production_result"]["status"] == "blocked"
                assert final_event["critic_review"]["status"] == "needs_refinement"
                assert final_event["critic_review"]["score"] == 0
