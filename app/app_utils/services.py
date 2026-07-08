"""Process-wide ADK session/artifact services shared across every serving surface.

Registered under shared:// so the ADK web routes, A2A path, and any
custom endpoints share one instance — a session created on any surface
is visible to the others.
"""

from __future__ import annotations

import functools
import os

from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.sessions import InMemorySessionService

SESSION_SERVICE_URI = "shared://session"
ARTIFACT_SERVICE_URI = "shared://artifact"


@functools.cache
def get_session_service() -> InMemorySessionService:
    """Process-wide session service, environment-driven."""
    if bucket := os.environ.get("SESSION_SERVICE_URI"):
        # Cloud SQL or Agent Platform Sessions when configured
        try:
            from google.adk.cli.utils.service_factory import (
                create_session_service_from_options,
            )
            _agent_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            return create_session_service_from_options(
                base_dir=_agent_dir, session_service_uri=bucket
            )
        except ImportError:
            pass
    if agent_engine_id := os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService
        return VertexAiSessionService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=(
                os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION")
                or os.environ.get("GOOGLE_CLOUD_LOCATION")
            ),
            agent_engine_id=agent_engine_id,
        )
    return InMemorySessionService()


@functools.cache
def get_artifact_service():
    """Process-wide artifact service: GCS when bucket configured, else in-memory."""
    if bucket := os.environ.get("LOGS_BUCKET_NAME"):
        return GcsArtifactService(bucket_name=bucket)
    return InMemoryArtifactService()
