import uvicorn
from openenv.core.env_server import create_fastapi_app
from server.environment import SentinelSREEnvironment
from models import SREAction, SREObservation

app = create_fastapi_app(SentinelSREEnvironment, SREAction, SREObservation)

def main():
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()