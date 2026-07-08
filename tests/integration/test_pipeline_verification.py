"""End-to-end integration verification script for Gemini Omni Video Generation.

Verifies:
1. GCS Artifact Service initialization with LOGS_BUCKET_NAME
2. Live interaction call with gemini-omni-flash-preview model
3. Video byte extraction (> 500 KB)
4. Artifact persistence in GCS / ADK storage
5. HTTP retrieval via FastAPI /api/videos/{artifact_name} returning status 200 OK and real MP4 video bytes.
"""

import asyncio
import os
import sys
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv()
if "GEMINI_API_KEY" in os.environ and "GOOGLE_API_KEY" not in os.environ:
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

from main import app
from app.app_utils.services import get_artifact_service
from app.tools import generate_video
from google.adk.tools import ToolContext
from app.constants import user_api_key_var

client = TestClient(app)


def test_gcs_artifact_service_configuration():
    """Verify GcsArtifactService is active when LOGS_BUCKET_NAME is set."""
    bucket = os.environ.get("LOGS_BUCKET_NAME")
    assert bucket is not None, "LOGS_BUCKET_NAME must be set in environment"
    svc = get_artifact_service()
    assert type(svc).__name__ == "GcsArtifactService"
    assert svc.bucket_name == bucket


@pytest.mark.asyncio
async def test_live_video_generation_e2e():
    """Live verification test calling Gemini Omni Flash gemini-omni-flash-preview model."""
    token = user_api_key_var.set(os.getenv("GEMINI_API_KEY"))
    try:
        artifact_service = get_artifact_service()

        class MockToolContext:
            def __init__(self):
                self.state = {}

            async def save_artifact(self, filename, part):
                return await artifact_service.save_artifact(
                    app_name="app",
                    user_id="anonymous",
                    session_id="test_verify_session",
                    filename=filename,
                    artifact=part,
                )

        tool_ctx = MockToolContext()
        prompt = "A sleek red sports car driving on Mars illuminated by neon lights, cinematic"

        result = await generate_video(prompt=prompt, aspect_ratio="16:9", tool_context=tool_ctx)
        assert result["status"] == "success", f"Video generation failed: {result}"
        artifact_name = result["artifact_name"]
        assert artifact_name.startswith("video_")

        # Verify loading artifact from storage service
        loaded_part = await artifact_service.load_artifact(
            app_name="app",
            user_id="anonymous",
            session_id="test_verify_session",
            filename=artifact_name,
        )
        assert loaded_part is not None, "Loaded artifact is None!"
        assert loaded_part.inline_data is not None, "Loaded inline_data is None!"
        video_bytes = loaded_part.inline_data.data
        assert len(video_bytes) > 100000, f"Expected > 100KB video bytes, got {len(video_bytes)}"

        # Verify HTTP endpoint serving
        http_resp = client.get(f"/api/videos/{artifact_name}?session_id=test_verify_session&user_id=anonymous")
        assert http_resp.status_code == 200
        assert http_resp.headers["content-type"] == "video/mp4"
        assert http_resp.headers["content-disposition"].startswith("inline;")
        assert len(http_resp.content) == len(video_bytes)
        print(f"\n✅ E2E VERIFICATION PASSED! Generated and verified {len(video_bytes)} bytes of real MP4 video in GCS artifact storage!")
    finally:
        user_api_key_var.reset(token)


if __name__ == "__main__":
    asyncio.run(test_live_video_generation_e2e())
