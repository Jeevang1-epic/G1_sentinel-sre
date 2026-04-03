import uvicorn
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("Booting Sentinel-SRE Environment...")
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=True)