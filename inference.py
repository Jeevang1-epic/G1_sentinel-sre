import os
import textwrap
import asyncio
from typing import List
from openai import OpenAI

from client import SentinelSREClient
from models import SREAction


API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("HF_TOKEN")
ENV_BASE_URL = "https://jeevan-kumar0011-sentinel-sre.hf.space"
TASK_IDS = [
    "api-recovery-easy",
    "auth-latency-medium",
    "payment-cascade-hard",
]
BASE_SEED = int(os.getenv("BASELINE_SEED", "20260408"))
MAX_STEPS = 10
TEMPERATURE = 0.0
MAX_TOKENS = 100

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an elite Site Reliability Engineer (SRE).
    Your goal is to resolve live production incidents by restoring all services to running.
    
    You must reply with exactly ONE command string per turn.
    Valid commands:
    - restart_service <target>
    - check_health
    - read_log
    - noop
    
    Valid targets are strictly the exact service names shown in the alerts (e.g., web-api, auth-db, payment-gateway). DO NOT abbreviate target names.
    Example: restart_service payment-gateway
    
    CRITICAL: Do not include explanations, markdown formatting (no backticks), or conversational text. Output the command ONLY.
    """
).strip()

def _clamp_score(value: float) -> float:
    return max(0.01, min(0.99, value))

def build_user_prompt(step: int, obs, history: List[str]) -> str:
    alerts = ", ".join(obs.active_alerts) if obs.active_alerts else "None"
    hist_text = "\n".join(history[-3:]) if history else "None"
    
    return textwrap.dedent(
        f"""
        Step: {step}
        Task ID: {obs.task_id}
        Task Name: {obs.task_name}
        Difficulty: {obs.task_difficulty}
        System Health: {obs.system_health}
        Active Alerts: {alerts}
        Terminal Output: {obs.terminal_output}
        Recent Actions:
        {hist_text}
        
        What is your next command?
        """
    ).strip()

def _normalize_target(text: str) -> str:
    cleaned = text.strip().lower().replace(",", "").replace(".", "")
    if cleaned in {"payment-gateway", "payment_gateway", "payment"}:
        return "payment-gateway"
    if cleaned in {"web-api", "web_api", "web"}:
        return "web-api"
    if cleaned in {"auth-db", "auth_db", "auth"}:
        return "auth-db"
    return ""

def parse_model_action(response_text: str) -> SREAction:
    text = (response_text or "").strip().lower()
    first_line = text.splitlines()[0] if text else "noop"
    tokens = first_line.split()

    if tokens and tokens[0] == "restart_service":
        target = _normalize_target(tokens[1]) if len(tokens) > 1 else ""
        return SREAction(command="restart_service", target=target)
    if first_line.startswith("check_health"):
        return SREAction(command="check_health", target="")
    if first_line.startswith("read_log"):
        return SREAction(command="read_log", target="")
    if first_line.startswith("noop"):
        return SREAction(command="noop", target="")

    # Fallback parser for non-compliant model output.
    if "restart_service" in text:
        for token in ("payment-gateway", "web-api", "auth-db", "payment", "web", "auth"):
            if token in text:
                return SREAction(command="restart_service", target=_normalize_target(token))
        return SREAction(command="restart_service", target="")
    if "check_health" in text:
        return SREAction(command="check_health", target="")
    if "read_log" in text:
        return SREAction(command="read_log", target="")
    return SREAction(command="noop", target="")

def _heuristic_action(obs) -> SREAction:
    # Prioritize critical service recovery before degraded components.
    for alert in obs.active_alerts:
        lowered = alert.lower()
        if "critical" in lowered and "payment-gateway" in lowered:
            return SREAction(command="restart_service", target="payment-gateway")
        if "critical" in lowered and "web-api" in lowered:
            return SREAction(command="restart_service", target="web-api")
        if "critical" in lowered and "auth-db" in lowered:
            return SREAction(command="restart_service", target="auth-db")

    for alert in obs.active_alerts:
        lowered = alert.lower()
        if "warn" in lowered and "auth-db" in lowered:
            return SREAction(command="restart_service", target="auth-db")
        if "warn" in lowered and "web-api" in lowered:
            return SREAction(command="restart_service", target="web-api")
        if "warn" in lowered and "payment-gateway" in lowered:
            return SREAction(command="restart_service", target="payment-gateway")

    if obs.attempts_remaining >= 8:
        return SREAction(command="read_log", target="")
    return SREAction(command="check_health", target="")

async def run_task(client: OpenAI, env: SentinelSREClient, task_id: str, seed: int) -> float:
    history: List[str] = []
    rewards_history: List[float] = []
    print(f"[TASK_START] task_id={task_id} seed={seed}")
    result = await env.reset(task_id=task_id, seed=seed)
    obs = result.observation
    actual_steps = 0

    for step in range(1, MAX_STEPS + 1):
        if result.done:
            break

        actual_steps = step
        user_prompt = build_user_prompt(step, obs, history)
        response_text = ""
        error_str = "null"

        try:
            completion = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
            response_text = completion.choices[0].message.content or "noop"
        except Exception as exc:
            error_str = type(exc).__name__
            response_text = "noop"

        action = parse_model_action(response_text)
        if action.command == "restart_service" and not action.target:
            action = _heuristic_action(obs)
        if action.command == "noop":
            action = _heuristic_action(obs)

        action_str = (
            f"{action.command}('{action.target}')"
            if action.target
            else f"{action.command}()"
        )
        result = await env.step(action)
        obs = result.observation
        reward = _clamp_score(float(result.reward if result.reward is not None else 0.01))

        history.append(f"Action: {action_str} | Reward: {reward:.4f}")
        rewards_history.append(reward)

        done_str = str(result.done).lower()
        print(
            f"[STEP] task={task_id} step={step} action={action_str} "
            f"reward={reward:.4f} done={done_str} error={error_str}"
        )

    current_state = await env.state()
    success_str = str(current_state.resolved).lower()
    rewards_str = ",".join(f"{r:.4f}" for r in rewards_history)
    task_score_raw = sum(rewards_history) / max(1, len(rewards_history))
    task_score = _clamp_score(task_score_raw)
    print(
        f"[TASK_END] task={task_id} success={success_str} "
        f"steps={actual_steps} task_score={task_score:.4f} rewards={rewards_str}"
    )
    return task_score

async def main() -> None:
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY is required to run the baseline inference.")

    client = OpenAI(base_url=API_BASE_URL, api_key=OPENAI_API_KEY)
    env = SentinelSREClient(base_url=ENV_BASE_URL)

    print(
        f"[START] env=sentinel-sre model={MODEL_NAME} "
        f"tasks={','.join(TASK_IDS)} seed={BASE_SEED}"
    )

    task_scores: List[float] = []
    try:
        for index, task_id in enumerate(TASK_IDS):
            score = await run_task(client=client, env=env, task_id=task_id, seed=BASE_SEED + index)
            task_scores.append(score)
    finally:
        await env.close()

    aggregate_score = _clamp_score(sum(task_scores) / max(1, len(task_scores)))
    score_parts = ",".join(f"{task_id}:{score:.4f}" for task_id, score in zip(TASK_IDS, task_scores))
    print(f"[END] baseline_score={aggregate_score:.4f} task_scores={score_parts}")

if __name__ == "__main__":
    asyncio.run(main())
