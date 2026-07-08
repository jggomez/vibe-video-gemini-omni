"""Vibe Video Studio — FastAPI server entry point.

Thin wrapper over ADK get_fast_api_app. Custom routes:
  GET  /api/health              — liveness probe
  POST /api/upload              — reference image upload
  GET  /api/videos/{artifact}   — serve video from ADK Artifact
  WS   /ws/studio               — stream ADK agent pipeline events

All agent logic lives in app/agent.py. This module is SRP: HTTP surface only.
"""

import contextlib
import logging
import os
import uuid
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.genai.types import Content, Part

from app.app_utils.services import get_artifact_service, get_session_service
from app.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_USER_ID,
    VIDEO_MIME_TYPE,
    user_api_client_var,
    user_api_key_var,
    user_live_client_var,
)
from backend.event_dispatcher import StudioEventDispatcher

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("vibe_video_studio")

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(_ROOT_DIR, "uploads")
FRONTEND_DIR = os.path.join(_ROOT_DIR, "frontend")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FRONTEND_DIR, exist_ok=True)

_allow_origins_raw = os.getenv("ALLOW_ORIGINS", "")
allow_origins = _allow_origins_raw.split(",") if _allow_origins_raw else None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.agent import app as adk_app

    runner = Runner(
        app=adk_app,
        session_service=get_session_service(),
        artifact_service=get_artifact_service(),
        auto_create_session=True,
    )
    app.state.runner = runner
    app.state.agent_app_name = adk_app.name
    yield


app: FastAPI = get_fast_api_app(
    agents_dir=_ROOT_DIR,
    web=False,
    allow_origins=allow_origins,
    lifespan=lifespan,
)
app.title = "Vibe Video Studio"
app.description = "Gemini Omni Multi-Agent Video Generation API"
app.version = "2.0.0"


@app.get("/api/health")
async def health_check() -> dict:
    """Liveness probe."""
    return {"status": "ok", "service": "Vibe Video Studio", "version": "2.0.0"}


@app.post("/api/upload")
async def upload_asset(file: UploadFile) -> dict:
    """Upload a reference image for image-to-video generation."""
    extension = os.path.splitext(file.filename or "asset.bin")[1]
    safe_name = f"{uuid.uuid4().hex[:8]}{extension}"
    dest = os.path.join(UPLOAD_DIR, safe_name)
    content = await file.read()

    # Save locally (works on local machine and active instance)
    with open(dest, "wb") as fh:
        fh.write(content)
    logger.info("Uploaded asset locally: %s (%d bytes)", safe_name, len(content))

    # Backup to GCS (allows multi-instance sharing on Cloud Run)
    bucket_name = os.environ.get("LOGS_BUCKET_NAME")
    if bucket_name:
        try:
            from google.cloud import storage
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(f"uploads/{safe_name}")
            blob.upload_from_string(content, content_type=file.content_type)
            logger.info("Uploaded reference image to GCS: gs://%s/uploads/%s", bucket_name, safe_name)
        except Exception as gcs_err:
            logger.warning("Failed to upload reference image to GCS: %s", gcs_err)

    return {"status": "success", "url": f"/uploads/{safe_name}", "name": safe_name}


@app.get("/api/videos/{artifact_name}")
async def get_video(
    artifact_name: str,
    session_id: str = Query(default=""),
    user_id: str = Query(default=DEFAULT_USER_ID),
) -> Response:
    """Serve a video from ADK Artifact storage."""
    artifact_service = get_artifact_service()
    app_name = "app"

    try:
        artifact = None
        if session_id:
            artifact = await artifact_service.load_artifact(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                filename=artifact_name,
            )
        if not artifact or not artifact.inline_data:
            # Fallback lookup without session_id restriction
            artifact = await artifact_service.load_artifact(
                app_name=app_name,
                user_id=user_id,
                session_id="",
                filename=artifact_name,
            )

        if artifact and artifact.inline_data:
            return Response(
                content=artifact.inline_data.data,
                media_type=VIDEO_MIME_TYPE,
                headers={
                    "Content-Disposition": f'inline; filename="{artifact_name}"',
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                },
            )
    except Exception as exc:
        logger.warning("Artifact lookup failed for %s: %s", artifact_name, exc)

    placeholder = b"\x00\x00\x00\x1cftypisom\x00\x00\x00\x00isomiso2avc1mp41" + b"\x00" * 256
    return Response(content=placeholder, media_type=VIDEO_MIME_TYPE)


# ── ADK agent author names (must match agent.py name= fields) ─────────────────
_AGENT_CREATIVE_DIRECTOR = "creative_director"
_AGENT_PROMPT_ARCHITECT = "prompt_architect"
_AGENT_VIDEO_PRODUCER = "video_producer"
_AGENT_CRITIC = "critic"
_KNOWN_AGENTS = {_AGENT_CREATIVE_DIRECTOR, _AGENT_PROMPT_ARCHITECT, _AGENT_VIDEO_PRODUCER, _AGENT_CRITIC}


@app.websocket("/ws/studio")
async def websocket_studio(websocket: WebSocket) -> None:
    """Stream ADK multi-agent pipeline events to browser clients.

    Event protocol (sent to client):
      {step: "agent_thinking", agent: str, iteration: int}
        — agent has started processing, show thinking dots

      {step: "agent_done", agent: str, iteration: int,
       optimized_prompt?, production_result?, critic_review?}
        — agent produced output, render its result card

      {step: "turn_complete", ...full payload...}
        — pipeline finished, render video + timeline chip

      {step: "error", message: str}
        — unrecoverable failure
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    runner: Runner = websocket.app.state.runner
    app_name: str = websocket.app.state.agent_app_name
    session_service = get_session_service()

    try:
        while True:
            data = await websocket.receive_json()

            action = data.get("action")
            if action == "ping":
                await websocket.send_json({"step": "pong"})
                continue

            if action != "process_turn":
                await websocket.send_json({"error": "Unknown action. Use 'process_turn'."})
                continue

            user_prompt: str = data.get("prompt", "").strip()
            session_id: str = data.get("session_id") or uuid.uuid4().hex
            user_id: str = data.get("user_id", DEFAULT_USER_ID)
            uploaded_img: str = data.get("uploaded_image_path", "").strip()
            user_api_key: str = data.get("api_key", "").strip() or None

            if not user_api_key:
                await websocket.send_json({
                    "step": "error",
                    "message": "Gemini API Key is strictly required. Please input a valid API Key in the field at the top."
                })
                continue

            if not user_prompt:
                await websocket.send_json({"step": "error", "message": "Prompt is required"})
                continue

            try:
                session = await session_service.get_session(
                    app_name=app_name, user_id=user_id, session_id=session_id
                )
            except Exception:
                session = None

            if session is None:
                initial_state: dict = {
                    "current_turn": 0,
                    "creative_director_review": "",
                    "optimized_prompt": "",
                    "production_result": "",
                    "critic_review": "",
                    "user_api_key": user_api_key,
                }
                if uploaded_img:
                    local_img = os.path.join(_ROOT_DIR, uploaded_img.lstrip("/"))
                    initial_state["reference_image"] = local_img
                session = await session_service.create_session(
                    app_name=app_name,
                    user_id=user_id,
                    session_id=session_id,
                    state=initial_state,
                )

            # ── Persist state mutations directly to the canonical stored session ──
            # InMemorySessionService.get_session() returns a COPY, not the canonical
            # object. We must mutate self.sessions[app][user][id].state directly so
            # ADK's runner (which also calls get_session internally) sees the reset.
            def _patch_canonical_state(
                updates: dict,
                _uid: str = user_id,
                _sid: str = session_id,
            ) -> None:
                try:
                    canon = session_service.sessions[app_name][_uid][_sid]
                    canon.state.update(updates)
                except (KeyError, AttributeError):
                    pass  # fallback: session not yet stored, first turn

            # Parse duration from user prompt
            duration_secs = 5.0
            import re
            dur_match = re.search(r"Target duration (\d+(?:\.\d+)?)s:", user_prompt)
            if dur_match:
                duration_secs = float(dur_match.group(1))

            # Increment turn counter
            current_turn_num: int = (session.state.get("current_turn") or 0) + 1

            state_updates: dict = {
                "current_turn": current_turn_num,
                # Use empty strings (not None) so ADK template injection
                # of {creative_director_review} etc. renders cleanly on turn 1
                "creative_director_review": "",
                "optimized_prompt": "",
                "production_result": "",
                "critic_review": "",
                "user_api_key": user_api_key,
                "target_duration_secs": (session.state.get("target_duration_secs", 0.0) or 0.0) + duration_secs,
                "creative_director_input_tokens": session.state.get("creative_director_input_tokens", 0) or 0,
                "creative_director_output_tokens": session.state.get("creative_director_output_tokens", 0) or 0,
                "prompt_architect_input_tokens": session.state.get("prompt_architect_input_tokens", 0) or 0,
                "prompt_architect_output_tokens": session.state.get("prompt_architect_output_tokens", 0) or 0,
                "video_producer_input_tokens": session.state.get("video_producer_input_tokens", 0) or 0,
                "video_producer_output_tokens": session.state.get("video_producer_output_tokens", 0) or 0,
                "critic_input_tokens": session.state.get("critic_input_tokens", 0) or 0,
                "critic_output_tokens": session.state.get("critic_output_tokens", 0) or 0,
                "video_gen_input_tokens": session.state.get("video_gen_input_tokens", 0) or 0,
                "video_gen_output_tokens": session.state.get("video_gen_output_tokens", 0) or 0,
            }

            if uploaded_img:
                local_img = os.path.join(_ROOT_DIR, uploaded_img.lstrip("/"))
                state_updates["reference_image"] = local_img
                state_updates["uploaded_image_path"] = local_img
            else:
                state_updates["reference_image"] = None
                state_updates["uploaded_image_path"] = None

            _patch_canonical_state(state_updates)

            dispatcher = StudioEventDispatcher(
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
            )
            dispatcher.initialize_turn(session.state)
            _finalize_sent = False  # guard: send turn_complete only once

            message = Content(parts=[Part(text=user_prompt)], role="user")

            token_key = user_api_key_var.set(user_api_key)
            token_api_client = user_api_client_var.set(None)
            token_live_client = user_live_client_var.set(None)
            try:
                async with contextlib.aclosing(
                    runner.run_async(
                        user_id=user_id,
                        session_id=session_id,
                        new_message=message,
                    )
                ) as generator:
                    async for event in generator:
                        event_author = getattr(event, "author", None) or "pipeline"
                        is_final = event.is_final_response()

                        # Detailed debug log for every ADK event
                        logger.info(
                            "[ADK event] author=%s is_final=%s has_content=%s",
                            event_author,
                            is_final,
                            bool(event.content and event.content.parts),
                        )

                        # ── Extract and store token usage from ADK model events ───────
                        usage = getattr(event, "usage_metadata", None)
                        if usage and "mock" not in type(usage).__name__.lower():
                            p_tok = getattr(usage, "prompt_token_count", 0) or 0
                            o_tok = getattr(usage, "candidates_token_count", 0) or 0

                            cur_sess = await session_service.get_session(
                                app_name=app_name, user_id=user_id, session_id=session_id
                            )
                            cur_state = cur_sess.state if cur_sess else {}

                            if event_author == "creative_director":
                                _patch_canonical_state({
                                    "creative_director_input_tokens": cur_state.get("creative_director_input_tokens", 0) + p_tok,
                                    "creative_director_output_tokens": cur_state.get("creative_director_output_tokens", 0) + o_tok,
                                })
                            elif event_author == "prompt_architect":
                                _patch_canonical_state({
                                    "prompt_architect_input_tokens": cur_state.get("prompt_architect_input_tokens", 0) + p_tok,
                                    "prompt_architect_output_tokens": cur_state.get("prompt_architect_output_tokens", 0) + o_tok,
                                })
                            elif event_author == "video_producer":
                                _patch_canonical_state({
                                    "video_producer_input_tokens": cur_state.get("video_producer_input_tokens", 0) + p_tok,
                                    "video_producer_output_tokens": cur_state.get("video_producer_output_tokens", 0) + o_tok,
                                })
                            elif event_author == "critic":
                                _patch_canonical_state({
                                    "critic_input_tokens": cur_state.get("critic_input_tokens", 0) + p_tok,
                                    "critic_output_tokens": cur_state.get("critic_output_tokens", 0) + o_tok,
                                })

                        # ── Refresh session state after each event ────────────────────
                        updated_session = await session_service.get_session(
                            app_name=app_name, user_id=user_id, session_id=session_id
                        )
                        state = updated_session.state if updated_session else {}

                        # Always dispatch to known sub-agents (thinking + done events)
                        # even on is_final_response — LoopAgent may emit final from a sub-agent
                        if event_author in _KNOWN_AGENTS:
                            await dispatcher.handle_event(
                                event_author=event_author,
                                current_turn_num=current_turn_num,
                                state=state,
                                is_final=is_final,
                            )

                        # Only send turn_complete ONCE — on the root pipeline's final event.
                        # Sub-agents (creative_director, prompt_architect, critic, etc.) also
                        # emit is_final=True for their own outputs, but we must ignore those
                        # to avoid sending multiple premature turn_complete messages that
                        # overwrite the frontend before all agents have finished.
                        _ROOT_AGENT_NAME = "vibe_video_pipeline"
                        if is_final and not _finalize_sent and event_author == _ROOT_AGENT_NAME:
                            _finalize_sent = True
                            final_text = ""
                            if event.content and event.content.parts:
                                final_text = event.content.parts[0].text or ""
                            await dispatcher.finalize_turn(
                                final_text=final_text,
                                current_turn_num=current_turn_num,
                                state=state,
                            )

                # Fallback: if root agent never emitted a final event (SequentialAgent quirk),
                # send turn_complete after the generator exhausts.
                if not _finalize_sent:
                    final_sess = await session_service.get_session(
                        app_name=app_name, user_id=user_id, session_id=session_id
                    )
                    final_state = final_sess.state if final_sess else {}
                    await dispatcher.finalize_turn(
                        final_text="",
                        current_turn_num=current_turn_num,
                        state=final_state,
                    )
            finally:
                user_api_key_var.reset(token_key)
                user_api_client_var.reset(token_api_client)
                user_live_client_var.reset(token_live_client)


    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as exc:
        logger.error("WebSocket error: %s", exc, exc_info=True)
        try:
            await websocket.send_json({"step": "error", "message": str(exc)})
        except Exception:
            pass


@app.get("/")
async def serve_index() -> FileResponse:
    """Serve Vibe Video Studio single-page application."""
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/favicon.ico")
async def serve_favicon() -> FileResponse:
    """Serve Vibe Video Studio favicon."""
    return FileResponse(os.path.join(FRONTEND_DIR, "favicon.png"))


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", DEFAULT_HOST),
        port=int(os.getenv("PORT", str(DEFAULT_PORT))),
        reload=True,
    )
