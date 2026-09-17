"""Seed demo data — idempotent (looks up UUIDs, skips existing idempotency_keys).

Users: alice/lead, bob/member, charlie/new — password `demo123` for all.
Projects: orca (alice owner, bob member), phoenix (alice owner).
Memory chain: Hyderabad superseded->Bangalore (alice), GCP pinned project fact,
old Hinglish task pref, alice personal secret (leak test).
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from backend.auth import hash_password, normalize_username  # noqa: E402
from backend.db import get_conn  # noqa: E402

DEMO_PASSWORD = "demo123"
DIM = 768


def norm(s: str) -> str:
    return " ".join(s.strip().lower().split())


def fact_key(subject: str, predicate: str) -> str:
    return f"{norm(subject)}::{norm(predicate)}"


def vec(seed: str) -> str:
    rng = random.Random("teamgen:" + seed)
    return "[" + ",".join(f"{rng.uniform(-1, 1):.6f}" for _ in range(DIM)) + "]"


def get_or_create_user(cur, username: str, display: str) -> str:
    username = normalize_username(username)
    cur.execute("SELECT id::text AS id FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO users (username, display_name, password_hash) VALUES (%s,%s,%s) "
        "RETURNING id::text",
        (username, display, hash_password(DEMO_PASSWORD)),
    )
    return cur.fetchone()[0]


def get_or_create_project(cur, name: str, owner_id: str) -> str:
    cur.execute("SELECT id::text AS id FROM projects WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO projects (name, owner_id) VALUES (%s,%s) RETURNING id::text",
        (name, owner_id),
    )
    return cur.fetchone()[0]


def ensure_member(cur, project_id: str, user_id: str, role: str):
    cur.execute(
        """INSERT INTO memberships (project_id, user_id, role) VALUES (%s,%s,%s)
           ON CONFLICT (project_id, user_id) DO UPDATE SET role = EXCLUDED.role""",
        (project_id, user_id, role),
    )


def add_message(cur, project_id: str | None, author_id: str, text: str,
                created_at: str | None = None) -> str:
    if created_at:
        cur.execute(
            "INSERT INTO messages (project_id, author_id, text, created_at) "
            "VALUES (%s,%s,%s,%s) RETURNING id::text",
            (project_id, author_id, text, created_at),
        )
    else:
        cur.execute(
            "INSERT INTO messages (project_id, author_id, text) VALUES (%s,%s,%s) "
            "RETURNING id::text",
            (project_id, author_id, text),
        )
    return cur.fetchone()[0]


def add_memory(cur, *, idem: str, author_id: str, scope: str, scope_key: str,
               project_id: str | None, subject: str, predicate: str, obj: str,
               type_: str = "fact", epistemic: str = "asserted", override: bool = False,
               status: str = "active", valid_from: str | None = None,
               valid_to: str | None = None, pinned: bool = False,
               msg_id: str | None = None, quote: str | None = None,
               supersedes: str | None = None) -> str | None:
    cur.execute("SELECT id::text AS id FROM memory WHERE idempotency_key = %s", (idem,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO memory (author_id, user_id, project_id, scope, subject, predicate,
            object, fact_key, type, epistemic_status, override_signal, status,
            valid_from, valid_to, supersedes, is_pinned, idempotency_key,
            embedding, source_message_id, quote, confidence)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                   COALESCE(%s, now()),%s,%s,%s,%s,%s::vector,%s,%s,0.9)
           RETURNING id::text""",
        (author_id, scope_key, project_id, scope, subject, predicate, obj,
         fact_key(subject, predicate), type_, epistemic, override, status,
         valid_from, valid_to, supersedes, pinned, idem, vec(idem), msg_id, quote),
    )
    new_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO memory_event (memory_id, action, actor_id, detail) "
        "VALUES (%s,%s,%s,%s::jsonb)",
        (new_id, "added", author_id, '{"via":"seed"}'),
    )
    if supersedes:
        cur.execute(
            """UPDATE memory SET status='superseded', valid_to=%s, superseded_by=%s
               WHERE id=%s""",
            (valid_from, new_id, supersedes),
        )
        cur.execute(
            "INSERT INTO memory_event (memory_id, action, actor_id, detail) "
            "VALUES (%s,'superseded',%s,%s::jsonb)",
            (supersedes, author_id, '{"via":"seed"}'),
        )
    return new_id


def main() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            alice = get_or_create_user(cur, "alice", "Alice Lead")
            bob = get_or_create_user(cur, "bob", "Bob Member")
            charlie = get_or_create_user(cur, "charlie", "Charlie New")
            orca = get_or_create_project(cur, "orca", alice)
            phoenix = get_or_create_project(cur, "phoenix", alice)
            ensure_member(cur, orca, alice, "owner")
            ensure_member(cur, orca, bob, "member")
            ensure_member(cur, phoenix, alice, "owner")

            # 1. Backdated chain: Hyderabad (superseded) -> Bangalore (active), by alice
            m1 = add_message(cur, None, alice, "I live in Hyderabad", "2026-01-15T10:00:00+00:00")
            old = add_memory(cur, idem="seed:alice:lives_in:hyd", author_id=alice,
                             scope="personal", scope_key=alice, project_id=None,
                             subject="alice", predicate="lives_in", obj="Hyderabad",
                             valid_from="2026-01-15T10:00:00+00:00", msg_id=m1,
                             quote="I live in Hyderabad")
            m2 = add_message(cur, None, alice, "Actually I moved to Bangalore",
                             "2026-06-01T10:00:00+00:00")
            add_memory(cur, idem="seed:alice:lives_in:blr", author_id=alice,
                       scope="personal", scope_key=alice, project_id=None,
                       subject="alice", predicate="lives_in", obj="Bangalore",
                       epistemic="correction", override=True,
                       valid_from="2026-06-01T10:00:00+00:00", msg_id=m2,
                       quote="Actually I moved to Bangalore", supersedes=old)

            # 2. GCP pinned project fact (orca)
            m3 = add_message(cur, orca, alice, "Team decision: we deploy on GCP")
            add_memory(cur, idem="seed:orca:stack:gcp", author_id=alice,
                       scope="project", scope_key=orca, project_id=orca,
                       subject="orca", predicate="cloud", obj="GCP",
                       type_="decision", pinned=True, msg_id=m3,
                       quote="Team decision: we deploy on GCP")

            # 3. Old Hinglish task pref (decay candidate)
            m4 = add_message(cur, None, alice, "Reply to me in Hinglish",
                             "2025-06-01T10:00:00+00:00")
            add_memory(cur, idem="seed:alice:pref:hinglish", author_id=alice,
                       scope="personal", scope_key=alice, project_id=None,
                       subject="alice", predicate="reply_language", obj="Hinglish",
                       valid_from="2025-06-01T10:00:00+00:00", msg_id=m4,
                       quote="Reply to me in Hinglish")

            # 4. Alice personal secret (leak test — bob must never see this)
            m5 = add_message(cur, None, alice, "My salary is 42LPA, keep it private")
            add_memory(cur, idem="seed:alice:secret:salary", author_id=alice,
                       scope="personal", scope_key=alice, project_id=None,
                       subject="alice", predicate="salary", obj="42LPA",
                       msg_id=m5, quote="My salary is 42LPA, keep it private")

            # 5. Bob team fact so project queries have multi-author data
            m6 = add_message(cur, orca, bob, "Our standup is at 10am")
            add_memory(cur, idem="seed:orca:standup:10am", author_id=bob,
                       scope="project", scope_key=orca, project_id=orca,
                       subject="orca", predicate="standup", obj="10am",
                       msg_id=m6, quote="Our standup is at 10am")

            # 6. Orca deadline decision (sets up dispute->resolve demo beats)
            m7 = add_message(cur, orca, alice, "Deadline is Oct 10")
            add_memory(cur, idem="seed:orca:deadline:oct10", author_id=alice,
                       scope="project", scope_key=orca, project_id=orca,
                       subject="orca", predicate="deadline", obj="Oct 10",
                       type_="decision", msg_id=m7,
                       quote="Deadline is Oct 10")

            # 7. Bob personal pref (multi-author personal isolation data)
            m8 = add_message(cur, None, bob, "My editor is vim")
            add_memory(cur, idem="seed:bob:editor:vim", author_id=bob,
                       scope="personal", scope_key=bob, project_id=None,
                       subject="bob", predicate="editor", obj="vim",
                       msg_id=m8, quote="My editor is vim")

    print(f"seed ok: alice={alice} bob={bob} charlie={charlie} orca={orca} phoenix={phoenix}")
    print(f"demo logins — alice/{DEMO_PASSWORD}, bob/{DEMO_PASSWORD}, charlie/{DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
