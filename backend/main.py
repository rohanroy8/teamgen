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


class ChatIn(BaseModel):
    text: str = Field(min_length=1)
    project_id: str | None = None
    scope: str = "personal"
    msg_id: str | None = None


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class InviteIn(BaseModel):
    username: str = Field(min_length=1)


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


# --- Phase 2: write path (extract -> resolve -> write). Answer generation lands in Phase 3. ---
@app.post("/chat")
def chat(body: ChatIn, user: dict = Depends(get_current_user)):
    import uuid

    from .write import ingest_text

    scope = body.scope if body.scope in ("personal", "project") else "personal"
    project_id = body.project_id
    if scope == "project" or project_id:
        if not project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_id required for project scope")
        with get_conn() as conn, get_dict_cur(conn) as cur:
            cur.execute(
                """SELECT role FROM memberships
                   WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
                (project_id, user["id"]),
            )
            mem = cur.fetchone()
        if mem is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not a project member")
        scope, scope_key = "project", project_id
    else:
        scope, scope_key = "personal", user["id"]
    msg_id = body.msg_id or f"api-{uuid.uuid4().hex[:12]}"
    session_key = f"{user['id']}:{(project_id or 'personal')}"
    # ingest_text owns its transaction: pass an un-entered connection.
    conn = get_conn()
    try:
        trace = ingest_text(conn, author_id=user["id"], scope=scope,
                            scope_key=scope_key, project_id=project_id,
                            text=body.text, msg_id=msg_id, session_key=session_key)
    finally:
        conn.close()
    return {"answer": "saved", "trace": trace}


@app.get("/projects/mine")
def my_projects(user: dict = Depends(get_current_user)):
    with get_conn() as conn, get_dict_cur(conn) as cur:
        cur.execute(
            """SELECT p.id::text AS id, p.name, m.role
               FROM projects p JOIN memberships m ON m.project_id = p.id
               WHERE m.user_id = %s AND m.left_at IS NULL ORDER BY p.name""",
            (user["id"],),
        )
        return {"projects": cur.fetchall()}


@app.post("/projects", status_code=201)
def create_project(body: ProjectIn, user: dict = Depends(get_current_user)):
    with get_conn() as conn, get_dict_cur(conn) as cur:
        cur.execute(
            "INSERT INTO projects (name, owner_id) VALUES (%s,%s) RETURNING id::text AS id, name",
            (body.name.strip(), user["id"]),
        )
        proj = cur.fetchone()
        cur.execute(
            "INSERT INTO memberships (project_id, user_id, role) VALUES (%s,%s,'owner')",
            (proj["id"], user["id"]),
        )
    return proj


@app.post("/projects/{project_id}/invite")
def invite(project_id: str, body: InviteIn, user: dict = Depends(get_current_user)):
    from .auth import normalize_username

    with get_conn() as conn, get_dict_cur(conn) as cur:
        cur.execute(
            """SELECT role FROM memberships
               WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
            (project_id, user["id"]),
        )
        mem = cur.fetchone()
        if mem is None or mem["role"] not in ("owner", "lead"):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "only project owners/leads can invite")
        username = normalize_username(body.username)
        cur.execute("SELECT id::text AS id, username FROM users WHERE username = %s",
                    (username,))
        target = cur.fetchone()
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        cur.execute(
            "SELECT left_at FROM memberships WHERE project_id = %s AND user_id = %s",
            (project_id, target["id"]),
        )
        existing = cur.fetchone()
        if existing and existing["left_at"] is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "already member")
        cur.execute(
            """INSERT INTO memberships (project_id, user_id, role) VALUES (%s,%s,'member')
               ON CONFLICT (project_id, user_id)
               DO UPDATE SET role='member', left_at=NULL, joined_at=now()""",
            (project_id, target["id"]),
        )
    return {"project_id": project_id, "username": target["username"], "role": "member"}
