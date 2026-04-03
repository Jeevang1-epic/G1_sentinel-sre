import random
import uuid
from openenv.core.env_server import Environment
from models import SREAction, SREObservation, SREState

class SentinelSREEnvironment(Environment):
    def __init__(self):
        self._state = None
        self.max_attempts = 10

    def reset(self, **kwargs) -> SREObservation:
        tasks = ["easy", "medium", "hard"]
        task = random.choice(tasks)
        
        services = {
            "web-api": "running",
            "auth-db": "running",
            "payment-gateway": "running"
        }
        alerts = []
        
        if task == "easy":
            services["web-api"] = "crashed"
            alerts.append("CRITICAL: web-api is down (502 Bad Gateway)")
        elif task == "medium":
            services["auth-db"] = "degraded"
            alerts.append("WARN: auth-db high latency detected")
        else:
            services["payment-gateway"] = "crashed"
            services["web-api"] = "degraded"
            alerts.append("CRITICAL: payment-gateway offline")
            alerts.append("WARN: web-api cascading failure")

        self._state = SREState(
            episode_id=str(uuid.uuid4()),
            step_count=0,
            task_difficulty=task,
            services_status=services,
            resolved=False
        )
        
        return self._generate_obs("System reset. Awaiting SRE intervention.", reward=0.0, done=False)

    def step(self, action: SREAction, **kwargs) -> SREObservation:
        self._state.step_count += 1
        cmd = action.command
        target = action.target
        output = ""
        reward = 0.0
        
        if cmd == "restart_service":
            if target in self._state.services_status:
                if self._state.services_status[target] != "running":
                    self._state.services_status[target] = "running"
                    output = f"SUCCESS: Service '{target}' restarted."
                    reward += 0.5
                else:
                    output = f"INFO: Service '{target}' already running."
                    reward -= 0.1
            else:
                output = f"ERROR: Service '{target}' not found."
                reward -= 0.1
        elif cmd == "check_health":
            output = f"HEALTH REPORT: {self._state.services_status}"
        elif cmd == "noop":
            output = "Idled for 1 cycle."
        else:
            output = f"ERROR: Unknown command '{cmd}'."
            reward -= 0.2

        all_running = all(status == "running" for status in self._state.services_status.values())
        done = False
        
        if all_running:
            self._state.resolved = True
            done = True
            reward = 1.0
            output += "\nINCIDENT RESOLVED."
        elif self._state.step_count >= self.max_attempts:
            done = True
            reward = -1.0
            output += "\nCRITICAL FAILURE: System crashed."

        return self._generate_obs(output, reward, done)

    def _generate_obs(self, terminal_output: str, reward: float, done: bool) -> SREObservation:
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
            system_health=health,
            active_alerts=current_alerts,
            terminal_output=terminal_output,
            attempts_remaining=self.max_attempts - self._state.step_count,
            reward=reward,
            done=done
        )

    @property
    def state(self) -> SREState:
        return self._state