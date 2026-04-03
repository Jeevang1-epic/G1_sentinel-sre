from typing import Dict, Any
from openenv.core.env_client import EnvClient # pyright: ignore[reportMissingImports]
from openenv.core.client_types import StepResult # pyright: ignore[reportMissingImports]
from models import SREAction, SREObservation, SREState

class SentinelSREClient(EnvClient[SREAction, SREObservation, SREState]):
    def _step_payload(self, action: SREAction) -> Dict[str, Any]:
        return {
            "command": action.command,
            "target": action.target
        }

    def _parse_result(self, payload: Dict[str, Any]) -> StepResult:
        obs_data = payload.get("observation", {})
        
        observation = SREObservation(
            system_health=obs_data.get("system_health", 0.0),
            active_alerts=obs_data.get("active_alerts", []),
            terminal_output=obs_data.get("terminal_output", ""),
            attempts_remaining=obs_data.get("attempts_remaining", 0)
        )
        
        return StepResult(
            observation=observation,
            reward=payload.get("reward", 0.0),
            done=payload.get("done", False)
        )

    def _parse_state(self, payload: Dict[str, Any]) -> SREState:
        return SREState(
            episode_id=payload.get("episode_id", ""),
            step_count=payload.get("step_count", 0),
            task_difficulty=payload.get("task_difficulty", "easy"),
            services_status=payload.get("services_status", {}),
            resolved=payload.get("resolved", False)
        )