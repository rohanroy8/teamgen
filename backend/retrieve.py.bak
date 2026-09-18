"""Retrieval — structured lookup + vector top-20, scope-filtered in SQL, reranked.

Scope/privacy filtering happens HERE (SQL + vector query), BEFORE any fact
reaches the answer LLM. A fact outside the caller's scope can never enter the
LLM context, even as the closest embedding match.

Rerank: 0.55*sim + 0.10*exp(-age_days/HALF_LIFE) + 0.15*importance
        + 0.10*confidence + 0.10*log-scaled access.
Similarity dominates: a young irrelevant row must never outrank an older
exact match (recency/importance/confidence only break near-ties).
"""
import math
import re
from datetime import datetime, timezone

from .embeddings import embed, to_pgvector

HALF_LIFE_DAYS = 30.0
VECTOR_TOPK = 20

CURRENT_STATUSES = ("active", "disputed")
HISTORY_STATUSES = ("active", "superseded", "retracted", "disputed")


def _tokens(s: str) -> set[str]:
    # Split into letter/digit runs ("t1pet" -> {t, 1, pet}) + light stemming.
    toks = set()
    for w in re.findall(r"[a-z]+|[0-9]+", (s or "").lower()):
        toks.add(w)
        if len(w) > 3 and w.endswith("s"):  # lives->live
            toks.add(w[:-1])
    return toks


def keyword_sim(question: str, fact_text: str) -> float:
    q = _tokens(question)
    if not q:
        return 0.0
    return len(q & _tokens(fact_text)) / len(q)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def has_access(conn, user_id: str, scope: str, scope_key: str,
               project_id: str | None) -> bool:
    if scope == "personal":
        return scope_key == user_id
    if scope == "project" and project_id:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM memberships
                   WHERE project_id = %s AND user_id = %s AND left_at IS NULL""",
                (project_id, user_id),
            )
            return cur.fetchone() is not None
    return False


def retrieve(conn, *, user_id: str, scope: str, scope_key: str,
             project_id: str | None, question: str,
             as_of: datetime | None = None, limit: int = 20) -> list[dict]:
    """Ranked facts visible to user_id. Empty list on no access or no match."""
    if not has_access(conn, user_id, scope, scope_key, project_id):
        return []
    now = datetime.now(timezone.utc)
    ref = as_of or now
    statuses = HISTORY_STATUSES if as_of else CURRENT_STATUSES

    with conn.cursor() as cur:
        if as_of:
            cur.execute(
                """SELECT m.id::text AS id, m.subject, m.predicate, m.object,
                          m.status, m.epistemic_status, m.confidence, m.importance,
                          m.access_count, m.valid_from, m.valid_to, m.quote,
                          m.embedding, u.username AS author
                   FROM memory m JOIN users u ON u.id = m.author_id
                   WHERE m.user_id = %s AND m.scope = %s
                     AND m.project_id IS NOT DISTINCT FROM %s
                     AND m.status = ANY(%s)
                     AND m.valid_from <= %s
                     AND (m.valid_to IS NULL OR m.valid_to > %s)
                   ORDER BY m.valid_from DESC LIMIT 200""",
                (scope_key, scope, project_id, list(statuses), as_of, as_of),
            )
        else:
            cur.execute(
                """SELECT m.id::text AS id, m.subject, m.predicate, m.object,
                          m.status, m.epistemic_status, m.confidence, m.importance,
                          m.access_count, m.valid_from, m.valid_to, m.quote,
                          m.embedding, u.username AS author
                   FROM memory m JOIN users u ON u.id = m.author_id
                   WHERE m.user_id = %s AND m.scope = %s
                     AND m.project_id IS NOT DISTINCT FROM %s
                     AND m.status = ANY(%s)
                     AND (m.valid_to IS NULL OR m.valid_to > now())
                   ORDER BY m.recorded_at DESC LIMIT 200""",
                (scope_key, scope, project_id, list(statuses)),
            )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Vector channel only for present-time queries: it has no valid-time filter,
    # so it must not leak current facts into as_of (time-travel) results.
    seen = {r["id"] for r in rows}
    qvecs = embed([question]) if not as_of else None
    if qvecs:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT m.id::text AS id, m.subject, m.predicate, m.object,
                          m.status, m.epistemic_status, m.confidence, m.importance,
                          m.access_count, m.valid_from, m.valid_to, m.quote,
                          m.embedding, u.username AS author
                   FROM memory m JOIN users u ON u.id = m.author_id
                   WHERE m.user_id = %s AND m.scope = %s
                     AND m.project_id IS NOT DISTINCT FROM %s
                     AND m.status = ANY(%s)
                     AND (m.valid_to IS NULL OR m.valid_to > now())
                     AND m.embedding IS NOT NULL
                   ORDER BY m.embedding <=> %s::vector LIMIT %s""",
                (scope_key, scope, project_id, list(CURRENT_STATUSES),
                 to_pgvector(qvecs[0]), VECTOR_TOPK),
            )
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                row = dict(zip(cols, r))
                if row["id"] not in seen:
                    rows.append(row)
                    seen.add(row["id"])

    qvec = qvecs[0] if qvecs else None
    scored = []
    for r in rows:
        fact_text = f"{r['subject']} {r['predicate']} {r['object']}"
        sim = keyword_sim(question, fact_text)
        if qvec and r["embedding"] is not None:
            emb = r["embedding"]
            if isinstance(emb, str):  # psycopg2 returns vector columns as text
                emb = [float(x) for x in emb.strip("[]").split(",") if x]
            if len(emb) == len(qvec):
                sim = max(sim, max(0.0, cosine(qvec, emb)))
        age_days = max(0.0, (ref - r["valid_from"]).total_seconds() / 86400.0)
        recency = math.exp(-age_days / HALF_LIFE_DAYS)
        conf = r["confidence"] if r["confidence"] is not None else 0.5
        access = min(1.0, math.log1p(r["access_count"] or 0) / math.log1p(9))
        score = (0.55 * sim + 0.10 * recency + 0.15 * (r["importance"] or 0.5)
                 + 0.10 * conf + 0.10 * access)
        r["sim"], r["score"] = sim, score
        scored.append(r)
    scored.sort(key=lambda r: r["score"], reverse=True)
    top = scored[:limit]

    if top:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE memory SET access_count = access_count + 1,
                       last_accessed = now() WHERE id = ANY(%s::uuid[])""",
                ([r["id"] for r in top],),
            )
        conn.commit()
    for r in top:
        r.pop("embedding", None)
    return top
