# Phase 0 backend stub — real auth/DB lands in Phase 1.
# This file exists so `python3 -c "import fastapi..."` style checks pass
# and `ls backend` shows structure. See AGENT_LOOP.md Phase 1+ for full impl.
from fastapi import FastAPI

app = FastAPI(title="teamgen-memory")


@app.get("/health")
def health():
    return {"ok": True, "phase": 0}


@app.post("/auth/signup")
def signup_stub():
    return {"detail": "not implemented until Phase 1"}


@app.post("/auth/login")
def login_stub():
    return {"detail": "not implemented until Phase 1"}


@app.get("/me")
def me_stub():
    return {"detail": "not implemented until Phase 1"}
