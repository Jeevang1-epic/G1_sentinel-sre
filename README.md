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

# 🛡️ Sentinel-SRE: Autonomous Incident Response Environment

Sentinel-SRE is an enterprise-grade OpenEnv simulator designed to evaluate the operational capabilities of AI agents acting as Site Reliability Engineers (SREs). 

Unlike standard web-navigation or game environments, Sentinel-SRE tests an agent's ability to ingest PagerDuty-style alerts, parse simulated terminal outputs, and execute precise remediation commands to restore microservice health without violating SLAs.

## The Tasks
The environment procedurally generates incidents across three difficulty tiers:
1. **Easy:** Single service failure (e.g., `web-api` crash). Agent must read the alert and restart the specific service.
2. **Medium:** Degraded performance (e.g., `auth-db` latency). Agent must identify the degraded service and restart it before a cascading failure occurs.
3. **Hard:** Cascading multi-service failure. Agent must triage multiple alerts, identify the core crashed service vs. the degraded dependent service, and resolve them efficiently.

## Observation & Action Space
- **Observation:** `SREObservation` containing `system_health` (0.0-1.0), `active_alerts` (List[str]), `terminal_output` (str), and `attempts_remaining` (int).
- **Action:** `SREAction` requiring a `command` (e.g., `restart_service`, `check_health`) and a `target` (e.g., `web-api`).

## Deterministic Reward Function
- **+1.0:** Incident fully resolved (all services running).
- **+0.5:** Partial progress (successfully restarting one crashed service in a multi-service failure).
- **-0.1:** Wasted action (restarting an already healthy service, targeting a non-existent service).
- **-0.2:** Syntax/Unknown command error.
- **-1.0:** SLA breached (ran out of attempts).