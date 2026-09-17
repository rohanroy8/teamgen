"""Memory version control — history/blame/revert/digest/onboard (Phase 4).

Append-only: revert flips statuses + logs events, never deletes or rewrites rows.
History reads like `git log`; revert is blame-aware (lead/owner or original author).
"""
from fastapi import HTTPException, status

from .db import get_conn, get_dict_cur

_LEAD_ROLES = {"owner", "lead"}


def get_fact(conn, fact_id: str) -> dict | None:
    with get_dict_cur(conn) as cur:
        cur.execute(
            """SELECT m.id::text AS id, m.author_id::text AS author_id,
                      m.user_id, m.project_id::text AS project_id, m.scope,
                      m.subject, m.predicate, m.object, m.status,
                      m.epistemic_status, m.valid_from, m.valid_to, m.recorded_at,
                      m.supersedes::text AS supersedes,
                      m.superseded_by::text AS superseded_by,
                      m.quote, m.confidence, u.username AS author
               FROM memory m JOIN users u ON u.id = m.author_id
               WHERE m.id = %s""",
            (fact_id,),
        )
        return cur.fetchone()


def check_access(conn, user_id: str, fact: dict):
    """Raise 403 unless user_id may see this fact (personal owner or project member)."""
    if fact["scope"] == "personal" and fact["user_id"] == user_id:
        return
    if fact["scope"] == "project" and fact["project_id"]:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM memberships
                   WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
                (fact["project_id"], user_id),
            )
            if cur.fetchone():
                return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "no access to this memory")


def history(conn, fact_id: str) -> dict:
    fact = get_fact(conn, fact_id)
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory not found")
    # Walk back to the oldest ancestor, then forward to the head.
    oldest = fact
    guard = 0
    while oldest["supersedes"] and guard < 100:
        prev = get_fact(conn, oldest["supersedes"])
        if prev is None:
            break
        oldest = prev
        guard += 1
    chain, guard = [], 0
    node = oldest
    while node and guard < 100:
        chain.append(node)
        node = get_fact(conn, node["superseded_by"]) if node["superseded_by"] else None
        guard += 1
    with get_dict_cur(conn) as cur:
        cur.execute(
            """SELECT e.id::text AS id, e.memory_id::text AS memory_id, e.action,
                      a.username AS actor, e.detail, e.created_at
               FROM memory_event e LEFT JOIN users a ON a.id = e.actor_id
               WHERE e.memory_id = ANY(%s::uuid[])
               ORDER BY e.created_at""",
            ([n["id"] for n in chain],),
        )
        events = cur.fetchall()
    return {"chain": chain, "events": events}


def revert(conn, fact_id: str, user_id: str) -> dict:
    fact = get_fact(conn, fact_id)
    if fact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory not found")
    check_access(conn, user_id, fact)
    if fact["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"only an active fact can be reverted (is {fact['status']})")
    # Authorized: project lead/owner, or the original author (personal or project).
    allowed = fact["author_id"] == user_id
    if not allowed and fact["scope"] == "project" and fact["project_id"]:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT role FROM memberships
                   WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
                (fact["project_id"], user_id),
            )
            row = cur.fetchone()
            allowed = row is not None and row[0] in _LEAD_ROLES
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "revert needs project lead/owner or original author")
    prev = get_fact(conn, fact["supersedes"]) if fact["supersedes"] else None
    old_autocommit, conn.autocommit = conn.autocommit, False
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE memory SET status='retracted', valid_to=now() WHERE id = %s",
                (fact_id,),
            )
            cur.execute(
                """INSERT INTO memory_event (memory_id, action, actor_id, detail)
                   VALUES (%s,'reverted',%s,'{"via":"revert"}'::jsonb)""",
                (fact_id, user_id),
            )
            if prev is not None:
                # Restore prior row to active. superseded_by is KEPT so the
                # history chain stays walkable (status + events tell the story).
                cur.execute(
                    """UPDATE memory SET status='active', valid_to=NULL
                       WHERE id = %s""",
                    (prev["id"],),
                )
                cur.execute(
                    """INSERT INTO memory_event (memory_id, action, actor_id, detail)
                       VALUES (%s,'restored',%s,'{"via":"revert"}'::jsonb)""",
                    (prev["id"], user_id),
                )
    finally:
        conn.autocommit = old_autocommit
    return {"reverted": fact_id, "restored": prev["id"] if prev else None}


def digest(conn, user_id: str, project_id: str, days: int = 7) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM memberships
               WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
            (project_id, user_id),
        )
        if not cur.fetchone():
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not a project member")
    with get_dict_cur(conn) as cur:
        cur.execute(
            """SELECT e.action, count(*) AS n
               FROM memory_event e JOIN memory m ON m.id = e.memory_id
               WHERE m.project_id = %s AND e.created_at > now() - (%s || ' days')::interval
               GROUP BY e.action ORDER BY e.action""",
            (project_id, days),
        )
        counts = {r["action"]: r["n"] for r in cur.fetchall()}
    return {"project_id": project_id, "days": days, "counts": counts}


def onboard(conn, user_id: str, project_id: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM memberships
               WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
            (project_id, user_id),
        )
        if not cur.fetchone():
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not a project member")
    with get_dict_cur(conn) as cur:
        cur.execute(
            """SELECT m.id::text AS id, m.subject, m.predicate, m.object, m.status,
                      u.username AS author
               FROM memory m JOIN users u ON u.id = m.author_id
               WHERE m.project_id = %s AND m.scope = 'project' AND m.status = 'active'
               ORDER BY m.importance DESC, m.recorded_at DESC LIMIT 10""",
            (project_id,),
        )
        facts = cur.fetchall()
    lines = [f"- @{f['author']}: {f['subject']} {f['predicate']} {f['object']}"
             for f in facts]
    brief = "Catch-me-up — active project facts:\n" + ("\n".join(lines) if lines else "(none yet)")
    return {"project_id": project_id, "brief": brief,
            "used_ids": [f["id"] for f in facts]}
