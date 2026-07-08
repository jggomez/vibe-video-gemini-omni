"""Unit tests verifying the Client caching lifecycle of user_api_client_var and user_live_client_var."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from main import app
from app.constants import user_api_key_var, user_api_client_var, user_live_client_var
from app.agent import _FLASH_MODEL


@pytest.mark.asyncio
async def test_client_caching_lifecycle():
    """Verify context clients are None initially, cached on access, and reset in the finally block."""
    # Save original context values
    orig_api_key = user_api_key_var.get()
    orig_api_client = user_api_client_var.get()
    orig_live_client = user_live_client_var.get()

    async def mock_run_async(*args, **kwargs):
        # 1. Verify they are set to None initially inside the connection run
        assert user_api_client_var.get() is None
        assert user_live_client_var.get() is None

        # Create mocks for client instances
        mock_client = MagicMock()
        mock_live_client = MagicMock()

        # 2. Access properties and verify caching
        with patch("app.agent.Client", side_effect=[mock_client, mock_live_client]):
            c1 = _FLASH_MODEL.api_client
            c2 = _FLASH_MODEL.api_client
            # Verify cached on access (same client returned)
            assert c1 is mock_client
            assert c2 is mock_client
            assert user_api_client_var.get() is mock_client

            lc1 = _FLASH_MODEL._live_api_client
            lc2 = _FLASH_MODEL._live_api_client
            # Verify cached on access
            assert lc1 is mock_live_client
            assert lc2 is mock_live_client
            assert user_live_client_var.get() is mock_live_client

        # Yield a dummy event to simulate pipeline execution
        dummy_event = MagicMock()
        dummy_event.is_final_response.return_value = True
        dummy_event.author = "pipeline"
        dummy_event.content = MagicMock()
        dummy_event.content.parts = [MagicMock(text="success")]
        yield dummy_event

    with patch("main.Runner.run_async", side_effect=mock_run_async):
        # Use context manager to trigger lifespan events (sets app.state.runner)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/studio") as websocket:
                websocket.send_json({
                    "action": "process_turn",
                    "prompt": "A beautiful sunset over the mountains",
                    "api_key": "test_api_key_123",
                    "session_id": "test_session_abc",
                })
                # Read messages until turn_complete
                has_complete = False
                for _ in range(5):
                    try:
                        msg = websocket.receive_json()
                        if msg.get("step") == "turn_complete":
                            has_complete = True
                            break
                    except Exception:
                        break
                assert has_complete

    # 3. Verify they are reset in the finally block
    assert user_api_key_var.get() == orig_api_key
    assert user_api_client_var.get() == orig_api_client
    assert user_live_client_var.get() == orig_live_client
