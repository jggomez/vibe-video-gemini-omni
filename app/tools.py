"""ADK FunctionTools for Gemini Omni video generation via Interactions API.

Rules:
# - OMNI_MODEL="gemini-omni-flash-preview" — Gemini Omni Flash model name (mandatory)
# - response_format with delivery="uri" for large payloads (>4MB)
# - ADK Artifacts used to store/retrieve video binary
# - ToolContext for session state (last_interaction_id chaining)
# - All tools return dict (ADK requirement)
"""

import base64
import logging
import os

import httpx
from google import genai
from google.adk.tools import ToolContext
from google.genai import types as genai_types

from app.constants import (
    DEFAULT_ASPECT_RATIO,
    MAX_TURNS_BEFORE_DRIFT,
    OMNI_MODEL,
    VIDEO_MIME_TYPE,
    user_api_client_var,
    user_api_key_var,
)
from app.state_helper import StudioSessionState

logger = logging.getLogger(__name__)


def _get_client() -> genai.Client:
    """Returns a Gemini client using the mandatory user session key, cached per request context."""
    client = user_api_client_var.get()
    if client is not None:
        return client

    key = user_api_key_var.get()
    if not key:
        raise ValueError("Gemini API Key is required but not provided in user session context.")

    client = genai.Client(api_key=key)
    user_api_client_var.set(client)
    return client



async def generate_video(
    prompt: str,
    aspect_ratio: str,
    tool_context: ToolContext,
) -> dict:
    """Generate a new video from a structured 6-dimension prompt using Gemini Omni Flash.

    Calls the Interactions API with model gemini-omni-flash-preview. Saves the resulting video
    binary to an ADK Artifact for persistence and retrieval. Stores the
    interaction_id in session state for subsequent edit turns.

    Args:
        prompt: Fully optimized 6-dimension video generation prompt.
        aspect_ratio: Frame aspect ratio. Use "16:9" for landscape or "9:16" for portrait.

    Returns:
        dict with: status, interaction_id, artifact_name, output_text.
    """
    logger.info("generate_video — model=%s, prompt_len=%d", OMNI_MODEL, len(prompt))
    state = StudioSessionState(tool_context.state)
    try:
        client = _get_client()

        # Check for Image-to-Video reference image in session state
        input_payload = prompt
        ref_img_path = tool_context.state.get("reference_image") or tool_context.state.get("uploaded_image_path")

        # Download from GCS if missing locally (Cloud Run multi-instance fallback)
        if ref_img_path and not os.path.exists(ref_img_path):
            bucket_name = os.environ.get("LOGS_BUCKET_NAME")
            if bucket_name:
                try:
                    from google.cloud import storage
                    safe_name = os.path.basename(ref_img_path)
                    storage_client = storage.Client()
                    bucket = storage_client.bucket(bucket_name)
                    blob = bucket.blob(f"uploads/{safe_name}")
                    if blob.exists():
                        os.makedirs(os.path.dirname(ref_img_path), exist_ok=True)
                        blob.download_to_filename(ref_img_path)
                        logger.info("Downloaded reference image from GCS to local instance path: %s", ref_img_path)
                except Exception as download_err:
                    logger.warning("Failed to download reference image from GCS: %s", download_err)

        if ref_img_path and os.path.exists(ref_img_path):
            try:
                with open(ref_img_path, "rb") as fh:
                    img_bytes = fh.read()
                ext = os.path.splitext(ref_img_path)[1].lower()
                mime = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
                b64_str = base64.b64encode(img_bytes).decode("utf-8")
                input_payload = [
                    {"type": "image", "data": b64_str, "mime_type": mime},
                    {"type": "text", "text": prompt},
                ]
                logger.info("Loaded reference image for Image-to-Video generation: %s", ref_img_path)
            except Exception as img_err:
                logger.warning("Could not read reference image %s: %s", ref_img_path, img_err)

        interaction = client.interactions.create(
            model=OMNI_MODEL,
            input=input_payload,
            background=False,
            store=True,
            stream=False,
            response_format={
                "type": "video",
                "aspect_ratio": aspect_ratio or DEFAULT_ASPECT_RATIO,
                "delivery": "uri",
            },
        )

        interaction_id = interaction.id
        artifact_name = f"video_{interaction_id[:12]}.mp4"

        usage = getattr(interaction, "usage", None)
        in_tok = 0
        out_tok = 0
        if usage:
            in_tok = getattr(usage, "total_input_tokens", 0) or getattr(usage, "prompt_token_count", 0) or getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "total_output_tokens", 0) or getattr(usage, "candidates_token_count", 0) or getattr(usage, "completion_tokens", 0) or 0

        tool_context.state["video_gen_input_tokens"] = tool_context.state.get("video_gen_input_tokens", 0) + in_tok
        tool_context.state["video_gen_output_tokens"] = tool_context.state.get("video_gen_output_tokens", 0) + out_tok

        video_data = _extract_video_bytes(interaction)
        if video_data:
            part = genai_types.Part(
                inline_data=genai_types.Blob(mime_type=VIDEO_MIME_TYPE, data=video_data)
            )
            await tool_context.save_artifact(artifact_name, part)
            logger.info("Saved %d bytes to artifact: %s", len(video_data), artifact_name)
        else:
            logger.error("video_data is None for generate_video! Artifact NOT saved: %s", artifact_name)

        state.last_interaction_id = interaction_id
        state.last_artifact_name = artifact_name
        current_turn = state.current_turn

        return {
            "status": "success",
            "interaction_id": interaction_id,
            "artifact_name": artifact_name,
            "output_text": interaction.output_text or "Video generated.",
            "turn": current_turn,
        }
    except Exception as exc:
        logger.error("generate_video failed: %s", exc, exc_info=True)
        exc_str = str(exc)
        if "prohibited content" in exc_str.lower() or "violated google's" in exc_str.lower() or "safety" in exc_str.lower():
            blocked_msg = f"Request blocked due to prohibited content guidelines: {exc_str}"
            state.production_result = {
                "status": "blocked",
                "error": blocked_msg
            }
            return {
                "status": "blocked",
                "error": blocked_msg,
                "output_text": blocked_msg,
                "turn": state.current_turn,
            }
        raise exc


async def edit_video(
    edit_prompt: str,
    tool_context: ToolContext,
) -> dict:
    """Edit the current video using a targeted conversational instruction.

    Reads the previous interaction_id from session state to chain turns.
    The edit_prompt MUST start with 'Edit this keeping everything else identical.'
    to apply preservation guardrails. Saves the new video to an ADK Artifact.

    Args:
        edit_prompt: Targeted edit instruction with preservation guardrail prefix applied.

    Returns:
        dict with: status, interaction_id, artifact_name, output_text, turn.
    """
    state = StudioSessionState(tool_context.state)
    previous_id = state.last_interaction_id
    if not previous_id:
        return {
            "status": "error",
            "error": "No prior video session. Call generate_video first.",
        }

    current_turn = state.current_turn
    logger.info("edit_video — turn=%d, prev_id=%s", current_turn + 1, previous_id[:12])

    if not edit_prompt.strip().lower().startswith("edit this keeping"):
        edit_prompt = f"Edit this keeping everything else identical. {edit_prompt}"

    try:
        client = _get_client()
        interaction = client.interactions.create(
            model=OMNI_MODEL,
            input=edit_prompt,
            previous_interaction_id=previous_id,
            background=False,
            store=True,
            stream=False,
            response_format={
                "type": "video",
                "aspect_ratio": DEFAULT_ASPECT_RATIO,
                "delivery": "uri",
            },
        )

        new_id = interaction.id
        current_turn = state.current_turn
        artifact_name = f"video_{new_id[:12]}.mp4"

        usage = getattr(interaction, "usage", None)
        in_tok = 0
        out_tok = 0
        if usage:
            in_tok = getattr(usage, "total_input_tokens", 0) or getattr(usage, "prompt_token_count", 0) or getattr(usage, "prompt_tokens", 0) or 0
            out_tok = getattr(usage, "total_output_tokens", 0) or getattr(usage, "candidates_token_count", 0) or getattr(usage, "completion_tokens", 0) or 0

        tool_context.state["video_gen_input_tokens"] = tool_context.state.get("video_gen_input_tokens", 0) + in_tok
        tool_context.state["video_gen_output_tokens"] = tool_context.state.get("video_gen_output_tokens", 0) + out_tok

        video_data = _extract_video_bytes(interaction)
        if video_data:
            part = genai_types.Part(
                inline_data=genai_types.Blob(mime_type=VIDEO_MIME_TYPE, data=video_data)
            )
            await tool_context.save_artifact(artifact_name, part)
            logger.info("Saved edit artifact: %s (%d bytes)", artifact_name, len(video_data))
        else:
            logger.error("video_data is None for edit_video! Artifact NOT saved: %s", artifact_name)

        state.last_interaction_id = new_id
        state.last_artifact_name = artifact_name

        drift_warning = current_turn >= MAX_TURNS_BEFORE_DRIFT

        return {
            "status": "success",
            "interaction_id": new_id,
            "previous_interaction_id": previous_id,
            "artifact_name": artifact_name,
            "output_text": interaction.output_text or "Edit applied.",
            "turn": current_turn,
            "drift_warning": drift_warning,
        }
    except Exception as exc:
        logger.error("edit_video failed: %s", exc, exc_info=True)
        exc_str = str(exc)
        if "prohibited content" in exc_str.lower() or "violated google's" in exc_str.lower() or "safety" in exc_str.lower():
            blocked_msg = f"Request blocked due to prohibited content guidelines during edit: {exc_str}"
            state.production_result = {
                "status": "blocked",
                "error": blocked_msg
            }
            return {
                "status": "blocked",
                "error": blocked_msg,
                "output_text": blocked_msg,
                "turn": state.current_turn,
            }
        raise exc


def get_video_artifact(
    artifact_name: str,
    tool_context: ToolContext,
) -> dict:
    """Retrieve metadata about a stored video artifact.

    Args:
        artifact_name: The artifact filename (e.g. 'video_abc123.mp4').

    Returns:
        dict with: status, artifact_name, exists.
    """
    last_artifact = tool_context.state.get("last_artifact_name", "")
    return {
        "status": "success",
        "artifact_name": artifact_name,
        "exists": artifact_name == last_artifact or bool(last_artifact),
        "current_artifact": last_artifact,
    }


def _extract_video_bytes(interaction) -> bytes | None:
    """Extract video bytes from an interaction response."""
    try:
        out_vid = getattr(interaction, "output_video", None)
        if out_vid:
            data = getattr(out_vid, "data", None)
            if data:
                return data

            uri = getattr(out_vid, "uri", None)
            file_id = uri.split("/")[-1] if uri and "/" in uri else (uri or "")
            if ":" in file_id:
                file_id = file_id.split(":")[0]
            if "?" in file_id:
                file_id = file_id.split("?")[0]

            if file_id:
                client = _get_client()
                try:
                    downloaded = client.files.download(file=file_id)
                    if downloaded:
                        logger.info("Successfully downloaded video bytes via SDK (%d bytes)", len(downloaded))
                        return downloaded
                except Exception as sdk_err:
                    logger.warning("SDK file download failed (%s), trying httpx fallback", sdk_err)

            if uri:
                try:
                    api_key = user_api_key_var.get() or ""
                    headers = {"x-goog-api-key": api_key} if api_key else {}
                    resp = httpx.get(uri, headers=headers, follow_redirects=True, timeout=60.0)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        logger.info("Successfully downloaded video bytes via httpx (%d bytes)", len(resp.content))
                        return resp.content
                except Exception as http_err:
                    logger.warning("httpx video download failed: %s", http_err)

        if hasattr(interaction, "content") and interaction.content:
            for part in interaction.content.parts or []:
                if hasattr(part, "inline_data") and part.inline_data:
                    if "video" in (part.inline_data.mime_type or ""):
                        return part.inline_data.data
    except Exception as exc:
        logger.warning("Could not extract video bytes: %s", exc, exc_info=True)
    return None
