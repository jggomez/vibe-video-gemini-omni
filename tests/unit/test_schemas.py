"""Unit tests for Pydantic schema validation."""

import pytest
from pydantic import ValidationError

from app.schemas import CriticReview


def test_critic_review_valid():
    """Verify valid CriticReview construction."""
    review = CriticReview(
        score=85,
        status="approved",
        summary="Good visual alignment and motion.",
        feedback_points=["Shot framing matches prompt spec", "Lighting is coherent"],
        refinement_suggestions=["Add sunset golden hour glow"],
        turn_drift_warning=False,
    )
    assert review.score == 85
    assert review.status == "approved"
    assert review.turn_drift_warning is False


def test_critic_review_score_boundary():
    """Verify score boundary constraints (0 to 100)."""
    r_min = CriticReview(
        score=0,
        status="needs_refinement",
        summary="Failed completely",
        feedback_points=[],
        refinement_suggestions=[],
    )
    assert r_min.score == 0

    r_max = CriticReview(
        score=100,
        status="approved",
        summary="Perfect execution",
        feedback_points=[],
        refinement_suggestions=[],
    )
    assert r_max.score == 100

    with pytest.raises(ValidationError):
        CriticReview(
            score=-1,
            status="approved",
            summary="Invalid",
            feedback_points=[],
            refinement_suggestions=[],
        )

    with pytest.raises(ValidationError):
        CriticReview(
            score=101,
            status="approved",
            summary="Invalid",
            feedback_points=[],
            refinement_suggestions=[],
        )


def test_critic_review_status_literal():
    """Verify status must match expected literal options."""
    with pytest.raises(ValidationError):
        CriticReview(
            score=50,
            status="invalid_status_type",
            summary="Test",
            feedback_points=[],
            refinement_suggestions=[],
        )
