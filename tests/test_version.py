"""Phase 4 version-control tests (T12 revert, history chain, digest). Live DB."""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from backend.db import get_conn  # noqa: E402
from backend.version import digest as project_digest  # noqa: E402
from backend.version import history as fact_history  # noqa: E402
from backend.version import revert as fact_revert  # noqa: E402
from backend.write import ingest_text  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def user_id(name: str) -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE username = %s", (name,))
        return cur.fetchone()[0]


ALICE, BOB = user_id("alice"), user_id("bob")


def C(subject, predicate, obj, **kw) -> dict:
    c = {
        "subject": subject, "predicate": predicate, "object": obj,
        "type": "fact", "epistemic_status": "asserted", "override_signal": False,
        "asserted_strength": 0.8, "valid_from": None, "quote": "t",
        "scope_hint": "personal", "is_retraction": False, "is_forget_all": False,
    }
    c.update(kw)
    return c


def ingest(author, skey, text, msg, candidates):
    conn = get_conn()
    try:
        return ingest_text(conn, author_id=author, scope="personal", scope_key=skey,
                           project_id=None, text=text, msg_id=msg,
                           session_key=f"{author}:{skey}", candidates=candidates)
    finally:
        conn.close()


def mem_row(mid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT object, status, supersedes::text FROM memory WHERE id = %s", (mid,))
        return cur.fetchone()


# T12 revert: bad fact supersedes good one; revert restores prior, history grows
def test_t12_revert_restores_prior():
    run = uuid.uuid4().hex[:6]
    skey = ALICE
    pred = f"t12city-{run}"
    ingest(ALICE, skey, "I live in Vienna", f"r1-{run}", [C("me", pred, "Vienna")])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM memory WHERE user_id = %s AND predicate = %s "
            "AND status = 'active'",
            (skey, pred),
        )
        good_id = cur.fetchone()[0]
    bad_trace = ingest(ALICE, skey, "Actually I live in Paris", f"r2-{run}",
                       [C("me", pred, "Paris", epistemic_status="correction",
                           override_signal=True)])
    bad_id = bad_trace["writes"][0]["ids"][0]
    assert mem_row(good_id)[1] == "superseded"

    events_before = len(fact_history(get_conn(), bad_id)["events"])
    conn = get_conn()
    try:
        out = fact_revert(conn, bad_id, ALICE)
    finally:
        conn.close()
    assert out == {"reverted": bad_id, "restored": good_id}
    assert mem_row(bad_id)[1] == "retracted"
    good = mem_row(good_id)
    assert good[1] == "active"  # prior active again
    after = fact_history(get_conn(), bad_id)
    assert len(after["events"]) > events_before  # history grew (reverted event)
    assert {n["object"] for n in after["chain"]} == {"Vienna", "Paris"}


# Seed chain: Hyderabad history length 2 with correct valid_to linkage
def test_history_chain_seed():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM memory WHERE user_id = %s AND predicate = 'lives_in' "
            "AND object = 'Bangalore' AND status = 'active'",
            (ALICE,),
        )
        head = cur.fetchone()[0]
    h = fact_history(get_conn(), head)
    assert [n["object"] for n in h["chain"]] == ["Hyderabad", "Bangalore"]
    hyd, blr = h["chain"]
    assert hyd["status"] == "superseded" and blr["status"] == "active"
    assert hyd["valid_to"] is not None and blr["supersedes"] == hyd["id"]
    assert all(n["author"] == "alice" for n in h["chain"])  # blame, not raw UUIDs


# Revert auth: non-author, non-lead cannot revert someone else's personal fact
def test_revert_forbidden_for_stranger():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id::text FROM memory WHERE user_id = %s AND predicate = 'salary'",
            (ALICE,),
        )
        secret = cur.fetchone()[0]
    conn = get_conn()
    try:
        try:
            fact_revert(conn, secret, BOB)
            assert False, "expected 403"
        except HTTPException as e:
            assert e.status_code == 403
    finally:
        conn.close()


# Digest: added/superseded counts present for a project with seeded history
def test_digest_counts():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM projects WHERE name = 'orca'")
        orca = cur.fetchone()[0]
    d = project_digest(get_conn(), ALICE, orca, 3650)
    assert d["counts"].get("added", 0) >= 1
    assert isinstance(d["counts"], dict)
