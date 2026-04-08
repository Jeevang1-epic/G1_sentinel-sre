---
title: Sentinel SRE
emoji: 🛡️
sdk: docker
app_port: 8000
pinned: false
tags:
  - openenv
  - environment
  - agent
---

# Sentinel-SRE: Autonomous Incident Response Environment

Sentinel-SRE is an OpenEnv-compliant Site Reliability Engineering simulator for benchmarking agent behavior in production-style outage response.  
It models realistic triage, remediation, escalation pressure, and SLA-bound recovery under constrained steps.

## Why This Environment Is Useful

- Real-world utility: incident-response workflows are a daily SRE responsibility.
- Agent-evaluation value: tasks require prioritization, signal reading, and targeted remediation.
- Non-trivial dynamics: degraded services can escalate into cascading failures when ignored.

## OpenEnv Interface

- `Action`: `SREAction(command, target)`
- `Observation`: `SREObservation(task_id, task_name, task_difficulty, system_health, active_alerts, terminal_output, attempts_remaining, reward, done)`
- `State`: `SREState(..., task_id, task_name, task_difficulty, task_description, incident_briefing, grader_id, services_status, resolved)`
- API endpoints: `/reset`, `/step`, `/state`, `/schema`, `/metadata`, `/health`, `/ws`, `/mcp`, `/tasks`, `/grade/{task_id}`, `/validate`

## Task Catalog (3 Programmatic Graders)

| Task ID | Difficulty | Objective | Grader ID |
|---|---|---|---|
| `api-recovery-easy` | easy | Recover edge API outage before SLA target | `grader-api-recovery-easy-v1` |
| `auth-latency-medium` | medium | Resolve auth-db degradation before retry-storm propagation | `grader-auth-latency-medium-v1` |
| `payment-cascade-hard` | hard | Stabilize payment outage with cascading multi-service impact | `grader-payment-cascade-hard-v1` |

### Deterministic task behavior

- `reset(task_id=..., seed=...)` supports deterministic episode initialization.
- With `seed`, task selection is deterministic (`seed % 3` mapping).
- Without `task_id` and without `seed`, resets rotate through all three tasks in round-robin order to guarantee coverage.
- Task selectors accept aliases: `task_id`, `task_name`, `task`, `scenario`, `difficulty`, `level`.
- Each task has a dedicated programmatic grader path.

## Reward/Grader Design

The reward function is dense (not sparse-only) and deterministic:

- Service-status quality (`running > degraded > crashed`)
- Efficiency pressure (fewer steps used => better score)
- Action quality (`restart_service` on the correct target > passive/no-op/invalid behavior)
- Resolution bonus (larger when solved within `sla_target_steps`)
- Escalation penalties are reflected via worsened service states

### Score bounds

- All scores are explicitly clamped to **exclusive** evaluator-safe bounds: `(0.01, 0.99)`.
- No terminal or intermediate action returns exactly `0.0` or `1.0`.

## Baseline Inference Script

`inference.py`:

- Uses the OpenAI Python client.
- Reads credentials from `OPENAI_API_KEY` (falls back to `HF_TOKEN` if provided).
- Runs the baseline across all 3 task IDs in a fixed order.
- Uses fixed seeds (`BASELINE_SEED + task_index`) for reproducibility.
- Prints per-task score + aggregate baseline score.

### Run baseline

```bash
export OPENAI_API_KEY=...
export MODEL_NAME=gpt-4o-mini
python inference.py
```

### Reference deterministic baseline (local, seed = 20260408)

These are deterministic reference scores generated with the built-in policy logic:

- `api-recovery-easy`: `0.9900`
- `auth-latency-medium`: `0.9900`
- `payment-cascade-hard`: `0.9320`
- Aggregate baseline score: `0.9707`

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

## Container / HF Space

- Docker runtime uses `server/Dockerfile`.
- `requirements.txt` includes runtime dependencies for FastAPI + OpenEnv + OpenAI client.
- Space should expose app on port `8000`.

## Validation Checklist Mapping

- OpenEnv spec compliance: typed Action/Observation/State + standard routes.
- Minimum 3 tasks with graders: implemented and task-linked.
- Meaningful reward function: dense trajectory signal + escalation dynamics.
- Baseline script requirement: OpenAI client + env-var credentials + reproducible multi-task scoring.
