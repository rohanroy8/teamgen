"""Phase 2 write-path tests (T2,T3,T4,T5,T6,T14). Live DB, isolated scopes.

Each test uses a unique scope_key so no cleanup is needed (append-only memory
is never deleted, even by tests).
"""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

# Phase 2 tests exercise the OFFLINE fallback extractor: force no-provider even
# if keys ever appear in the environment.
for _k in ("LLM_PROVIDER", "GEMINI_API_KEY", "GROQ_API_KEY"):
    os.environ.pop(_k, None)

from backend.db import get_conn  # noqa: E402
from backend.extract import extract_fallback  # noqa: E402
from backend.write import ingest_text  # noqa: E402


def get_test_user() -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE username = 'testwriter'")
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash) "
            "VALUES ('testwriter','Test Writer','!') RETURNING id::text"
        )
        return cur.fetchone()[0]


AUTHOR = get_test_user()


def scope() -> str:
    return f"test:{uuid.uuid4().hex[:8]}"


def C(subject, predicate, obj, **kw) -> dict:
    c = {
        "subject": subject, "predicate": predicate, "object": obj,
        "type": "fact", "epistemic_status": "asserted", "override_signal": False,
        "asserted_strength": 0.8, "valid_from": None, "quote": "t",
        "scope_hint": "personal", "is_retraction": False, "is_forget_all": False,
    }
    c.update(kw)
    return c


def ingest(skey, text, msg, candidates):
    # ingest_text owns its transaction: pass an un-entered connection.
    conn = get_conn()
    try:
        return ingest_text(conn, author_id=AUTHOR, scope="personal",
                           scope_key=skey, project_id=None, text=text,
                           msg_id=msg, session_key=f"{AUTHOR}:{skey}",
                           candidates=candidates)
    finally:
        conn.close()


def ingest_auto(skey, text, msg, candidates=None):
    conn = get_conn()
    try:
        return ingest_text(conn, author_id=AUTHOR, scope="personal",
                           scope_key=skey, project_id=None, text=text,
                           msg_id=msg, session_key=f"{AUTHOR}:{skey}",
                           candidates=candidates)
    finally:
        conn.close()


def rows(skey, predicate):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id::text, object, status, supersedes::text
               FROM memory WHERE user_id = %s AND predicate = %s ORDER BY recorded_at""",
            (skey, predicate),
        )
        return cur.fetchall()


# T2 supersede: Hyd then Blr => old superseded, new.supersedes = old.id
def test_t2_supersede():
    s = scope()
    ingest(s, "I live in Hyderabad", "m1", [C("me", "lives_in", "Hyderabad")])
    ingest(s, "I moved to Bangalore", "m2",
           [C("me", "lives_in", "Bangalore", epistemic_status="correction",
               override_signal=True)])
    r = rows(s, "lives_in")
    assert len(r) == 2
    old, new = r[0], r[1]
    assert old[1] == "Hyderabad" and old[2] == "superseded"
    assert new[1] == "Bangalore" and new[2] == "active" and new[3] == old[0]


# T3 multi: likes tea + likes coffee => both active, no conflict
def test_t3_multi_valued():
    s = scope()
    ingest(s, "I like tea", "m1", [C("me", "likes", "tea")])
    ingest(s, "I like coffee", "m2", [C("me", "likes", "coffee")])
    r = rows(s, "likes")
    assert sorted([x[1] for x in r]) == ["coffee", "tea"]
    assert all(x[2] == "active" for x in r)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM conflicts WHERE project_id IS NULL")
        # project-less personal scopes never open conflict rows here; just ensure
        # these two memories are not linked as conflicts
        cur.execute(
            """SELECT count(*) FROM memory
               WHERE user_id = %s AND conflicts_with_id IS NOT NULL""", (s,))
        assert cur.fetchone()[0] == 0


# T4 hypothetical: "if I moved..." => 0 new rows
def test_t4_hypothetical_skipped():
    assert extract_fallback("If I moved to the US, I would buy a car") == []
    s = scope()
    trace = ingest_auto(s, "If I moved to the US, I would buy a car", "m1")
    assert trace["writes"] == []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE user_id = %s", (s,))
        assert cur.fetchone()[0] == 0


# T5 attribution: friend's fact is not attributed to the user
def test_t5_attribution():
    cands = extract_fallback("My friend lives in Delhi")
    assert len(cands) == 1
    assert cands[0]["subject"] == "friend"
    assert cands[0]["subject"] != "me"
    s = scope()
    ingest(s, "My friend lives in Delhi", "m1", cands)
    r = rows(s, "lives_in")
    assert len(r) == 1 and r[0][1].lower() == "delhi"


# T6 retract: "forget my old number" => status=retracted
def test_t6_retract():
    s = scope()
    ingest(s, "My number is 555-1234", "m1", [C("me", "number", "555-1234")])
    assert rows(s, "number")[0][2] == "active"
    trace = ingest_auto(s, "forget my old number", "m2")
    assert trace["writes"][0]["decision"] == "retract"
    assert rows(s, "number")[0][2] == "retracted"


# T14 idempotency: same msg_id twice => 1 row
def test_t14_idempotent_replay():
    s = scope()
    c = [C("me", "editor", "vim")]
    ingest(s, "My editor is vim", "dup1", c)
    trace = ingest_auto(s, "My editor is vim", "dup1", [C("me", "editor", "vim")])
    assert trace["writes"] == []
    assert len(rows(s, "editor")) == 1
