from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

# 1. Get the exact path to the "src" folder inside audiomass
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_FOLDER = os.path.join(BASE_DIR, "src")

# 2. Mount the src folder directly to "/" so it automatically loads index.html
if os.path.exists(SRC_FOLDER):
    app.mount("/", StaticFiles(directory=SRC_FOLDER, html=True), name="frontend")
else:
    @app.get("/")
    def error_message():
        return {"error": f"Could not find src folder at: {SRC_FOLDER}"}

