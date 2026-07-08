"""System instructions for all Vibe Video Studio agents.

Separated from agent definitions (SRP). Loads prompts dynamically from separate
markdown instruction files in app/instructions/ to prevent Primitive Obsession.
"""

import os

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
_INSTRUCTIONS_DIR = os.path.join(_ROOT_DIR, "instructions")


def _load_instruction(filename: str, fallback: str) -> str:
    """Loads prompt text from file, with fallback support."""
    path = os.path.join(_INSTRUCTIONS_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()
        except Exception:
            pass
    return fallback


# Fallback instructions in case files are missing or unreadable at runtime.
_DIRECTOR_FALLBACK = """You are the Gemini Omni Creative Director Agent. Your primary responsibility is to outline the artistic and production concept for the generated video and ensure that the Prompt Architect's optimized prompt aligns perfectly with this concept.
## Execution Context
- Current Turn: {current_turn}
- Existing Production Concept (if any): {creative_director_review}
- Optimized Prompt under Review (if any): {optimized_prompt}
"""

_ARCHITECT_FALLBACK = """You are the Gemini Omni Prompt Architect Agent. Your single responsibility is to transform raw user video requests into world-class, precision-engineered prompts for the Google Omni (Gemini Omni Flash) model.
## Execution Context
- Current Turn: {current_turn}
- Creative Director Review/Concept: {creative_director_review}
- Previous Critic Review (if any): {critic_review}
"""

_PRODUCER_FALLBACK = """You are the Video Producer Agent. Your primary responsibility is executing video generation and conversational video editing using the Gemini Omni Flash model (Google Omni) via the Interactions API tools.
## Execution Context
- Optimized Prompt in State: {optimized_prompt}
- Current Turn: {current_turn}
"""

_CRITIC_FALLBACK = """You are the Gemini Omni Critic Agent — expert quality controller for AI-generated videos.
## Evaluation Context
- Production result metadata: {production_result}
- Current turn: {current_turn}
- Optimized prompt used: {optimized_prompt}
"""

# Dynamic loading
CREATIVE_DIRECTOR_INSTRUCTION: str = _load_instruction("creative_director.md", _DIRECTOR_FALLBACK)
ARCHITECT_INSTRUCTION: str = _load_instruction("prompt_architect.md", _ARCHITECT_FALLBACK)
PRODUCER_INSTRUCTION: str = _load_instruction("video_producer.md", _PRODUCER_FALLBACK)
CRITIC_INSTRUCTION: str = _load_instruction("critic.md", _CRITIC_FALLBACK)
