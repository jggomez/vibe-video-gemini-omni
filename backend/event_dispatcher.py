"""Helper to orchestrate FSM loop tracking and WebSocket event generation."""

import logging

logger = logging.getLogger("vibe_video_studio.event_dispatcher")

_AGENT_CREATIVE_DIRECTOR = "creative_director"
_AGENT_PROMPT_ARCHITECT = "prompt_architect"
_AGENT_VIDEO_PRODUCER = "video_producer"
_AGENT_CRITIC = "critic"

_KNOWN_AGENTS = [
    _AGENT_CREATIVE_DIRECTOR,
    _AGENT_PROMPT_ARCHITECT,
    _AGENT_VIDEO_PRODUCER,
    _AGENT_CRITIC,
]

_STATE_KEY = {
    _AGENT_CREATIVE_DIRECTOR: "creative_director_review",
    _AGENT_PROMPT_ARCHITECT: "optimized_prompt",
    _AGENT_VIDEO_PRODUCER: "production_result",
    _AGENT_CRITIC: "critic_review",
}


class StudioEventDispatcher:
    """Dispatches ADK sub-agent events to the WebSocket client.

    ADK LoopAgent emits ALL sub-agent events with is_final=True and potentially
    out of execution order. This dispatcher:
    1. Tracks which outputs have changed since the turn started.
    2. Emits agent_thinking + agent_done immediately when a new output is detected.
    3. Tracks iteration boundaries by detecting creative_director repeats.
    4. Sends the final turn_complete event.
    """

    def __init__(self, websocket, session_id: str, user_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.user_id = user_id

        self.iteration_count = 1
        # Per-iteration dedup: set of "agent_iterN" strings already emitted
        self._done_sent: set[str] = set()
        self._thinking_sent: set[str] = set()
        # Snapshot of state at turn start — detect fresh outputs
        self._baseline: dict[str, object] = {}
        # Track which agents we've seen per iteration for boundary detection
        self._agents_this_iter: set[str] = set()

    def initialize_turn(self, session_state: dict):
        """Snapshot state at turn start so we can detect new outputs later."""
        self._baseline = {a: session_state.get(k) for a, k in _STATE_KEY.items()}
        self.iteration_count = 1
        self._done_sent.clear()
        self._thinking_sent.clear()
        self._agents_this_iter.clear()

    def _is_new_output(self, agent: str, state: dict) -> bool:
        """Return True if the agent produced meaningful new output since turn start.

        Treats None and '' as equivalent 'no output yet' values, since state
        is initialized with empty strings for ADK template injection compatibility.
        """
        current = state.get(_STATE_KEY[agent])
        baseline = self._baseline.get(agent)
        if not current:  # None, "", {}, [] — no output
            return False
        if not baseline:  # baseline was empty/None, current has value
            return True
        return current != baseline


    def _detect_iteration_boundary(self, agent: str) -> None:
        """Increment iteration counter when creative_director fires again in a new loop."""
        if agent == _AGENT_CREATIVE_DIRECTOR and _AGENT_CREATIVE_DIRECTOR in self._agents_this_iter:
            self.iteration_count += 1
            self._agents_this_iter.clear()
            logger.info("[dispatcher] New iteration: %d", self.iteration_count)

    async def handle_event(self, event_author: str, current_turn_num: int, state: dict, is_final: bool = False):
        """Process one ADK event. Emit thinking+done if this agent has new output.

        ADK emits events out of order — a creative_director final event can arrive
        AFTER video_producer has already run. We use is_final=True to force-send
        agent_done with the current state, bypassing stale dedup checks.
        """
        if event_author not in _KNOWN_AGENTS:
            return

        self._detect_iteration_boundary(event_author)
        self._agents_this_iter.add(event_author)

        has_new = self._is_new_output(event_author, state)
        done_key = f"{event_author}_{self.iteration_count}"
        think_key = done_key

        # On is_final=True: force-send agent_done even if dedup key was already seen,
        # because ADK may have emitted an earlier non-final event before state was ready.
        force_send = is_final and has_new

        if not has_new and not force_send:
            # Emit thinking at minimum so the user sees the agent is active
            if think_key not in self._thinking_sent:
                self._thinking_sent.add(think_key)
                await self.websocket.send_json({
                    "step": "agent_thinking",
                    "agent": event_author,
                    "iteration": self.iteration_count,
                    "current_turn": current_turn_num,
                })
            return

        # Send thinking first (once per agent per iteration)
        if think_key not in self._thinking_sent:
            self._thinking_sent.add(think_key)
            await self.websocket.send_json({
                "step": "agent_thinking",
                "agent": event_author,
                "iteration": self.iteration_count,
                "current_turn": current_turn_num,
            })

        # Send done — allow re-send on is_final if state changed since first send
        if done_key not in self._done_sent or force_send:
            self._done_sent.add(done_key)
            output = state.get(_STATE_KEY[event_author])
            # Update baseline so next iteration detects changes correctly
            self._baseline[event_author] = output

            payload: dict = {
                "step": "agent_done",
                "agent": event_author,
                "iteration": self.iteration_count,
                "current_turn": current_turn_num,
            }
            if event_author == _AGENT_CREATIVE_DIRECTOR:
                payload["creative_director_review"] = output
            elif event_author == _AGENT_PROMPT_ARCHITECT:
                payload["optimized_prompt"] = output
            elif event_author == _AGENT_VIDEO_PRODUCER:
                payload["production_result"] = output
                payload["artifact_name"] = state.get("last_artifact_name", "")
            elif event_author == _AGENT_CRITIC:
                payload["critic_review"] = output

            payload.update(self._get_token_metadata(state))
            await self.websocket.send_json(payload)
            logger.info("[dispatcher] agent_done sent: %s iter=%d final=%s", event_author, self.iteration_count, is_final)


    async def finalize_turn(self, final_text: str, current_turn_num: int, state: dict):
        """Send turn_complete with all collected metadata."""
        payload = {
            "step": "turn_complete",
            "session_id": self.session_id,
            "user_id": self.user_id,
            "current_turn": current_turn_num,
            "iteration": self.iteration_count,
            "output": final_text,
            "artifact_name": state.get("last_artifact_name", ""),
            "interaction_id": state.get("last_interaction_id", ""),
            "creative_director_review": state.get("creative_director_review"),
            "optimized_prompt": state.get("optimized_prompt", ""),
            "production_result": state.get("production_result"),
            "critic_review": state.get("critic_review"),
        }
        payload.update(self._get_token_metadata(state))
        await self.websocket.send_json(payload)
        logger.info("[dispatcher] turn_complete. turn=%d iters=%d", current_turn_num, self.iteration_count)

    def _get_token_metadata(self, state: dict) -> dict:
        dir_in = state.get("creative_director_input_tokens", 0) or 0
        dir_out = state.get("creative_director_output_tokens", 0) or 0
        p_arch_in = state.get("prompt_architect_input_tokens", 0) or 0
        p_arch_out = state.get("prompt_architect_output_tokens", 0) or 0
        prod_in = state.get("video_producer_input_tokens", 0) or 0
        prod_out = state.get("video_producer_output_tokens", 0) or 0
        critic_in = state.get("critic_input_tokens", 0) or 0
        critic_out = state.get("critic_output_tokens", 0) or 0
        v_gen_in = state.get("video_gen_input_tokens", 0) or 0
        v_gen_out = state.get("video_gen_output_tokens", 0) or 0
        duration_secs = state.get("target_duration_secs", 5.0) or 5.0

        input_tokens = dir_in + p_arch_in + prod_in + critic_in + v_gen_in
        text_output_tokens = dir_out + p_arch_out + prod_out + critic_out
        input_cost = (input_tokens / 1_000_000) * 1.50
        text_output_cost = (text_output_tokens / 1_000_000) * 9.00
        video_output_cost = duration_secs * 0.10
        total_cost = input_cost + text_output_cost + video_output_cost

        return {
            "token_metadata": {
                "input_tokens": input_tokens,
                "text_output_tokens": text_output_tokens,
                "video_output_seconds": duration_secs,
                "video_gen_input_tokens": v_gen_in,
                "video_gen_output_tokens": v_gen_out,
                "prompt_architect_input_tokens": p_arch_in,
                "prompt_architect_output_tokens": p_arch_out,
                "video_producer_input_tokens": prod_in,
                "video_producer_output_tokens": prod_out,
                "critic_input_tokens": critic_in,
                "critic_output_tokens": critic_out,
                "total_tokens": input_tokens + text_output_tokens,
                "input_cost": round(input_cost, 6),
                "text_output_cost": round(text_output_cost, 6),
                "video_output_cost": round(video_output_cost, 6),
                "total_cost": round(total_cost, 6),
            }
        }
