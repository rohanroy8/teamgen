"""Write path — transactional insert/supersede, idempotency, memory_event log.

ingest_text() owns ONE transaction: message row + every candidate's resolution.
author_id ALWAYS comes from the JWT caller — never from client body.
Idempotency: idempotency_key = session_key + msg_id + candidate hash; a repeated
delivery returns the original outcome without new rows.
"""
import hashlib

from .embeddings import embed, to_pgvector
from .extract import extract_candidates
from .llm_provider import BaseProvider
from .resolve import fact_key, resolve_candidate


def _idem_key(session_key: str, msg_id: str, cand: dict) -> str:
    h = hashlib.sha256(
        f"{cand.get('subject')}|{cand.get('predicate')}|{cand.get('object')}|"
        f"{cand.get('epistemic_status')}|{cand.get('valid_from')}".encode()
    ).hexdigest()[:16]
    return f"{session_key}:{msg_id}:{h}"


def _log_event(cur, memory_id: str | None, action: str, actor_id: str, detail: str = "{}"):
    cur.execute(
        "INSERT INTO memory_event (memory_id, action, actor_id, detail) "
        "VALUES (%s,%s,%s,%s::jsonb)",
        (memory_id, action, actor_id, detail),
    )


def _insert_memory(cur, cand: dict, ctx: dict, status: str, msg_id: str,
                   vec: str | None) -> str:
    cur.execute(
        """INSERT INTO memory (author_id, user_id, project_id, scope, subject, predicate,
            object, fact_key, type, epistemic_status, override_signal, asserted_strength,
            status, valid_from, source_message_id, quote, confidence,
            idempotency_key, embedding)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   COALESCE(%s, now()),%s,%s,%s,%s,%s::vector)
           RETURNING id::text""",
        (ctx["author_id"], ctx["scope_key"], ctx["project_id"], ctx["scope"],
         cand["subject"], cand["predicate"], cand["object"],
         cand.get("_fact_key") or fact_key(cand["subject"], cand["predicate"]),
         cand.get("type", "fact"), cand.get("epistemic_status", "asserted"),
         cand.get("override_signal", False), cand.get("asserted_strength"),
         status, cand.get("valid_from"), msg_id, cand.get("quote"),
         cand.get("asserted_strength"), cand["_idem_key"], vec),
    )
    return cur.fetchone()[0]


def _apply_decision(cur, decision: dict, ctx: dict, msg_id: str,
                    vec: str | None) -> dict:
    cand = decision["candidate"]
    actor = ctx["author_id"]
    d = decision["decision"]

    if d == "noop":
        for t in decision.get("targets", []):
            cur.execute(
                "UPDATE memory SET evidence_count = evidence_count + 1 WHERE id = %s",
                (t["id"],),
            )
            _log_event(cur, t["id"], "duplicate_noop", actor, '{"via":"write"}')
        return {"decision": d, "reason": decision["reason"], "ids": []}

    if d == "insert_active":
        new_id = _insert_memory(cur, cand, ctx, "active", msg_id, vec)
        _log_event(cur, new_id, "added", actor, '{"via":"write"}')
        return {"decision": d, "reason": decision["reason"], "ids": [new_id]}

    if d == "insert_proposed":
        new_id = _insert_memory(cur, cand, ctx, "proposed", msg_id, vec)
        _log_event(cur, new_id, "proposed", actor, '{"via":"write"}')
        # Pinned-PR proposals link to the challenged fact so approve/reject
        # (Phase 5) can resolve them; plain hedged proposals have no targets.
        conflict_id = None
        for t in decision.get("targets", []):
            cur.execute(
                """INSERT INTO conflicts (project_id, memory_a_id, memory_b_id, status)
                   VALUES (%s,%s,%s,'open') RETURNING id::text""",
                (ctx["project_id"], t["id"], new_id),
            )
            conflict_id = cur.fetchone()[0]
        out = {"decision": d, "reason": decision["reason"], "ids": [new_id]}
        if conflict_id:
            out["conflict_id"] = conflict_id
        return out

    if d == "supersede":
        target = decision["targets"][0]
        new_id = _insert_memory(cur, cand, ctx, "active", msg_id, vec)
        cur.execute(
            """UPDATE memory SET status='superseded', valid_to=now(), superseded_by=%s
               WHERE id=%s AND status='active'""",
            (new_id, target["id"]),
        )
        cur.execute("UPDATE memory SET supersedes=%s WHERE id=%s", (target["id"], new_id))
        _log_event(cur, new_id, "added", actor, '{"via":"write"}')
        _log_event(cur, target["id"], "superseded", actor, '{"via":"write"}')
        return {"decision": d, "reason": decision["reason"], "ids": [new_id],
                "superseded": target["id"]}

    if d == "disputed":
        target = decision["targets"][0]
        new_id = _insert_memory(cur, cand, ctx, "disputed", msg_id, vec)
        cur.execute("UPDATE memory SET conflicts_with_id=%s WHERE id=%s",
                    (target["id"], new_id))
        cur.execute(
            """INSERT INTO conflicts (project_id, memory_a_id, memory_b_id, status)
               VALUES (%s,%s,%s,'open') RETURNING id::text""",
            (ctx["project_id"], target["id"], new_id),
        )
        conflict_id = cur.fetchone()[0]
        _log_event(cur, new_id, "disputed", actor, '{"via":"write"}')
        return {"decision": d, "reason": decision["reason"], "ids": [new_id],
                "conflict_id": conflict_id}

    if d == "retract":
        ids = []
        for t in decision["targets"]:
            cur.execute(
                "UPDATE memory SET status='retracted', valid_to=now() WHERE id=%s",
                (t["id"],),
            )
            _log_event(cur, t["id"], "retracted", actor, '{"via":"write"}')
            ids.append(t["id"])
        return {"decision": d, "reason": decision["reason"], "ids": ids}

    if d == "forget_all":
        cur.execute(
            """UPDATE memory SET status='forgotten', valid_to=now(), embedding=NULL
               WHERE user_id=%s AND scope=%s AND project_id IS NOT DISTINCT FROM %s
                 AND status='active'""",
            (ctx["scope_key"], ctx["scope"], ctx["project_id"]),
        )
        _log_event(cur, None, "forget_all", actor, '{"via":"write"}')
        return {"decision": d, "reason": decision["reason"], "ids": []}

    raise ValueError(f"unknown decision: {d}")


def ingest_text(conn, *, author_id: str, scope: str, scope_key: str,
                project_id: str | None, text: str, msg_id: str,
                session_key: str, provider: BaseProvider | None = None,
                candidates: list[dict] | None = None,
                speaker: str | None = None) -> dict:
    """Full write path in one transaction. Returns a trace dict."""
    trace = {"retrieved": [], "rejected": [], "used": [], "writes": []}
    if candidates is None:
        candidates = extract_candidates(text, provider=provider, speaker=speaker)
    vecs = embed([f"{c.get('subject','')} {c.get('predicate','')} {c.get('object','')}"
                  for c in candidates]) if candidates else []
    if vecs is None:
        vecs = [None] * len(candidates)

    # get_conn() is autocommit; the write path must be ONE transaction.
    old_autocommit, conn.autocommit = conn.autocommit, False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id::text AS id FROM memory WHERE idempotency_key LIKE %s LIMIT 1",
                    (f"{session_key}:{msg_id}:%",),
                )
                if cur.fetchone():
                    trace["rejected"].append({"reason": "idempotent replay", "msg_id": msg_id})
                    return trace
                cur.execute(
                    "INSERT INTO messages (project_id, author_id, text) VALUES (%s,%s,%s) "
                    "RETURNING id::text",
                    (project_id, author_id, text),
                )
                db_msg_id = cur.fetchone()[0]
                ctx = {"author_id": author_id, "scope": scope,
                       "scope_key": scope_key, "project_id": project_id,
                       "speaker": speaker}
                for cand, vec in zip(candidates, vecs):
                    cand["_idem_key"] = _idem_key(session_key, msg_id, cand)
                    decision = resolve_candidate(conn, cand, ctx)
                    outcome = _apply_decision(
                        cur, decision, ctx, db_msg_id,
                        to_pgvector(vec) if vec is not None else None)
                    trace["writes"].append(outcome)
                    if outcome["decision"] in ("insert_active", "supersede"):
                        trace["used"].extend(outcome["ids"])
                    else:
                        trace["rejected"].append(outcome)
    finally:
        conn.autocommit = old_autocommit
    return trace
