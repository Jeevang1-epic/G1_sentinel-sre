from typing import List, Dict
from pydantic import Field
from openenv.core.env_server import Action, Observation, State # pyright: ignore[reportMissingImports]

class SREAction(Action):
    """The command the SRE agent wants to execute."""
    command: str = Field(
        description=(
            "The action to take: 'read_log', 'restart_service', 'check_health', or 'noop'."
        )
    )
    target: str = Field(default="", description="The target of the command (e.g., 'web-api', '192.168.1.50', 'db-migration'). Leave empty if not applicable.")

class SREObservation(Observation):
    """What the agent sees after taking an action."""
    task_id: str = Field(description="Stable task identifier for the active scenario")
    task_name: str = Field(description="Human-readable task name")
    task_difficulty: str = Field(description="Task difficulty tier: easy, medium, hard")
    system_health: float = Field(description="Overall health score of the system (0.0 to 1.0)")
    active_alerts: List[str] = Field(description="List of active PagerDuty-style alerts")
    terminal_output: str = Field(description="The stdout/stderr result of the last executed command")
    attempts_remaining: int = Field(description="Number of actions left before the system completely crashes")

class SREState(State):
    """The hidden state of the environment used for tracking and grading."""
    episode_id: str
    step_count: int
    task_id: str = Field(description="Stable task identifier for the active scenario")
    task_name: str = Field(description="Human-readable task name")
    task_difficulty: str = Field(description="The current difficulty level: 'easy', 'medium', or 'hard'")
    task_description: str = Field(description="Detailed enterprise incident scenario description")
    sla_target_steps: int = Field(default=5, description="Target number of steps to meet SLA for this scenario")
    grader_id: str = Field(description="Programmatic grader ID attached to this scenario")
    incident_briefing: str = Field(description="Initial incident context for this episode")
    services_status: Dict[str, str] = Field(description="Hidden status of microservices (e.g., 'running', 'crashed', 'degraded')")
    resolved: bool = Field(default=False, description="True if the root cause of the alert has been fixed")
