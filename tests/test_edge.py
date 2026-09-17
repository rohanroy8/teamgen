"""Phase 7 hardening edge tests. Live DB, isolated scopes/users."""
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

os.environ["TEAMGEN_OFFLINE"] = "1"

from backend.answer import answer_question  # noqa: E402
from backend.db import get_conn  # noqa: E402
from backend.extract import extract_candidates  # noqa: E402
from backend.llm_provider import (  # noqa: E402
    FailoverProvider,
    LLMError,
    MockProvider,
)
from backend.retrieve import retrieve  # noqa: E402
from backend.write import ingest_text  # noqa: E402


def get_or_create_user(username: str, display: str) -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            "INSERT INTO users (username, display_name, password_hash) "
            "VALUES (%s,%s,'!') RETURNING id::text",
            (username, display),
        )
        return cur.fetchone()[0]


def C(subject, predicate, obj, **kw) -> dict:
    c = {
        "subject": subject, "predicate": predicate, "object": obj,
        "type": "fact", "epistemic_status": "asserted", "override_signal": False,
        "asserted_strength": 0.8, "valid_from": None, "quote": "t",
        "scope_hint": "personal", "is_retraction": False, "is_forget_all": False,
    }
    c.update(kw)
    return c


def auto_ingest(author, skey, text, msg, project=None, candidates=None):
    conn = get_conn()
    try:
        scope = "project" if project else "personal"
        return ingest_text(conn, author_id=author, scope=scope,
                           scope_key=skey, project_id=project, text=text,
                           msg_id=msg, session_key=f"{author}:{skey}",
                           candidates=candidates)
    finally:
        conn.close()


# Empty user, zero memories -> graceful don't-know, no crash, no ids.
def test_edge_empty_user_graceful():
    uid = get_or_create_user(f"edge_empty_{uuid.uuid4().hex[:6]}", "Edge Empty")
    facts = retrieve(get_conn(), user_id=uid, scope="personal", scope_key=uid,
                     project_id=None, question="what do you remember about me?")
    assert facts == []
    ans = answer_question("what do you remember about me?", facts)
    assert "don't know" in ans["answer"].lower() and ans["used_ids"] == []


# Same display name, different user_id -> fully isolated scopes.
def test_edge_same_name_isolation():
    tag = uuid.uuid4().hex[:6]
    a = get_or_create_user(f"edge_a_{tag}", "Edge Same")
    b = get_or_create_user(f"edge_b_{tag}", "Edge Same")
    auto_ingest(a, a, "My secret code is zebra", f"s-{tag}",
                candidates=[C("me", f"edge_secret_{tag}", "zebra")])
    # B cannot see A's scope, and B's own queries never surface A's rows.
    assert retrieve(get_conn(), user_id=b, scope="personal", scope_key=a,
                    project_id=None, question="secret code?") == []
    mine = retrieve(get_conn(), user_id=b, scope="personal", scope_key=b,
                    project_id=None, question="secret code?")
    assert all(f["subject"] != "me" or tag not in f["predicate"] for f in mine)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM memory WHERE user_id = %s AND predicate = %s",
            (b, f"edge_secret_{tag}"),
        )
        assert cur.fetchone()[0] == 0


# 200-message session: small talk stored as messages, but zero greeting memories.
def test_edge_200msg_session_only_facts():
    uid = get_or_create_user(f"edge_bulk_{uuid.uuid4().hex[:6]}", "Edge Bulk")
    skey = uid
    smalltalk = ["hello", "thanks!", "ok", "good morning", "hey there", "thx",
                 "what time is it?", "if I moved to Mars, would I weigh less?"]
    for i in range(190):
        auto_ingest(uid, skey, smalltalk[i % len(smalltalk)], f"bulk-{i}")
    auto_ingest(uid, skey, "My ship is called Aurora", "bulk-fact",
                candidates=[C("me", f"edge_ship_{skey[-6:]}", "Aurora")])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM memory
               WHERE user_id = %s AND (quote ILIKE '%%hello%%' OR quote ILIKE '%%thanks%%'
                 OR object ILIKE '%%hello%%' OR object ILIKE '%%thanks%%')""",
            (skey,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM messages WHERE author_id = %s", (uid,))
        assert cur.fetchone()[0] >= 190  # chatter preserved as provenance
        cur.execute(
            "SELECT count(*) FROM memory WHERE user_id = %s", (skey,))
        assert cur.fetchone()[0] == 1  # only the fact


# Tool failure degrades gracefully: failover fires, raising providers fall back.
def test_edge_tool_failover_and_fallback():
    class Boom(MockProvider):
        name = "boom"

        def generate(self, prompt: str) -> str:
            raise LLMError("simulated outage")

    fo = FailoverProvider(Boom(), MockProvider(['[{"answer": "fine"}]']))
    assert fo.generate("hi") == '[{"answer": "fine"}]'

    # A raising provider inside extraction falls back to deterministic regex.
    cands = extract_candidates("My editor is helix", provider=Boom())
    assert len(cands) == 1 and cands[0]["predicate"] == "editor"

    # Total outage + unparseable text -> no facts, no crash, no write.
    cands = extract_candidates("blorpt wibble ???", provider=Boom())
    assert cands == []


# No greeting-only content anywhere in the memory table.
def test_edge_no_greeting_memories():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM memory
               WHERE subject ILIKE '%%hello%%' OR subject ILIKE '%%thanks%%'
                  OR predicate ILIKE '%%hello%%' OR predicate ILIKE '%%thanks%%'
                  OR object ILIKE '%%hello%%' OR object ILIKE '%%thanks%%'""")
        assert cur.fetchone()[0] == 0
