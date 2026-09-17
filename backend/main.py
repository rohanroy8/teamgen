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

    # Phase 3: retrieve -> answer -> cite, with the ingest trace attached.
    from datetime import datetime

    from .answer import answer_question
    from .llm_provider import get_provider
    from .retrieve import retrieve

    conn = get_conn()
    try:
        facts = retrieve(conn, user_id=user["id"], scope=scope,
                         scope_key=scope_key, project_id=project_id,
                         question=body.text)
    finally:
        conn.close()
    owner_hint = None
    if project_id:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT u.username FROM projects p JOIN users u ON u.id = p.owner_id
                       WHERE p.id = %s""",
                    (project_id,),
                )
                row = cur.fetchone()
                owner_hint = row[0] if row else None
        finally:
            conn.close()
    try:
        result = answer_question(body.text, facts, provider=get_provider(),
                                 owner_hint=owner_hint, asker=user["username"])
    except Exception:
        result = {"answer": "I couldn't compose an answer right now.",
                  "used_ids": []}
    trace["retrieved"] = [f["id"] for f in facts]
    return {"answer": result["answer"], "used_ids": result["used_ids"],
            "trace": trace}


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


def _visible_scope(user: dict, project_id: str | None, scope: str) -> tuple[str, str | None]:
    """Resolve + authorize the caller's memory scope. Raises 403 on no access."""
    from .retrieve import has_access

    if scope == "project" or project_id:
        if not project_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "project_id required for project scope")
        conn = get_conn()
        try:
            if not has_access(conn, user["id"], "project", project_id, project_id):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "not a project member")
        finally:
            conn.close()
        return "project", project_id
    return "personal", None


@app.get("/memories")
def list_memories(project_id: str | None = None, scope: str = "personal",
                  status: str | None = None, limit: int = 50,
                  user: dict = Depends(get_current_user)):
    scope, pid = _visible_scope(user, project_id, scope)
    scope_key = pid if scope == "project" else user["id"]
    with get_conn() as conn, get_dict_cur(conn) as cur:
        if status:
            cur.execute(
                """SELECT m.id::text AS id, m.subject, m.predicate, m.object, m.status,
                          m.scope, m.valid_from, m.valid_to, m.recorded_at, m.confidence,
                          m.quote, u.username AS author
                   FROM memory m JOIN users u ON u.id = m.author_id
                   WHERE m.user_id = %s AND m.scope = %s
                     AND m.project_id IS NOT DISTINCT FROM %s AND m.status = %s
                   ORDER BY m.recorded_at DESC LIMIT %s""",
                (scope_key, scope, pid, status, min(limit, 200)),
            )
        else:
            cur.execute(
                """SELECT m.id::text AS id, m.subject, m.predicate, m.object, m.status,
                          m.scope, m.valid_from, m.valid_to, m.recorded_at, m.confidence,
                          m.quote, u.username AS author
                   FROM memory m JOIN users u ON u.id = m.author_id
                   WHERE m.user_id = %s AND m.scope = %s
                     AND m.project_id IS NOT DISTINCT FROM %s
                   ORDER BY m.recorded_at DESC LIMIT %s""",
                (scope_key, scope, pid, min(limit, 200)),
            )
        return {"memories": cur.fetchall()}


@app.get("/memories/at")
def memories_at(date: str, project_id: str | None = None,
                user: dict = Depends(get_current_user)):
    """Time-travel: facts as they were true on `date` (valid-time, not ingestion)."""
    from datetime import datetime

    from .retrieve import retrieve

    try:
        as_of = datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "date must be ISO8601")
    scope = "project" if project_id else "personal"
    scope, pid = _visible_scope(user, project_id, scope)
    scope_key = pid if scope == "project" else user["id"]
    conn = get_conn()
    try:
        facts = retrieve(conn, user_id=user["id"], scope=scope, scope_key=scope_key,
                         project_id=pid, question="", as_of=as_of, limit=50)
    finally:
        conn.close()
    return {"date": date, "facts": facts}


# --- Phase 4: version control (history/revert/digest/onboard) ---
@app.get("/memories/{fact_id}/history")
def fact_history(fact_id: str, user: dict = Depends(get_current_user)):
    from .version import check_access, get_fact, history

    conn = get_conn()
    try:
        fact = get_fact(conn, fact_id)
        if fact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "memory not found")
        check_access(conn, user["id"], fact)
        return history(conn, fact_id)
    finally:
        conn.close()


@app.post("/memories/{fact_id}/revert")
def fact_revert(fact_id: str, user: dict = Depends(get_current_user)):
    from .version import revert

    conn = get_conn()
    try:
        return revert(conn, fact_id, user["id"])
    finally:
        conn.close()


@app.get("/digest")
def digest(project_id: str, days: int = 7, user: dict = Depends(get_current_user)):
    from .version import digest as project_digest

    conn = get_conn()
    try:
        return project_digest(conn, user["id"], project_id, min(max(days, 1), 90))
    finally:
        conn.close()


@app.get("/onboard")
def onboard(project_id: str, user: dict = Depends(get_current_user)):
    from .version import onboard as project_onboard

    conn = get_conn()
    try:
        return project_onboard(conn, user["id"], project_id)
    finally:
        conn.close()


# --- Phase 5: team governance (conflicts inbox + Memory PRs) ---
@app.get("/conflicts")
def conflicts(project_id: str, user: dict = Depends(get_current_user)):
    from .team import list_conflicts

    conn = get_conn()
    try:
        return {"conflicts": list_conflicts(conn, user["id"], project_id)}
    finally:
        conn.close()


class ConflictResolveIn(BaseModel):
    mode: str = Field(description="'accept_both' or winning memory id")
    note: str | None = None


@app.post("/conflicts/{conflict_id}/resolve")
def conflict_resolve(conflict_id: str, body: ConflictResolveIn,
                     user: dict = Depends(get_current_user)):
    from .team import resolve_conflict

    conn = get_conn()
    try:
        return resolve_conflict(conn, user["id"], conflict_id, body.mode, body.note)
    finally:
        conn.close()


@app.post("/proposals/{proposal_id}/approve")
def proposal_approve(proposal_id: str, user: dict = Depends(get_current_user)):
    from .team import decide_proposal

    conn = get_conn()
    try:
        return decide_proposal(conn, user["id"], proposal_id, True)
    finally:
        conn.close()


@app.post("/proposals/{proposal_id}/reject")
def proposal_reject(proposal_id: str, user: dict = Depends(get_current_user)):
    from .team import decide_proposal

    conn = get_conn()
    try:
        return decide_proposal(conn, user["id"], proposal_id, False)
    finally:
        conn.close()
