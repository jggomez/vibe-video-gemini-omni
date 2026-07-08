"""Vibe Video Studio — ADK multi-agent pipeline with Skills support.

Architecture: SequentialAgent orchestrating three LlmAgents:
  1. prompt_architect  — enhances user prompt via 6-dimension framework (Skill attached)
  2. video_producer    — executes Gemini Omni Flash (Google Omni) via Interactions API
  3. critic            — evaluates video quality with structured CriticReview output

State flows: output_key → {state_key} template injection between agents.
Artifacts:   video binary stored/retrieved via ADK GcsArtifactService.

ADK Skills for agents: skills injected as pre_loaded_tools to give agents
access to the prompt engineering knowledge base (https://adk.dev/skills/).
"""


import asyncio
import logging

from dotenv import load_dotenv
from google.adk.agents import Agent, LoopAgent, SequentialAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import Client, types

from app.app_utils.services import get_artifact_service
from app.constants import user_api_client_var, user_api_key_var, user_live_client_var
from app.prompts import (
    ARCHITECT_INSTRUCTION,
    CREATIVE_DIRECTOR_INSTRUCTION,
    CRITIC_INSTRUCTION,
    PRODUCER_INSTRUCTION,
)
from app.schemas import CreativeDirectorReview, CriticReview
from app.tools import edit_video, generate_video, get_video_artifact

logger = logging.getLogger("vibe_video_studio.agent")

load_dotenv()

# ── ADK Skills Initialization for Agents (https://adk.dev/skills/) ───────────
_prompt_architect_skill = load_skill_from_dir(".agents/skills/gemini-omni-prompt-architect")
_omni_flash_skill = load_skill_from_dir(".agents/skills/gemini-omni-flash")
_prompt_eng_skill = load_skill_from_dir(".agents/skills/vibe-video-prompt-engineering")

_architect_skill_toolset = SkillToolset(skills=[_prompt_architect_skill, _prompt_eng_skill])
_architect_skill_tools = asyncio.run(_architect_skill_toolset.get_tools())

_producer_skill_toolset = SkillToolset(skills=[_prompt_architect_skill, _omni_flash_skill, _prompt_eng_skill])
_producer_skill_tools = asyncio.run(_producer_skill_toolset.get_tools())

class DynamicGemini(Gemini):
    """Gemini model variant that dynamically uses the context-local user API key (strictly required)."""

    @property
    def api_client(self) -> Client:
        client = user_api_client_var.get()
        if client is not None:
            return client

        key = user_api_key_var.get()
        if not key:
            raise ValueError("Gemini API Key is required but not provided in user session context.")
        base_url, api_version = self._base_url_and_api_version
        kwargs_for_http_options = {
            'headers': self._tracking_headers(),
            'retry_options': self.retry_options,
            'base_url': base_url,
        }
        if api_version:
            kwargs_for_http_options['api_version'] = api_version

        kwargs = {
            'http_options': types.HttpOptions(**kwargs_for_http_options),
            'api_key': key,
        }
        if self.model.startswith('projects/'):
            kwargs['enterprise'] = True
        client = Client(**kwargs)
        user_api_client_var.set(client)
        return client

    @property
    def _live_api_client(self) -> Client:
        client = user_live_client_var.get()
        if client is not None:
            return client

        key = user_api_key_var.get()
        if not key:
            raise ValueError("Gemini API Key is required but not provided in user session context.")
        base_url, _ = self._base_url_and_api_version
        kwargs = {
            'http_options': types.HttpOptions(
                headers=self._tracking_headers(),
                api_version=self._live_api_version,
                base_url=base_url,
            ),
            'api_key': key,
        }
        if self.model.startswith('projects/'):
            kwargs['enterprise'] = True
        client = Client(**kwargs)
        user_live_client_var.set(client)
        return client


# ── Shared model config (gemini-flash-latest for orchestration agents) ─────────
# Note: Google Omni is called exclusively via tools, not as agent model
_FLASH_MODEL = DynamicGemini(
    model="gemini-flash-latest",
    retry_options=types.HttpRetryOptions(attempts=3),
)
def _director_after_agent_callback(callback_context=None, **kwargs) -> types.Content | None:
    """Check director review and escalate to break out of alignment loop early if approved."""
    ctx = callback_context or kwargs.get("ctx")
    if not ctx:
        return None
    review = ctx.state.get("creative_director_review")
    if not review:
        return None
    approved = review.get("director_approved") if isinstance(review, dict) else getattr(review, "director_approved", False)
    if approved:
        ctx.actions.escalate = True
        return types.Content(
            parts=[types.Part.from_text(text="Creative Director approved the prompt. Exiting alignment loop.")],
            role="model",
        )
    return None


# ── Sub-agent 0: Creative Director ─────────────────────────────────────────────
creative_director = Agent(
    name="creative_director",
    model=_FLASH_MODEL,
    instruction=CREATIVE_DIRECTOR_INSTRUCTION,
    description=(
        "Creative Director Agent. Defines the visual production concept for the "
        "video generation request. Reviews the optimized prompt generated by the "
        "Prompt Architect to check for visual alignment. Outputs structured review."
    ),
    output_schema=CreativeDirectorReview,
    output_key="creative_director_review",
    after_agent_callback=_director_after_agent_callback,
)


# ── Sub-agent 1: Prompt Architect ──────────────────────────────────────────────
# Equipped with gemini-omni-prompt-architect ADK Skill.
# output_key injects {optimized_prompt} into producer state.
prompt_architect = Agent(
    name="prompt_architect",
    model=_FLASH_MODEL,
    instruction=ARCHITECT_INSTRUCTION,
    description=(
        "Expert Gemini Omni Prompt Architect equipped with gemini-omni-prompt-architect "
        "ADK Skill. Transforms raw user requests into precision 6-dimension structured "
        "video prompts. Applies preservation guardrails on edit turns ('Edit this keeping "
        "everything else identical.'). Outputs a single ready-to-generate prompt string."
    ),
    tools=_architect_skill_tools,
    output_key="optimized_prompt",
)

# ── Prompt Alignment Loop Agent (Max 3 iterations) ───────────────────────────
prompt_alignment_loop = LoopAgent(
    name="prompt_alignment_loop",
    description=(
        "Inner loop aligning the Prompt Architect's output with the Creative "
        "Director's concept (max 3 iterations)."
    ),
    sub_agents=[creative_director, prompt_architect],
    max_iterations=3,
)


# ── Sub-agent 2: Video Producer ────────────────────────────────────────────────
# Calls generate_video or edit_video tools (Google Omni via Interactions API).
# Equipped with ADK Skills (gemini-omni-prompt-architect and gemini-omni-flash).
# Reads {optimized_prompt} from state. Stores video in ADK Artifact.
video_producer = Agent(
    name="video_producer",
    model=_FLASH_MODEL,
    instruction=PRODUCER_INSTRUCTION,
    description=(
        "Video Producer Agent equipped with gemini-omni-prompt-architect and "
        "gemini-omni-flash ADK Skills. Calls Gemini Omni Flash (Google Omni) via the "
        "Interactions API to generate or edit videos. Uses ADK Artifacts to store "
        "generated video files. Manages stateful interaction chaining."
    ),
    tools=[generate_video, edit_video, get_video_artifact, *_producer_skill_tools],
    output_key="production_result",
)


async def _critic_inject_video_callback(callback_context, llm_request) -> None:
    """Before-model callback: fetch generated video bytes and inject as multimodal Part.

    ADK's output_schema disables tool calls, so the critic cannot call get_video_artifact
    itself. This callback fetches the artifact and prepends the video inline_data to the
    last Content block — giving the critic genuine visual perception before scoring.
    Returns None so the model call proceeds normally with the mutated request.
    """
    state = callback_context.state
    production_result = state.get("production_result")
    if not production_result:
        return None

    artifact_name = (
        production_result.get("artifact_name")
        if isinstance(production_result, dict)
        else None
    )
    if not artifact_name:
        return None

    try:
        session = callback_context.invocation_context.session
        artifact_service = get_artifact_service()
        artifact = await artifact_service.load_artifact(
            app_name=session.app_name,
            user_id=session.user_id,
            session_id=session.id,
            filename=artifact_name,
        )
        if artifact and artifact.inline_data and artifact.inline_data.data:
            video_part = types.Part(
                inline_data=types.Blob(
                    mime_type="video/mp4",
                    data=artifact.inline_data.data,
                )
            )
            # Prepend video to the last content block (the critic's evaluation request)
            if llm_request.contents:
                llm_request.contents[-1].parts.insert(0, video_part)
            logger.info(
                "Critic: injected video '%s' (%d bytes) for visual evaluation",
                artifact_name,
                len(artifact.inline_data.data),
            )
    except Exception as exc:
        logger.warning("Critic: could not inject video artifact '%s': %s", artifact_name, exc)

    return None


def _critic_after_agent_callback(callback_context=None, **kwargs) -> types.Content | None:
    """Check critic review result and escalate to break out of LoopAgent early if approved."""
    ctx = callback_context or kwargs.get("ctx")
    if not ctx:
        return None
    review = ctx.state.get("critic_review")
    if not review:
        return None
    status = review.get("status") if isinstance(review, dict) else getattr(review, "status", None)
    if status == "approved":
        ctx.actions.escalate = True
        return types.Content(
            parts=[types.Part.from_text(text="Critic approved the video quality. Exiting iterative loop.")],
            role="model",
        )
    return None


# ── Sub-agent 3: Critic ────────────────────────────────────────────────────────
# Uses output_schema for strict CriticReview JSON — disables tool calls.
# Reads {production_result} and {current_turn} from state.
critic = Agent(
    name="critic",
    model=_FLASH_MODEL,
    instruction=CRITIC_INSTRUCTION,
    description=(
        "Quality critic for AI-generated videos. Receives the actual video bytes "
        "via before_model_callback for genuine visual evaluation. Evaluates intent "
        "fidelity, visual quality, turn consistency, and drift risk. Returns "
        "structured CriticReview with score, status, feedback, and remix suggestions."
    ),
    output_schema=CriticReview,
    output_key="critic_review",
    before_model_callback=_critic_inject_video_callback,
    after_agent_callback=_critic_after_agent_callback,
)

# ── Root Agent: SequentialAgent pipeline ─────────────────────────────────────
# IMPORTANT: Must be SequentialAgent, NOT LoopAgent.
# Using LoopAgent here caused escalate=True (set by _director_after_agent_callback
# inside the inner prompt_alignment_loop) to propagate upward through ALL parent
# LoopAgents, skipping video_producer and critic entirely.
# SequentialAgent runs sub_agents in order without escalation propagation.
root_agent = SequentialAgent(
    name="vibe_video_pipeline",
    description=(
        "End-to-end Gemini Omni Vibe Video Studio sequential pipeline: "
        "Prompt Alignment Loop (Creative Director + Architect, max 3 inner iters) "
        "→ Video Producer (Google Omni) → Quality Critic."
    ),
    sub_agents=[prompt_alignment_loop, video_producer, critic],
)

# ── App registration (name MUST match directory "app") ────────────────────────
app = App(
    name="app",
    root_agent=root_agent,
)
