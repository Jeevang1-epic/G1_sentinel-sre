import os
import textwrap
import asyncio
from typing import List
from openai import OpenAI

from client import SentinelSREClient
from models import SREAction


API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY")


MAX_STEPS = 10
TEMPERATURE = 0.2
MAX_TOKENS = 100

SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an elite Site Reliability Engineer (SRE).
    Your goal is to resolve system outages by restarting crashed or degraded microservices.
    
    You must reply with exactly ONE command string per turn.
    Valid commands:
    - restart_service <target>
    - check_health
    - noop
    
    Valid targets are strictly the exact service names shown in the alerts (e.g., web-api, auth-db, payment-gateway). DO NOT abbreviate target names.
    Example: restart_service payment-gateway
    
    CRITICAL: Do not include explanations, markdown formatting (no backticks), or conversational text. Output the command ONLY.
    """
).strip()

def build_user_prompt(step: int, obs, history: List[str]) -> str:
    alerts = ", ".join(obs.active_alerts) if obs.active_alerts else "None"
    hist_text = "\n".join(history[-3:]) if history else "None"
    
    return textwrap.dedent(
        f"""
        Step: {step}
        System Health: {obs.system_health}
        Active Alerts: {alerts}
        Terminal Output: {obs.terminal_output}
        Recent Actions:
        {hist_text}
        
        What is your next command?
        """
    ).strip()

def parse_model_action(response_text: str) -> SREAction:
    text = response_text.lower()
    
    command = "noop"
    valid_commands = ["restart_service", "check_health", "read_log", "rollback", "block_ip"]
    for cmd in valid_commands:
        if cmd in text:
            command = cmd
            break  
            
    target = ""
    if "payment" in text:
        target = "payment-gateway"
    elif "web" in text:
        target = "web-api"
    elif "auth" in text:
        target = "auth-db"
        
    return SREAction(command=command, target=target)

async def main() -> None:
    if not HF_TOKEN:
        return

    client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN)
    env = SentinelSREClient(base_url="http://127.0.0.1:8000")
    
    history: List[str] = []
    rewards_history: List[float] = []

    try:
        print(f"[START] task=sre-incident-response env=sentinel-sre model={MODEL_NAME}")
        
        result = await env.reset()
        obs = result.observation
        actual_steps = 0
        
        for step in range(1, MAX_STEPS + 1):
            if result.done:
                break
                
            actual_steps = step
            user_prompt = build_user_prompt(step, obs, history)
            
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
                response_text = "noop"

            action = parse_model_action(response_text)
            action_str = f"{action.command}('{action.target}')" if action.target else f"{action.command}()"
            
            result = await env.step(action)
            obs = result.observation
            reward = result.reward
            
            history.append(f"Action: {action_str} | Reward: {reward}")
            rewards_history.append(reward)
            
            done_str = str(result.done).lower()
            print(f"[STEP] step={step} action={action_str} reward={reward:.2f} done={done_str} error=null")

        current_state = await env.state()
        success_str = str(current_state.resolved).lower()
        rewards_str = ",".join(f"{r:.2f}" for r in rewards_history)
        
        print(f"[END] success={success_str} steps={actual_steps} rewards={rewards_str}")

    finally:
        pass 

if __name__ == "__main__":
    asyncio.run(main())