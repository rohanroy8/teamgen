"""Team Memory backend — Phase 1: auth + identity. Chat/memories land in Phase 2+."""
import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

load_dotenv()

from .auth import (
    create_token,
    get_current_user,
    hash_password,
    normalize_username,
    verify_password,
)
from .db import get_conn, get_dict_cur

app = FastAPI(title="teamgen-memory")


class SignupIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)
    display_name: str | None = None


class LoginIn(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


@app.get("/health")
def health():
    return {"ok": True, "phase": 1}


@app.post("/auth/signup", status_code=201)
def signup(body: SignupIn):
    username = normalize_username(body.username)
    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "username required")
    pw_hash = hash_password(body.password)
    with get_conn() as conn, get_dict_cur(conn) as cur:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "username taken")
        cur.execute(
            """INSERT INTO users (username, display_name, password_hash)
               VALUES (%s, %s, %s) RETURNING id::text AS id, username""",
            (username, body.display_name or username, pw_hash),
        )
        row = cur.fetchone()
    return row


@app.post("/auth/login")
def login(body: LoginIn):
    username = normalize_username(body.username)
    with get_conn() as conn, get_dict_cur(conn) as cur:
        cur.execute(
            "SELECT id::text AS id, username, password_hash FROM users WHERE username = %s",
            (username,),
        )
        row = cur.fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    token = create_token(row["id"], row["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": row["id"], "username": row["username"]},
    }


@app.get("/me")
def me(user: dict = Depends(get_current_user)):
    return user


# --- Phase 2+ stubs (wired in their phases, listed here so routes 404 cleanly) ---
@app.post("/chat")
def chat_stub(user: dict = Depends(get_current_user)):
    return {"detail": "chat lands in Phase 2"}
