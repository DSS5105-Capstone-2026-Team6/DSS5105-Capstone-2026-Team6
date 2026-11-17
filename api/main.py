"""api/main.py — FastAPI front-end for the DispatchDesk (Streamlit parity).

App assembly only: middleware, auth, the index page, and the feature
routers under api/routes/. Session state and serialisation helpers live in
api/state.py; dashboard chart data builders in api/charts.py.

Run:  uvicorn api.main:app --port 8000
"""

import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.routes import dashboard, decisions, intake, misc, world

STATIC_DIR = Path(__file__).parent / "static"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
AUTH_TOKENS = {}

app = FastAPI(title="Dispatch Desk API")


@app.middleware("http")
async def ensure_session_cookie(request: Request, call_next):
    """Sessions were created per request because the sid was never written
    back to the client — every API call started a fresh session (decisions,
    objective, chat log all reset). Issue and persist a sid cookie."""
    request.state.new_sid = None
    if "sid" not in request.cookies:
        request.state.new_sid = secrets.token_hex(12)
    response = await call_next(request)
    if request.state.new_sid:
        response.set_cookie("sid", request.state.new_sid,
                            max_age=7 * 86400, samesite="lax")
    return response


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody):
    if not APP_PASSWORD or body.password == APP_PASSWORD:
        token = secrets.token_hex(16)
        AUTH_TOKENS[token] = time.time() + 30 * 86400
        return JSONResponse({"token": token})
    return JSONResponse({"error": "Wrong password."}, status_code=401)


def authed(request):
    if not APP_PASSWORD:
        return True
    token = request.cookies.get("auth") or request.headers.get("x-auth")
    return token in AUTH_TOKENS and AUTH_TOKENS[token] > time.time()


for r in (intake.router, decisions.router, world.router,
          dashboard.router, misc.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
