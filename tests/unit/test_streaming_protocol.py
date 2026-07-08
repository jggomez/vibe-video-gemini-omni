"""Unit tests for main.py WebSocket streaming protocol and iteration tracking.

Tests the iteration boundary detection, done_sent/thinking_sent deduplication,
and per-agent state management logic extracted from the WebSocket handler.
No real ADK or Gemini API calls are made.
"""

from unittest.mock import MagicMock

# ── Constants matching main.py ─────────────────────────────────────────────────
_AGENT_PROMPT_ARCHITECT = "prompt_architect"
_AGENT_VIDEO_PRODUCER = "video_producer"
_AGENT_CRITIC = "critic"
_KNOWN_AGENTS = {_AGENT_PROMPT_ARCHITECT, _AGENT_VIDEO_PRODUCER, _AGENT_CRITIC}


# ── Helpers ────────────────────────────────────────────────────────────────────
def _make_session(state: dict) -> MagicMock:
    """Build a minimal session mock that supports .state dict operations."""
    session = MagicMock()
    session.state = dict(state)
    session.id = "test-session-id"
    return session


# ── Core iteration tracking FSM (re-implemented from main.py for unit testing) ─
def simulate_iteration_tracking(event_authors: list, state_by_event: list) -> list:
    """Re-implements the main.py iteration-tracking FSM using last_seen_values.

    Args:
        event_authors: Ordered list of author strings (e.g. ["prompt_architect", ...]).
        state_by_event: Corresponding session state dict for each event.

    Returns:
        List of websocket payload dicts that would be sent by the handler.
    """
    iteration_count = 0
    agents_seen_in_loop: set = set()
    thinking_sent: set = set()
    done_sent: set = set()
    sent_payloads: list = []

    last_seen_values = {
        _AGENT_PROMPT_ARCHITECT: None,
        _AGENT_VIDEO_PRODUCER: None,
        _AGENT_CRITIC: None,
    }

    for idx, event_author in enumerate(event_authors):
        state = dict(state_by_event[idx])

        # ── Iteration boundary detection ──────────────────────────────────────
        if event_author == _AGENT_PROMPT_ARCHITECT:
            if _AGENT_CRITIC in agents_seen_in_loop:
                # Critic already completed a round → new loop iteration begins
                iteration_count += 1
                agents_seen_in_loop = set()
                thinking_sent = set()
                done_sent = set()
                # Reset last_seen_values to current state values to prevent treating stale values as fresh
                last_seen_values = {
                    _AGENT_PROMPT_ARCHITECT: state.get("optimized_prompt"),
                    _AGENT_VIDEO_PRODUCER: state.get("production_result"),
                    _AGENT_CRITIC: state.get("critic_review"),
                }
            elif iteration_count == 0:
                # Very first architect event → start iteration 1
                iteration_count = 1
                agents_seen_in_loop = set()

        if event_author in _KNOWN_AGENTS:
            agents_seen_in_loop.add(event_author)

        # ── Route event ───────────────────────────────────────────────────────
        if event_author not in _KNOWN_AGENTS:
            continue

        iter_key = f"{event_author}_{iteration_count}"

        raw_output = None
        if event_author == _AGENT_PROMPT_ARCHITECT:
            raw_output = state.get("optimized_prompt")
        elif event_author == _AGENT_VIDEO_PRODUCER:
            raw_output = state.get("production_result")
        elif event_author == _AGENT_CRITIC:
            raw_output = state.get("critic_review")

        agent_output = (
            raw_output
            if raw_output is not None and raw_output != last_seen_values.get(event_author)
            else None
        )

        if agent_output is not None and iter_key not in done_sent:
            done_sent.add(iter_key)
            last_seen_values[event_author] = agent_output
            thinking_sent.discard(event_author)
            sent_payloads.append({
                "step": "agent_done",
                "agent": event_author,
                "iteration": iteration_count or 1,
            })
        elif agent_output is None and event_author not in thinking_sent:
            thinking_sent.add(event_author)
            sent_payloads.append({
                "step": "agent_thinking",
                "agent": event_author,
                "iteration": iteration_count or 1,
            })

    return sent_payloads


# ── Test 1: Single iteration approve path ──────────────────────────────────────
def test_single_iteration_approve_path():
    """Architect→Producer→Critic(approve): 3 thinking + 3 done, all iteration=1."""
    authors = [
        _AGENT_PROMPT_ARCHITECT,  # thinking (no output yet)
        _AGENT_PROMPT_ARCHITECT,  # done (optimized_prompt ready)
        _AGENT_VIDEO_PRODUCER,    # thinking
        _AGENT_VIDEO_PRODUCER,    # done (production_result ready)
        _AGENT_CRITIC,            # thinking
        _AGENT_CRITIC,            # done (critic_review=approved)
    ]
    states = [
        {},
        {"optimized_prompt": "A cinematic wide shot..."},
        {"optimized_prompt": "A cinematic wide shot..."},
        {"optimized_prompt": "A cinematic wide shot...", "production_result": {"status": "success"}},
        {"optimized_prompt": "A cinematic wide shot...", "production_result": {"status": "success"}},
        {
            "optimized_prompt": "A cinematic wide shot...",
            "production_result": {"status": "success"},
            "critic_review": {"status": "approved", "score": 90},
        },
    ]

    payloads = simulate_iteration_tracking(authors, states)
    thinking = [p for p in payloads if p["step"] == "agent_thinking"]
    done = [p for p in payloads if p["step"] == "agent_done"]

    assert len(thinking) == 3, f"Expected 3 thinking events, got {len(thinking)}"
    assert len(done) == 3, f"Expected 3 done events, got {len(done)}"
    for p in payloads:
        assert p["iteration"] == 1, f"All iter should be 1 in single-loop, got: {p}"


# ── Test 2: Two iterations (reject → approve) ──────────────────────────────────
def test_two_iteration_reject_approve():
    """iteration_count correctly goes 1 → 2 when critic rejects on first pass."""
    authors = [
        # Iteration 1
        _AGENT_PROMPT_ARCHITECT,
        _AGENT_PROMPT_ARCHITECT,
        _AGENT_VIDEO_PRODUCER,
        _AGENT_VIDEO_PRODUCER,
        _AGENT_CRITIC,
        _AGENT_CRITIC,
        # Iteration 2 (critic rejected, loop continues)
        _AGENT_PROMPT_ARCHITECT,  # boundary: iteration_count 1→2
        _AGENT_PROMPT_ARCHITECT,
        _AGENT_VIDEO_PRODUCER,
        _AGENT_VIDEO_PRODUCER,
        _AGENT_CRITIC,
        _AGENT_CRITIC,
    ]
    states = [
        # Iter 1
        {},
        {"optimized_prompt": "Prompt v1"},
        {"optimized_prompt": "Prompt v1"},
        {"optimized_prompt": "Prompt v1", "production_result": {"status": "success"}},
        {"optimized_prompt": "Prompt v1", "production_result": {"status": "success"}},
        {
            "optimized_prompt": "Prompt v1",
            "production_result": {"status": "success"},
            "critic_review": {"status": "needs_refinement", "score": 60},
        },
        # Iter 2 — FSM clears stale state at boundary
        {},
        {"optimized_prompt": "Prompt v2"},
        {"optimized_prompt": "Prompt v2"},
        {"optimized_prompt": "Prompt v2", "production_result": {"status": "success"}},
        {"optimized_prompt": "Prompt v2", "production_result": {"status": "success"}},
        {
            "optimized_prompt": "Prompt v2",
            "production_result": {"status": "success"},
            "critic_review": {"status": "approved", "score": 88},
        },
    ]

    payloads = simulate_iteration_tracking(authors, states)
    iter1 = [p for p in payloads if p["iteration"] == 1]
    iter2 = [p for p in payloads if p["iteration"] == 2]

    assert len(iter1) == 6, f"Iter 1: expected 6 events, got {len(iter1)}"
    assert len(iter2) == 6, f"Iter 2: expected 6 events, got {len(iter2)}"
    assert {p["agent"] for p in iter2} == _KNOWN_AGENTS


# ── Test 3: done_sent prevents duplicate agent_done ────────────────────────────
def test_done_sent_deduplication_prevents_double_events():
    """Same agent+iteration with output in state must only emit ONE done event."""
    authors = [
        _AGENT_PROMPT_ARCHITECT,  # thinking (no output)
        _AGENT_PROMPT_ARCHITECT,  # done
        _AGENT_PROMPT_ARCHITECT,  # duplicate firing — must be suppressed
    ]
    states = [
        {},
        {"optimized_prompt": "Prompt v1"},
        {"optimized_prompt": "Prompt v1"},  # iter_key already in done_sent
    ]

    payloads = simulate_iteration_tracking(authors, states)
    done = [p for p in payloads if p["step"] == "agent_done" and p["agent"] == _AGENT_PROMPT_ARCHITECT]
    assert len(done) == 1, f"done_sent must deduplicate; expected 1 done, got {len(done)}"


# ── Test 4: thinking_sent prevents duplicate agent_thinking ────────────────────
def test_thinking_sent_deduplication_prevents_double_thinking():
    """Same agent within an iteration must only emit ONE thinking event."""
    authors = [
        _AGENT_PROMPT_ARCHITECT,  # thinking (sent)
        _AGENT_PROMPT_ARCHITECT,  # no output — thinking already sent → suppress
        _AGENT_PROMPT_ARCHITECT,  # no output — suppress again
        _AGENT_PROMPT_ARCHITECT,  # done
    ]
    states = [
        {},
        {},
        {},
        {"optimized_prompt": "Prompt v1"},
    ]

    payloads = simulate_iteration_tracking(authors, states)
    thinking = [p for p in payloads if p["step"] == "agent_thinking" and p["agent"] == _AGENT_PROMPT_ARCHITECT]
    assert len(thinking) == 1, f"thinking_sent must deduplicate; expected 1, got {len(thinking)}"


# ── Test 5: Iteration boundary clears stale output state ──────────────────────
def test_iteration_boundary_clears_stale_output():
    """After critic rejects and iteration resets, stale optimized_prompt in DB must
    NOT trigger premature agent_done for the new iteration's architect thinking phase."""
    authors = [
        # Iter 1
        _AGENT_PROMPT_ARCHITECT,
        _AGENT_PROMPT_ARCHITECT,  # done
        _AGENT_CRITIC,
        _AGENT_CRITIC,            # done (needs_refinement)
        # Iter 2 — architect fires while DB still has old optimized_prompt
        _AGENT_PROMPT_ARCHITECT,  # boundary clears state → must emit thinking, NOT done
    ]
    states = [
        {},
        {"optimized_prompt": "Prompt v1"},
        {"optimized_prompt": "Prompt v1"},
        {"optimized_prompt": "Prompt v1", "critic_review": {"status": "needs_refinement", "score": 50}},
        # Stale: DB not yet updated by new architect run
        {"optimized_prompt": "Prompt v1", "critic_review": {"status": "needs_refinement", "score": 50}},
    ]

    payloads = simulate_iteration_tracking(authors, states)
    iter2 = [p for p in payloads if p["iteration"] == 2]

    assert len(iter2) >= 1, "Iter 2 must have at least one event"
    assert iter2[0]["step"] == "agent_thinking", (
        "Iteration boundary must clear stale optimized_prompt so first iter-2 "
        f"architect event is agent_thinking, got: {iter2[0]['step']}"
    )
    assert iter2[0]["agent"] == _AGENT_PROMPT_ARCHITECT


# ── Test 6: Unknown authors are silently ignored ───────────────────────────────
def test_unknown_author_events_ignored():
    """Events from unknown authors (orchestrator, pipeline) must not emit any step."""
    authors = [
        "pipeline",            # ignored
        "vibe_video_pipeline", # ignored
        _AGENT_PROMPT_ARCHITECT,
        _AGENT_PROMPT_ARCHITECT,
    ]
    states = [
        {},
        {},
        {},
        {"optimized_prompt": "Prompt v1"},
    ]

    payloads = simulate_iteration_tracking(authors, states)
    non_architect = [p for p in payloads if p["agent"] != _AGENT_PROMPT_ARCHITECT]
    assert len(non_architect) == 0, f"Unknown authors must produce no events; got: {non_architect}"
