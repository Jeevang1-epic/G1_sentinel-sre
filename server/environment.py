import uuid
import threading
import hashlib
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from openenv.core.env_server import Environment
from openenv.core.env_server.types import EnvironmentMetadata

from models import SREAction, SREObservation, SREState


@dataclass(frozen=True)
class TaskScenario:
    task_id: str
    grader_id: str
    name: str
    difficulty: str
    description: str
    initial_services: Dict[str, str]
    sla_target_steps: int
    briefing: str

class SentinelSREEnvironment(Environment):
    # Global reset cursor so task coverage works even if each HTTP request creates
    # a fresh environment instance.
    _global_reset_counter = 0
    _global_reset_lock = threading.Lock()

    TASK_SCENARIOS = (
        TaskScenario(
            task_id="api-recovery-easy",
            grader_id="grader-api-recovery-easy-v1",
            name="API Tier Outage Recovery",
            difficulty="easy",
            description=(
                "Single-service outage in the request path. Restore web traffic by "
                "recovering the edge API process before SLA error budget is exhausted."
            ),
            initial_services={
                "web-api": "crashed",
                "auth-db": "running",
                "payment-gateway": "running",
            },
            sla_target_steps=3,
            briefing=(
                "P1 Incident: HTTP 502 spike detected. Synthetic probes report web-api "
                "hard down while dependencies are healthy."
            ),
        ),
        TaskScenario(
            task_id="auth-latency-medium",
            grader_id="grader-auth-latency-medium-v1",
            name="Authentication Latency Containment",
            difficulty="medium",
            description=(
                "Database tier degradation is causing elevated p99 auth latency. "
                "Mitigate before downstream services inherit retry storms."
            ),
            initial_services={
                "web-api": "running",
                "auth-db": "degraded",
                "payment-gateway": "running",
            },
            sla_target_steps=4,
            briefing=(
                "P2 Incident: auth-db latency breach at p99 > 2.5s. Login success "
                "rate trending downward with growing queue depth."
            ),
        ),
        TaskScenario(
            task_id="payment-cascade-hard",
            grader_id="grader-payment-cascade-hard-v1",
            name="Payment Cascade Stabilization",
            difficulty="hard",
            description=(
                "Multi-service cascading incident with a hard payment outage and "
                "degraded API dependencies. Execute triage quickly to avoid systemic failure."
            ),
            initial_services={
                "web-api": "degraded",
                "auth-db": "running",
                "payment-gateway": "crashed",
            },
            sla_target_steps=5,
            briefing=(
                "P1 Incident: payment-gateway offline with collateral degradation in "
                "web-api. Revenue path is interrupted and customer impact is active."
            ),
        ),
    )

    def __init__(self):
        super().__init__()
        self._state = None
        self.max_attempts = 10
        self._scenario_by_id = {scenario.task_id: scenario for scenario in self.TASK_SCENARIOS}
        self._task_graders: Dict[str, Callable[[str, bool], float]] = {
            "api-recovery-easy": self._grade_easy,
            "auth-latency-medium": self._grade_medium,
            "payment-cascade-hard": self._grade_hard,
        }
        self._status_weights = {"running": 1.0, "degraded": 0.55, "crashed": 0.15}

    @staticmethod
    def _clamp_exclusive(score: float) -> float:
        lower = 0.01
        upper = 0.99
        if score <= lower:
            return lower
        if score >= upper:
            return upper
        return score

    @staticmethod
    def _health_ratio(services_status: Dict[str, str]) -> float:
        total = len(services_status)
        if total == 0:
            return 0.0
        running = sum(1 for status in services_status.values() if status == "running")
        return running / total

    def _service_status_score(self, services_status: Dict[str, str]) -> float:
        total = len(services_status)
        if total == 0:
            return 0.0
        weighted = sum(self._status_weights.get(status, 0.0) for status in services_status.values())
        return weighted / total

    def _task_profile(self, task_id: str) -> Dict[str, float]:
        profile = {
            "api-recovery-easy": {
                "status_weight": 0.50,
                "efficiency_weight": 0.26,
                "resolve_fast_bonus": 0.18,
                "resolve_slow_bonus": 0.10,
            },
            "auth-latency-medium": {
                "status_weight": 0.52,
                "efficiency_weight": 0.24,
                "resolve_fast_bonus": 0.16,
                "resolve_slow_bonus": 0.09,
            },
            "payment-cascade-hard": {
                "status_weight": 0.56,
                "efficiency_weight": 0.22,
                "resolve_fast_bonus": 0.15,
                "resolve_slow_bonus": 0.08,
            },
        }
        return profile.get(task_id, profile["auth-latency-medium"])

    def _shared_grading_core(self, action_outcome: str, done: bool, task_id: str) -> float:
        status_score = self._service_status_score(self._state.services_status)
        attempts_used = self._state.step_count
        attempts_remaining_ratio = max(0.0, (self.max_attempts - attempts_used) / self.max_attempts)

        action_quality = {
            "restart_success": 0.20,
            "restart_redundant": 0.03,
            "restart_missing": 0.01,
            "read_log": 0.09,
            "check_health": 0.07,
            "noop": 0.03,
            "unknown_command": 0.01,
        }.get(action_outcome, 0.01)

        profile = self._task_profile(task_id)
        base_score = (status_score * profile["status_weight"]) + (
            attempts_remaining_ratio * profile["efficiency_weight"]
        ) + action_quality

        if all(status == "running" for status in self._state.services_status.values()):
            self._state.resolved = True
            sla_bonus = (
                profile["resolve_fast_bonus"]
                if attempts_used <= self._state.sla_target_steps
                else profile["resolve_slow_bonus"]
            )
            base_score += sla_bonus

        if done and not self._state.resolved:
            base_score *= 0.45

        return self._clamp_exclusive(base_score)

    def _grade_easy(self, action_outcome: str, done: bool) -> float:
        return self._shared_grading_core(
            action_outcome=action_outcome,
            done=done,
            task_id="api-recovery-easy",
        )

    def _grade_medium(self, action_outcome: str, done: bool) -> float:
        return self._shared_grading_core(
            action_outcome=action_outcome,
            done=done,
            task_id="auth-latency-medium",
        )

    def _grade_hard(self, action_outcome: str, done: bool) -> float:
        return self._shared_grading_core(
            action_outcome=action_outcome,
            done=done,
            task_id="payment-cascade-hard",
        )

    def _select_scenario(
        self,
        requested_task_id: str,
        seed: Optional[int],
        episode_id: Optional[str],
    ) -> TaskScenario:
        if requested_task_id and requested_task_id in self._scenario_by_id:
            return self._scenario_by_id[requested_task_id]

        if seed is not None:
            index = seed % len(self.TASK_SCENARIOS)
            return self.TASK_SCENARIOS[index]

        if episode_id:
            digest = hashlib.sha256(episode_id.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % len(self.TASK_SCENARIOS)
            return self.TASK_SCENARIOS[index]

        with SentinelSREEnvironment._global_reset_lock:
            index = SentinelSREEnvironment._global_reset_counter % len(self.TASK_SCENARIOS)
            SentinelSREEnvironment._global_reset_counter += 1
        return self.TASK_SCENARIOS[index]

    def _apply_task_escalation(self) -> str:
        escalation_events = []

        if self._state.task_id == "auth-latency-medium":
            if (
                self._state.services_status.get("auth-db") == "degraded"
                and self._state.step_count >= 3
                and self._state.services_status.get("web-api") == "running"
            ):
                self._state.services_status["web-api"] = "degraded"
                escalation_events.append(
                    "ESCALATION: retry storm propagated to web-api latency."
                )

        if self._state.task_id == "payment-cascade-hard":
            if (
                self._state.services_status.get("payment-gateway") == "crashed"
                and self._state.step_count >= 2
                and self._state.services_status.get("auth-db") == "running"
            ):
                self._state.services_status["auth-db"] = "degraded"
                escalation_events.append(
                    "ESCALATION: auth-db degraded due to payment backlog pressure."
                )
            if (
                self._state.services_status.get("payment-gateway") == "crashed"
                and self._state.step_count >= 4
                and self._state.services_status.get("web-api") == "degraded"
            ):
                self._state.services_status["web-api"] = "crashed"
                escalation_events.append(
                    "ESCALATION: web-api moved from degraded to crashed."
                )

        return "\n".join(escalation_events)

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs,
    ) -> SREObservation:
        requested_task_id = kwargs.get("task_id")
        scenario = self._select_scenario(
            requested_task_id=requested_task_id,
            seed=seed,
            episode_id=episode_id,
        )

        self._state = SREState(
            episode_id=episode_id or str(uuid.uuid4()),
            step_count=0,
            task_id=scenario.task_id,
            task_name=scenario.name,
            task_difficulty=scenario.difficulty,
            task_description=scenario.description,
            incident_briefing=scenario.briefing,
            grader_id=scenario.grader_id,
            services_status=dict(scenario.initial_services),
            resolved=False,
            sla_target_steps=scenario.sla_target_steps,
        )

        return self._generate_obs(
            (
                f"System reset for task '{scenario.name}'. "
                f"{scenario.briefing} Execute incident triage and remediation."
            ),
            reward=0.01,
            done=False,
        )

    def step(self, action: SREAction, **kwargs) -> SREObservation:
        if self._state is None:
            return self._generate_obs(
                "ERROR: Environment state missing. Call reset() before step().",
                reward=0.01,
                done=True,
            )

        self._state.step_count += 1
        cmd = action.command.strip().lower()
        target = action.target.strip().lower()
        output = ""
        action_outcome = "unknown_command"

        if cmd == "restart_service":
            if target in self._state.services_status:
                if self._state.services_status[target] != "running":
                    self._state.services_status[target] = "running"
                    output = f"SUCCESS: Service '{target}' restarted."
                    action_outcome = "restart_success"
                else:
                    output = f"INFO: Service '{target}' already running."
                    action_outcome = "restart_redundant"
            else:
                output = f"ERROR: Service '{target}' not found."
                action_outcome = "restart_missing"
        elif cmd == "read_log":
            output = f"LOG SNAPSHOT: Active status map {self._state.services_status}"
            action_outcome = "read_log"
        elif cmd == "check_health":
            output = f"HEALTH REPORT: {self._state.services_status}"
            action_outcome = "check_health"
        elif cmd == "noop":
            output = "Idled for 1 cycle."
            action_outcome = "noop"
        else:
            output = f"ERROR: Unknown command '{cmd}'."

        escalation_note = self._apply_task_escalation()
        if escalation_note:
            output += f"\n{escalation_note}"

        all_running = all(status == "running" for status in self._state.services_status.values())
        done = False

        if all_running:
            self._state.resolved = True
            done = True
            output += "\nINCIDENT RESOLVED."
        elif self._state.step_count >= self.max_attempts:
            done = True
            output += "\nSLA BREACH: Remediation window exhausted."

        grader = self._task_graders.get(self._state.task_id, self._grade_medium)
        reward = grader(action_outcome, done)

        return self._generate_obs(output, reward, done)

    def _generate_obs(self, terminal_output: str, reward: float, done: bool) -> SREObservation:
        if self._state is None:
            return SREObservation(
                task_id="uninitialized",
                task_name="Uninitialized Episode",
                task_difficulty="unknown",
                system_health=0.0,
                active_alerts=[],
                terminal_output=terminal_output,
                attempts_remaining=0,
                reward=self._clamp_exclusive(reward),
                done=done,
                metadata={
                    "task_id": "uninitialized",
                    "grader_id": "uninitialized-grader",
                    "score_bounds": {"exclusive_min": 0.01, "exclusive_max": 0.99},
                },
            )

        total = len(self._state.services_status)
        running = sum(1 for status in self._state.services_status.values() if status == "running")
        health = running / total if total > 0 else 0.0

        current_alerts = []
        for srv, status in self._state.services_status.items():
            if status == "crashed":
                current_alerts.append(f"CRITICAL: {srv} offline")
            elif status == "degraded":
                current_alerts.append(f"WARN: {srv} degraded")

        return SREObservation(
            task_id=self._state.task_id,
            task_name=self._state.task_name,
            task_difficulty=self._state.task_difficulty,
            system_health=health,
            active_alerts=current_alerts,
            terminal_output=terminal_output,
            attempts_remaining=max(0, self.max_attempts - self._state.step_count),
            reward=self._clamp_exclusive(reward),
            done=done,
            metadata={
                "task_id": self._state.task_id,
                "task_name": self._state.task_name,
                "task_difficulty": self._state.task_difficulty,
                "task_description": self._state.task_description,
                "grader_id": self._state.grader_id,
                "score_bounds": {"exclusive_min": 0.01, "exclusive_max": 0.99},
            },
        )

    def get_metadata(self) -> EnvironmentMetadata:
        task_lines = []
        for scenario in self.TASK_SCENARIOS:
            task_lines.append(
                f"{scenario.task_id} [{scenario.difficulty}] -> {scenario.grader_id}"
            )

        return EnvironmentMetadata(
            name="SentinelSREEnvironment",
            description=(
                "OpenEnv SRE incident-response simulator with 3 deterministic tasks "
                "and programmatic graders. Tasks: " + "; ".join(task_lines)
            ),
            version="1.1.0",
            author="Sentinel-SRE Team",
        )

    @property
    def state(self) -> SREState:
        if self._state is None:
            return SREState(
                episode_id="",
                step_count=0,
                task_id="uninitialized",
                task_name="Uninitialized Episode",
                task_difficulty="unknown",
                task_description="Call reset() to initialize an episode.",
                incident_briefing="No incident loaded.",
                sla_target_steps=self.max_attempts,
                grader_id="uninitialized-grader",
                services_status={},
                resolved=False,
            )
        return self._state
