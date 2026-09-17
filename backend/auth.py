"""Auth: bcrypt passwords + backend JWT (HS256, 24h). Frozen per AGENT_LOOP Phase 0.

NOTE: passlib is unmaintained and incompatible with bcrypt>=4 (wrap-bug
ValueError on verify), so hashing uses the `bcrypt` package directly.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .db import get_conn, get_dict_cur

ALGORITHM = "HS256"
TOKEN_HOURS = 24
_bearer = HTTPBearer(auto_error=False)


def jwt_secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if not s:
        raise RuntimeError("JWT_SECRET is not set (copy .env.example to .env)")
    return s


def normalize_username(username: str) -> str:
    # Usernames are unique case-insensitively: store + look up lowercase.
    return username.strip().lower()


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:72]  # bcrypt limit; fail closed beyond it
    if len(password.encode("utf-8")) > 72:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=TOKEN_HOURS)).timestamp()),
    }
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Resolve identity from backend JWT. Never trust client-sent user_id."""
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = jwt.decode(creds.credentials, jwt_secret(), algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token subject")
    with get_conn() as conn, get_dict_cur(conn) as cur:
        cur.execute(
            "SELECT id::text AS id, username, display_name FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return {"id": row["id"], "username": row["username"], "display_name": row["display_name"]}
