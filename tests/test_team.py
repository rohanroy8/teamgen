"""Phase 5 team-governance tests (T9 PR flow, conflict resolve paths). Live DB."""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from backend.db import get_conn  # noqa: E402
from backend.retrieve import retrieve  # noqa: E402
from backend.team import decide_proposal, list_conflicts, resolve_conflict  # noqa: E402
from backend.write import ingest_text  # noqa: E402


def user_id(name: str) -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE username = %s", (name,))
        return cur.fetchone()[0]


def project_id(name: str) -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM projects WHERE name = %s", (name,))
        return cur.fetchone()[0]


ALICE, BOB = user_id("alice"), user_id("bob")
ORCA = project_id("orca")


def C(subject, predicate, obj, **kw) -> dict:
    c = {
        "subject": subject, "predicate": predicate, "object": obj,
        "type": "decision", "epistemic_status": "asserted", "override_signal": False,
        "asserted_strength": 0.85, "valid_from": None, "quote": "t",
        "scope_hint": "project", "is_retraction": False, "is_forget_all": False,
    }
    c.update(kw)
    return c


def ingest(author, text, msg, candidates):
    conn = get_conn()
    try:
        return ingest_text(conn, author_id=author, scope="project", scope_key=ORCA,
                           project_id=ORCA, text=text, msg_id=msg,
                           session_key=f"{author}:{ORCA}", candidates=candidates)
    finally:
        conn.close()


def status_of(mid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM memory WHERE id = %s", (mid,))
        return cur.fetchone()[0]


def pin_as_alice(subject, predicate, obj):
    """Direct pinned insert (lead-only pin toggle UI lands in Phase 6)."""
    from backend.embeddings import embed, to_pgvector
    from backend.resolve import fact_key

    vec = to_pgvector(embed([f"{subject} {predicate} {obj}"])[0])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO memory (author_id, user_id, project_id, scope, subject,
                predicate, object, fact_key, type, is_pinned, idempotency_key,
                embedding, confidence)
               VALUES (%s,%s,%s,'project',%s,%s,%s,%s,'decision',true,%s,%s::vector,0.95)
               RETURNING id::text""",
            (ALICE, ORCA, ORCA, subject, predicate, obj,
             fact_key(subject, predicate), f"t9pin:{uuid.uuid4().hex[:8]}", vec),
        )
        return cur.fetchone()[0]


# T9 PR: member contradicts pinned fact -> proposed (invisible); approve flips it.
# Also asserts the real GCP seed pin is intact (read-only).
def test_t9_pr_flow():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT object, status, is_pinned FROM memory "
            "WHERE project_id = %s AND predicate = 'cloud' AND status = 'active'",
            (ORCA,),
        )
        assert cur.fetchone() == ("GCP", "active", True)
    run = uuid.uuid4().hex[:6]
    pred = f"t9ci-{run}"
    pin_as_alice("orca", pred, "CircleCI")
    trace = ingest(BOB, f"we use {pred} GitHub Actions", f"t9-{run}",
                   [C("orca", pred, "GitHub Actions")])
    w = trace["writes"][0]
    assert w["decision"] == "insert_proposed", w
    prop_id = w["ids"][0]
    assert status_of(prop_id) == "proposed"

    # Retrieval still returns the pinned value; proposal invisible.
    # (Filter to this run's predicate: prior runs' approved rows share tokens.)
    facts = retrieve(get_conn(), user_id=ALICE, scope="project", scope_key=ORCA,
                     project_id=ORCA, question=f"which {pred} do we use?")
    got = {f["object"] for f in facts if f["predicate"] == pred}
    assert "CircleCI" in got and "GitHub Actions" not in got

    # Approve (alice, owner): proposal active, pinned superseded.
    conn = get_conn()
    try:
        out = decide_proposal(conn, ALICE, prop_id, True)
    finally:
        conn.close()
    assert out["status"] == "active"
    assert status_of(prop_id) == "active"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM memory WHERE project_id = %s AND predicate = %s "
            "AND object = 'CircleCI'",
            (ORCA, pred),
        )
        assert cur.fetchone()[0] == "superseded"
    facts = retrieve(get_conn(), user_id=ALICE, scope="project", scope_key=ORCA,
                     project_id=ORCA, question=f"which {pred} do we use?")
    mine = [f for f in facts if f["predicate"] == pred]
    assert mine and (mine[0]["object"], mine[0]["status"]) == ("GitHub Actions", "active")


# T8 resolve accept_both keeps both active; conflict -> accepted_both.
def test_t8_resolve_accept_both():
    subj = f"t5rel-{uuid.uuid4().hex[:6]}"
    run = uuid.uuid4().hex[:6]
    ingest(ALICE, "date is Friday", f"a-{run}", [C(subj, "date", "Friday")])
    trace = ingest(BOB, "date is Monday", f"b-{run}", [C(subj, "date", "Monday")])
    conflict_id = trace["writes"][0]["conflict_id"]
    conn = get_conn()
    try:
        out = resolve_conflict(conn, ALICE, conflict_id, "accept_both",
                               note="both teams keep their dates")
    finally:
        conn.close()
    assert out["status"] == "accepted_both"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT object, status FROM memory WHERE subject = %s ORDER BY object",
            (subj,),
        )
        assert cur.fetchall() == [("Friday", "active"), ("Monday", "active")]
        cur.execute("SELECT status FROM conflicts WHERE id = %s", (conflict_id,))
        assert cur.fetchone()[0] == "accepted_both"


# Winner path: one side superseded, chain linked, conflict resolved.
def test_resolve_winner():
    subj = f"t5win-{uuid.uuid4().hex[:6]}"
    run = uuid.uuid4().hex[:6]
    ingest(ALICE, "venue is Hall A", f"a-{run}", [C(subj, "venue", "Hall A")])
    trace = ingest(BOB, "venue is Hall B", f"b-{run}", [C(subj, "venue", "Hall B")])
    conflict_id = trace["writes"][0]["conflict_id"]
    inbox = list_conflicts(get_conn(), ALICE, ORCA)
    assert conflict_id in {c["id"] for c in inbox if c["status"] == "open"}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM memory WHERE subject = %s AND object = 'Hall A'",
                    (subj,))
        hall_a = cur.fetchone()[0]
    conn = get_conn()
    try:
        out = resolve_conflict(conn, ALICE, conflict_id, hall_a, note="booked already")
    finally:
        conn.close()
    assert out == {"conflict_id": conflict_id, "status": "resolved", "winner_id": hall_a}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT object, status FROM memory WHERE subject = %s ORDER BY object",
                    (subj,))
        assert cur.fetchall() == [("Hall A", "active"), ("Hall B", "superseded")]
