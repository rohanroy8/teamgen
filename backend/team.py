"""Team governance — conflicts inbox + Memory PR approve/reject (Phase 5)."""
from fastapi import HTTPException, status

from .db import get_dict_cur

_LEAD_ROLES = {"owner", "lead"}


def _membership(cur, project_id: str | None, user_id: str) -> str | None:
    if not project_id:
        return None
    cur.execute(
        """SELECT role FROM memberships
           WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
        (project_id, user_id),
    )
    row = cur.fetchone()
    return row["role"] if row else None


def _mem(cur, mid: str) -> dict | None:
    cur.execute(
        """SELECT m.id::text AS id, m.author_id::text AS author_id,
                  m.user_id, m.project_id::text AS project_id, m.scope,
                  m.subject, m.predicate, m.object, m.status, m.quote,
                  u.username AS author
           FROM memory m JOIN users u ON u.id = m.author_id
           WHERE m.id = %s""",
        (mid,),
    )
    return cur.fetchone()


def list_conflicts(conn, user_id: str, project_id: str) -> list[dict]:
    with get_dict_cur(conn) as cur:
        if _membership(cur, project_id, user_id) is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not a project member")
        cur.execute(
            """SELECT c.id::text AS id, c.status, c.note,
                      c.memory_a_id::text AS memory_a_id,
                      c.memory_b_id::text AS memory_b_id,
                      c.winner_id::text AS winner_id,
                      r.username AS resolver, c.created_at, c.resolved_at
               FROM conflicts c LEFT JOIN users r ON r.id = c.resolver_id
               WHERE c.project_id = %s ORDER BY c.created_at DESC""",
            (project_id,),
        )
        out = []
        for c in cur.fetchall():
            c["memory_a"] = _mem(cur, c["memory_a_id"])
            c["memory_b"] = _mem(cur, c["memory_b_id"])
            out.append(c)
        return out


def resolve_conflict(conn, user_id: str, conflict_id: str, mode: str,
                     note: str | None = None) -> dict:
    """mode: 'accept_both' or a winning memory id."""
    old, conn.autocommit = conn.autocommit, False
    try:
        with conn, get_dict_cur(conn) as cur:
            cur.execute(
                """SELECT c.id::text AS id, c.status, c.project_id::text AS project_id,
                          c.memory_a_id::text AS memory_a_id,
                          c.memory_b_id::text AS memory_b_id
                   FROM conflicts c WHERE c.id = %s""",
                (conflict_id,),
            )
            c = cur.fetchone()
            if c is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "conflict not found")
            if c["status"] != "open":
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"conflict already {c['status']}")
            ma, mb = _mem(cur, c["memory_a_id"]), _mem(cur, c["memory_b_id"])
            if c["project_id"]:
                if _membership(cur, c["project_id"], user_id) not in _LEAD_ROLES:
                    raise HTTPException(status.HTTP_403_FORBIDDEN,
                                        "only project leads/owners resolve conflicts")
            elif user_id not in (ma["author_id"], mb["author_id"]):
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    "only involved authors resolve this conflict")
            if mode == "accept_both":
                for mid in (ma["id"], mb["id"]):
                    cur.execute(
                        "UPDATE memory SET status='active', valid_to=NULL WHERE id=%s",
                        (mid,),
                    )
                cur.execute(
                    """UPDATE conflicts SET status='accepted_both', note=%s,
                           resolver_id=%s, resolved_at=now() WHERE id=%s""",
                    (note, user_id, conflict_id),
                )
                for mid in (ma["id"], mb["id"]):
                    cur.execute(
                        """INSERT INTO memory_event (memory_id, action, actor_id, detail)
                           VALUES (%s,'accepted_both',%s,'{"via":"conflict-resolve"}'::jsonb)""",
                        (mid, user_id),
                    )
                return {"conflict_id": conflict_id, "status": "accepted_both"}
            winner = _mem(cur, mode)
            if winner is None or winner["id"] not in (ma["id"], mb["id"]):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "winner_id must be one side of this conflict")
            loser = mb if winner["id"] == ma["id"] else ma
            cur.execute(
                "UPDATE memory SET status='active', valid_to=NULL WHERE id=%s",
                (winner["id"],),
            )
            cur.execute(
                """UPDATE memory SET status='superseded', valid_to=now(),
                       superseded_by=%s WHERE id=%s""",
                (winner["id"], loser["id"]),
            )
            cur.execute("UPDATE memory SET supersedes=%s WHERE id=%s",
                        (loser["id"], winner["id"]))
            cur.execute(
                """UPDATE conflicts SET status='resolved', winner_id=%s, note=%s,
                       resolver_id=%s, resolved_at=now() WHERE id=%s""",
                (winner["id"], note, user_id, conflict_id),
            )
            for mid, act in ((winner["id"], "accepted"), (loser["id"], "superseded")):
                cur.execute(
                    """INSERT INTO memory_event (memory_id, action, actor_id, detail)
                       VALUES (%s,%s,%s,'{"via":"conflict-resolve"}'::jsonb)""",
                    (mid, act, user_id),
                )
            return {"conflict_id": conflict_id, "status": "resolved",
                    "winner_id": winner["id"]}
    finally:
        conn.autocommit = old


def _check_proposal_auth(cur, user_id: str, prop: dict):
    """Approver: project lead/owner, or the proposal's own author (personal PRs)."""
    if prop["author_id"] == user_id:
        return
    if prop["project_id"] and _membership(cur, prop["project_id"], user_id) in _LEAD_ROLES:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        "only project leads/owners (or the proposer) decide PRs")


def decide_proposal(conn, user_id: str, proposal_id: str, approve: bool) -> dict:
    old, conn.autocommit = conn.autocommit, False
    try:
        with conn, get_dict_cur(conn) as cur:
            prop = _mem(cur, proposal_id)
            if prop is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
            if prop["status"] != "proposed":
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    f"proposal is {prop['status']}, not proposed")
            _check_proposal_auth(cur, user_id, prop)
            cur.execute(
                """SELECT id::text AS id, memory_a_id::text AS memory_a_id
                   FROM conflicts
                   WHERE memory_b_id = %s AND status = 'open' LIMIT 1""",
                (proposal_id,),
            )
            link = cur.fetchone()
            if approve:
                cur.execute(
                    "UPDATE memory SET status='active', valid_to=NULL WHERE id=%s",
                    (proposal_id,),
                )
                superseded = None
                if link:
                    target = _mem(cur, link["memory_a_id"])
                    cur.execute(
                        """UPDATE memory SET status='superseded', valid_to=now(),
                               superseded_by=%s WHERE id=%s""",
                        (proposal_id, target["id"]),
                    )
                    cur.execute("UPDATE memory SET supersedes=%s WHERE id=%s",
                                (target["id"], proposal_id))
                    cur.execute(
                        """UPDATE conflicts SET status='resolved', winner_id=%s,
                               resolver_id=%s, resolved_at=now() WHERE id=%s""",
                        (proposal_id, user_id, link["id"]),
                    )
                    superseded = target["id"]
                cur.execute(
                    """INSERT INTO memory_event (memory_id, action, actor_id, detail)
                       VALUES (%s,'approved',%s,'{"via":"proposal"}'::jsonb)""",
                    (proposal_id, user_id),
                )
                return {"proposal_id": proposal_id, "status": "active",
                        "superseded": superseded}
            cur.execute("UPDATE memory SET status='rejected' WHERE id=%s", (proposal_id,))
            if link:
                cur.execute(
                    """UPDATE conflicts SET status='resolved', note='proposal rejected',
                           resolver_id=%s, resolved_at=now() WHERE id=%s""",
                    (user_id, link["id"]),
                )
            cur.execute(
                """INSERT INTO memory_event (memory_id, action, actor_id, detail)
                   VALUES (%s,'rejected',%s,'{"via":"proposal"}'::jsonb)""",
                (proposal_id, user_id),
            )
            return {"proposal_id": proposal_id, "status": "rejected"}
    finally:
        conn.autocommit = old
