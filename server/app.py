import uvicorn
from fastapi import HTTPException
from openenv.core.env_server import create_fastapi_app
from server.environment import SentinelSREEnvironment
from models import SREAction, SREObservation

app = create_fastapi_app(SentinelSREEnvironment, SREAction, SREObservation)

@app.get("/tasks", tags=["Environment Info"])
def list_tasks() -> dict:
    env = SentinelSREEnvironment()
    try:
        tasks = env.list_task_definitions()
        return {
            "count": len(tasks),
            "tasks": tasks,
        }
    finally:
        env.close()

@app.get("/grade/{task_id}", tags=["Environment Info"])
def grade_task(task_id: str) -> dict:
    env = SentinelSREEnvironment()
    try:
        if task_id not in env._scenario_by_id:
            raise HTTPException(status_code=404, detail=f"Unknown task_id: {task_id}")
        return env.evaluate_task_score(task_id)
    finally:
        env.close()

@app.get("/validate", tags=["Environment Info"])
def validate_tasks() -> dict:
    env = SentinelSREEnvironment()
    try:
        tasks = env.list_task_definitions()
        grade_reports = [env.evaluate_task_score(task["id"]) for task in tasks]
        checks = {
            "task_count_at_least_3": len(tasks) >= 3,
            "all_tasks_have_graders": all(bool(task["has_grader"]) for task in tasks),
            "all_scores_exclusive_bounds": all(
                0.0 < float(report["score"]) < 1.0 for report in grade_reports
            ),
        }
        return {
            "checks": checks,
            "task_count": len(tasks),
            "tasks": tasks,
            "grade_reports": grade_reports,
            "passed": all(checks.values()),
        }
    finally:
        env.close()

def main():
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
