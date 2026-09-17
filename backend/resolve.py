"""Resolver — merged M4 rules (Ledger a-e + cardinality + pinned-PR exception).

resolve_candidate() reads live rows and returns a decision; write.py applies it
transactionally. Scope/visibility filtering happens HERE (SQL) — never in prompts.
"""
from .embeddings import embed, to_pgvector

MULTI_VALUED = {"likes", "enjoys", "hobbies", "interests", "skills", "languages"}

_ROLE_RANK = {"owner": 4, "lead": 3, "member": 2, "viewer": 1}

# Roles allowed to directly contradict a pinned fact (pinner-role tracking
# lands in Phase 5 if needed; until then owner/lead may, others go to PR).
_PIN_DIRECT_ROLES = {"owner", "lead"}


def norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def fact_key(subject: str, predicate: str) -> str:
    return f"{norm(subject)}::{norm(predicate)}"


def author_role(conn, project_id: str | None, author_id: str) -> str | None:
    if not project_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """SELECT role FROM memberships
               WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
            (project_id, author_id),
        )
        row = cur.fetchone()
        return row[0] if row else None


def find_active(conn, scope_key: str, scope: str, project_id: str | None,
                fkey: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id::text AS id, author_id::text AS author_id, subject, predicate,
                      object, is_pinned, epistemic_status
               FROM memory
               WHERE user_id = %s AND scope = %s
                 AND project_id IS NOT DISTINCT FROM %s
                 AND fact_key = %s AND status = 'active'
               ORDER BY recorded_at DESC""",
            (scope_key, scope, project_id, fkey),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def find_vector_matches(conn, scope_key: str, scope: str, project_id: str | None,
                        text: str, exclude_ids: list[str],
                        threshold: float = 0.85) -> list[dict]:
    vecs = embed([text])
    if not vecs:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id::text AS id, author_id::text AS author_id, subject, predicate,
                      object, is_pinned, epistemic_status,
                      1 - (embedding <=> %s::vector) AS sim
               FROM memory
               WHERE user_id = %s AND scope = %s
                 AND project_id IS NOT DISTINCT FROM %s
                 AND status = 'active' AND embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector LIMIT 5""",
            (to_pgvector(vecs[0]), scope_key, scope, project_id, to_pgvector(vecs[0])),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return [r for r in rows if r["id"] not in set(exclude_ids) and r["sim"] >= threshold]


def find_retraction_targets(conn, scope_key: str, scope: str,
                            project_id: str | None, words: list[str]) -> list[dict]:
    if not words:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id::text AS id, subject, predicate, object
               FROM memory
               WHERE user_id = %s AND scope = %s
                 AND project_id IS NOT DISTINCT FROM %s AND status = 'active'""",
            (scope_key, scope, project_id),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    words = set(words)

    def toks(s: str) -> set[str]:
        return set(norm(s).split())

    hits = []
    for r in rows:
        p, s = toks(r["predicate"]), toks(r["subject"])
        if (p and p <= words) or (s and s <= words) \
                or norm(r["predicate"]) in words or norm(r["subject"]) in words:
            hits.append(r)
    return hits


def resolve_candidate(conn, cand: dict, ctx: dict) -> dict:
    """ctx: {author_id, scope, scope_key, project_id}. Returns a decision dict."""
    scope, scope_key, project_id = ctx["scope"], ctx["scope_key"], ctx["project_id"]
    author_id = ctx["author_id"]

    if cand.get("is_forget_all"):
        return {"decision": "forget_all", "candidate": cand, "reason": "explicit forget-all command"}

    if cand.get("is_retraction"):
        targets = find_retraction_targets(
            conn, scope_key, scope, project_id, cand.get("_retract_words", []))
        if targets:
            return {"decision": "retract", "targets": targets,
                    "candidate": cand, "reason": "targeted forget -> retract"}
        return {"decision": "noop", "candidate": cand, "reason": "retraction with no match"}

    fkey = fact_key(cand["subject"], cand["predicate"])
    cand["_fact_key"] = fkey
    matched = find_active(conn, scope_key, scope, project_id, fkey)
    if not matched:
        vec_hits = find_vector_matches(
            conn, scope_key, scope, project_id,
            f"{cand['subject']} {cand['predicate']} {cand['object']}", [])
        matched = [{k: h[k] for k in ("id", "author_id", "subject", "predicate",
                                      "object", "is_pinned", "epistemic_status")}
                   for h in vec_hits]
    if not matched:
        if cand["epistemic_status"] in ("opinion", "proposal", "uncertain"):
            return {"decision": "insert_proposed", "candidate": cand,
                    "reason": "rule a (no existing fact, hedged)"}
        return {"decision": "insert_active", "candidate": cand,
                "reason": "no match -> new fact"}

    epistemic = cand["epistemic_status"]
    # (d) duplicate: same value already active -> evidence++, no new row
    same_value = [m for m in matched if norm(m["object"]) == norm(cand["object"])]
    if same_value:
        return {"decision": "noop", "targets": same_value, "candidate": cand,
                "reason": "rule d (duplicate re-assertion)"}
    # Pinned-first (Phase 5 PR gate): ANY contradiction of a pinned fact by an
    # author without direct-pin rights becomes a proposal, before rules a-c.
    # Duplicates (above) are exempt; hedged rule (a) already yields proposed.
    pinned = [m for m in matched if m["is_pinned"]]
    if pinned and norm(pinned[0]["object"]) != norm(cand["object"]):
        role = author_role(conn, project_id, author_id)
        if role not in _PIN_DIRECT_ROLES:
            return {"decision": "insert_proposed", "targets": [pinned[0]],
                    "candidate": cand,
                    "reason": "pinned target, insufficient role -> Memory PR"}
    # (a) hedged -> proposed, never touches truth
    if epistemic in ("opinion", "proposal", "uncertain"):
        return {"decision": "insert_proposed", "candidate": cand,
                "reason": "rule a (hedged, existing fact untouched)"}

    target = matched[0]
    multi = norm(cand["predicate"]) in MULTI_VALUED
    same_author = target["author_id"] == author_id

    # (b) correction/override, or same-author update of a single-valued fact
    if cand.get("override_signal") or epistemic == "correction" or (same_author and not multi):
        if target["is_pinned"]:
            role = author_role(conn, project_id, author_id)
            if role not in _PIN_DIRECT_ROLES:
                return {"decision": "insert_proposed", "targets": [target],
                        "candidate": cand,
                        "reason": "pinned target, insufficient role -> Memory PR"}
        return {"decision": "supersede", "targets": [target], "candidate": cand,
                "reason": "rule b (correction/override/same-author update)"}

    # (c) cross-author asserted contradiction
    if not same_author:
        if multi:
            return {"decision": "insert_active", "candidate": cand,
                    "reason": "rule c multi-valued -> keep both, no conflict"}
        return {"decision": "disputed", "targets": [target], "candidate": cand,
                "reason": "rule c (cross-author contradiction -> disputed)"}

    # (e) fallback default: unrelated new value, same author, multi-valued
    if multi:
        return {"decision": "insert_active", "candidate": cand,
                "reason": "rule e default (multi-valued new value)"}
    return {"decision": "supersede", "targets": [target], "candidate": cand,
            "reason": "rule e default (single-valued update)"}
