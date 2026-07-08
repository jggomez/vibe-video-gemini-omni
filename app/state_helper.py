"""Helper to encapsulate tool context state dictionary keys to prevent primitive obsession."""


class StudioSessionState:
    """Type-safe wrapper for ADK tool_context.state to prevent magic string typos."""

    def __init__(self, state_dict: dict):
        self._state = state_dict

    @property
    def last_interaction_id(self) -> str:
        return self._state.get("last_interaction_id", "")

    @last_interaction_id.setter
    def last_interaction_id(self, val: str) -> None:
        self._state["last_interaction_id"] = val

    @property
    def last_artifact_name(self) -> str:
        return self._state.get("last_artifact_name", "")

    @last_artifact_name.setter
    def last_artifact_name(self, val: str) -> None:
        self._state["last_artifact_name"] = val

    @property
    def current_turn(self) -> int:
        return self._state.get("current_turn", 1)

    @current_turn.setter
    def current_turn(self, val: int) -> None:
        self._state["current_turn"] = val

    @property
    def production_result(self) -> dict | None:
        return self._state.get("production_result")

    @production_result.setter
    def production_result(self, val: dict | None) -> None:
        self._state["production_result"] = val
