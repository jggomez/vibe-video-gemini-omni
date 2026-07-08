"""Output schemas for structured ADK agent responses.

Using output_schema on agents that return structured data. Note: agents with
output_schema cannot call tools — they are single-turn structured responders.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ArchitectProposal(BaseModel):
    """Structured output from the Prompt Architect agent."""

    original_prompt: str = Field(description="The user's raw input prompt")
    optimized_prompt: str = Field(
        description="Expanded prompt following the 6-dimension framework"
    )
    is_edit_turn: bool = Field(
        default=False, description="Whether preservation guardrails were applied"
    )
    analysis: dict[str, str] = Field(
        description="Breakdown of the 6 dimensions applied"
    )


class CriticReview(BaseModel):
    """Structured quality review from the Critic agent."""

    score: int = Field(ge=0, le=100, description="Quality score between 0 and 100")
    status: Literal["approved", "needs_refinement"] = Field(
        description="Approval status"
    )
    summary: str = Field(description="Concise assessment of the video output")
    feedback_points: list[str] = Field(
        description="Specific visual observations and strengths"
    )
    refinement_suggestions: list[str] = Field(
        description="Actionable prompt remixes for the next iteration"
    )
    turn_drift_warning: bool = Field(
        default=False,
        description="True when turn >= 4 and visual drift risk is high",
    )


class CreativeDirectorReview(BaseModel):
    """Structured review from the Creative Director agent."""

    production_concept: str = Field(
        description="The detailed cinematic scene production concept or idea derived from the user's prompt."
    )
    director_approved: bool = Field(
        description="Set to True ONLY if the optimized_prompt is fully aligned with the production_concept. Set to False on the first run or if refinement is needed."
    )
    director_feedback: str = Field(
        description="Detailed feedback to the prompt architect describing how to improve and align the prompt with the production concept. Leave empty if approved."
    )
