# Ledger — PRD (v2, locked)
**Epochesque 2.0, Track 3: "The Assistant That Never Forgets... Or Does It?"**
Team: 2-3 people · Time: ~12 hours · Budget: $0 (free-tier only)

Positioning: *"Most assistants retrieve memories. Ledger maintains state — and can prove why it believes what it tells you."*

> For step-by-step build prompts and phase-by-phase agent instructions, see `ledger-master-workplan.md`. This document is the product/architecture spec — what we're building and why.

---

## 0. The 30-Second Pitch

> Every team's assistant remembers facts — but not when they *change*. Say "we're using MongoDB," then three days later "actually we moved to Postgres," and most memory tools either forget the old fact ever existed or silently overwrite it with no explanation. Ledger doesn't just store what's true — it tracks when it *became* true, when we *learned* it, and why we believe it now. Corrections get versioned, not erased. Disagreements get flagged as disputed, never guessed at. And every answer comes with proof: the exact message, person, and timestamp it came from. That's the difference between an assistant that retrieves memories and one that maintains state.

## 0b. Explain It Like I'm Not Technical

Imagine a team chat where someone says "the deadline is Oct 10," and a week later someone else says "actually it's Oct 3." Most bots either forget the first one entirely, or just quietly swap the answer with no record of the change. Ledger keeps both — it knows the deadline used to be Oct 10, knows exactly when and why it changed to Oct 3, and can show you the receipts if you ask "why do you think that?" If two people disagree and nobody's actually confirmed which is right, Ledger says "these two people disagree" instead of guessing. It's less like a search engine and more like a very organized teammate who remembers not just what everyone said, but *when the story changed and why*.

## 0c. Why This Is The Strongest Version Of This Track

The track names three graded requirements: persistence across sessions, handling contradicting information correctly, and explaining which memory an answer came from. Most teams will treat these as three checkboxes bolted onto a vector-DB chatbot. In Ledger, they're not features — they're the entire structure of the data model:

- **Persistence** isn't "save the vector store" — it's a real SQLite table with a version chain, tested by killing and restarting the actual server process.
- **Contradiction handling** isn't "ask the LLM if this is new" — it's a deterministic rule set that distinguishes an opinion, a correction, and a genuine unresolved dispute *before* any LLM guesswork enters the picture. This is precisely the part the track says will be tested live.
- **Provenance** isn't a footnote — every fact carries the exact message, user, and timestamp it came from, and the UI's "Why this answer?" panel is the primary way we explain the whole system to judges, not an afterthought.

The one thing we don't have that a fancier build might: a knowledge graph, RBAC, or multi-agent orchestration. We deliberately don't need them — see Section 9 (Explicit Cuts) for exactly why, stated in advance so it never looks like something we ran out of time for.

---

## 1. Problem & Constraints

- **Problem**: teams (hackathon/startup/lab/college) constantly change decisions — owners, deadlines, tech stack — and existing memory tools either dump everything into a vector DB (fails the track's own stated bar) or silently overwrite old facts (loses history, can't explain "why").
- **Target user**: a small team that needs one source of truth for "what do we currently believe, and why."
- **Constraints**: zero budget → free-tier APIs only; 12 hours; 2-3 builders; must run without internet-dependent infra beyond the LLM calls.
- **Must work end to end**: persistence across sessions, contradiction → supersession, provenance per answer (all three are graded rules, not optional).
- **Strong-plus (also committed to)**: multi-user isolation, disputed-conflict state, bi-temporal query.
- **Minimum acceptable outcome**: the 6-beat demo script (Section 6) runs live without a human correcting the system.

## 2. Why This Wins (evidence-based, not oversold)

- Naive "vector DB + top-k" fails the track's explicit rule against it — most teams will still build this under time pressure.
- Mem0-style flat-log memory updates without formally invalidating prior versions in the same explainable way a dedicated version chain does — we differ by keeping every old fact inspectable and linked, not just by adding new entries.
- Graphiti/Zep is the real published precedent for bi-temporal fact versioning (Zep's 2025 arXiv paper describes the temporal-knowledge-graph approach) — we borrow the *idea*, not the library, since Graphiti's embedded path needs Python 3.12+ and is pre-1.0, real integration risk for 12h.
- Differentiator claims stay factual: don't claim to be "the only team" doing anything; don't call Graphiti "peer-reviewed" (only Zep's paper is); don't claim Mem0 "can't handle change" (it can, just without the same explainable version chain). Say instead: *"we make conflict resolution explicit and inspectable, rather than hidden inside a general memory framework."*

## 3. Core Data Model (SQLite)

```
facts
------
id
workspace_id          -- isolation boundary
source_user_id        -- resolved server-side from session, never client-supplied
visibility            -- 'private' | 'team'
subject, attribute
fact_key              -- = normalize(subject) + '::' + normalize(attribute); used ONLY to find
                          candidate matches (structured lookup, then Chroma paraphrase fallback) —
                          it never decides truth, the resolver rules do
value
type                  -- fact | decision | task
epistemic_status      -- asserted | correction | proposal | opinion | uncertain
status                -- active | proposed | superseded | disputed | stale | forgotten
valid_from            -- when the fact became true (from message context)
valid_to              -- null if still active
recorded_at           -- when Ledger learned it (ingestion time)
supersedes_id         -- FK, version chain
conflicts_with_id     -- FK, set only when status=disputed
asserted_strength     -- 0-1, how confidently this was actually WORDED (never shown as a bare
                          confidence % in the UI — that's unfalsifiable and invites a judge question
                          we can't cleanly answer)
override_signal       -- bool, extraction flagged correction language ("actually", "confirmed", "moved to")
source_message_id     -- FK → messages.message_id (see below)
expires_at            -- for decay rules (tasks/temporary facts only)

messages
--------
message_id
workspace_id
user_id
text
created_at
```

**Why the split table**: keeping `messages` separate from `facts` means the fact table does one job (current + versioned knowledge) and the message log does the other (raw provenance). The inspector's "Why this answer?" trace becomes a clean walk: `fact → source_message_id → messages row → user + timestamp + original text`.

**Why `status='proposed'` pairs with `epistemic_status='proposal'`**: this is what stops "the newest statement always wins," the single biggest gap in a naive build. An opinion or proposal is recorded but never overwrites active truth — see the resolver rules below.

## 4. Resolution Algorithm (deterministic-first, LLM as fallback only)

Research note: a 2026 paper on memory conflict resolution argues deterministic post-retrieval logic outperforms asking an LLM to track freshness — this directly supports NOT making vector similarity or an LLM call the primary resolver.

```
1. Extract: ONE LLM call → candidate {subject, attribute, value, type, epistemic_status,
   override_signal, valid_from, asserted_strength}

2. fact_key = normalize(subject) + '::' + normalize(attribute)
   Structured lookup: exact fact_key match, scoped to workspace_id + visibility filter
   (team OR same source_user_id)
   → no match: Chroma semantic check (catches paraphrases: "Postgres" vs "we're on Postgres now")
                → still no match: insert new fact
                  (status='active' if epistemic_status=asserted/correction,
                   else status='proposed')

3. If a matching key/paraphrase exists, apply rules in order:
   a. epistemic_status = opinion/proposal/uncertain
        → insert as status=proposed, NEVER overwrites active truth
   b. epistemic_status = correction, OR override_signal = true
        → supersede: old.status=superseded, old.valid_to=now,
          new.status=active, new.supersedes_id=old.id
   c. epistemic_status = asserted, contradicts existing active fact,
      different source_user_id, no override_signal
        → status=disputed on the NEW fact, conflicts_with_id=old.id,
          old fact stays active (unresolved, not overwritten)
   d. same value re-asserted
        → no-op (dedupe)
   e. Only genuinely ambiguous cases that don't fit a-d fall through to ONE LLM judgment call
      (same/update/contradiction/unrelated), then re-apply a-d with that label. This must stay
      the minority path — if it fires often, the extraction prompt needs better few-shot
      coverage, not a bigger fallback branch.

4. Forget command ("forget that X"): mark target status=forgotten, valid_to=now; remove from
   BOTH SQLite active-query results AND the Chroma index (verify this explicitly — a common bug
   is leaving it retrievable via the vector store after "deleting" it from SQL).

5. Decay (computed lazily on read, no background jobs): if type=task and
   now - valid_from > type-specific threshold with no re-confirmation
   → status=stale, excluded from default answers, visible in the inspector.
```

**Normal-path LLM cost is exactly two calls**: one to extract on ingest, one to generate the final answer on query. Rule (e)'s fallback is the only path that can add a third, and it should rarely fire.

## 5. Multi-User Isolation (lightweight, not fake)

- No OAuth. A tiny demo-login endpoint (`POST /login {name}`) returns an in-memory session token mapped server-side to `{user_id, workspace_id}`.
- Every write/query call resolves identity from that token server-side — **never** trust a client-supplied `user_id` field directly; that's the difference between real isolation and a UI dropdown that's trivially spoofable by anyone sending raw JSON.
- Retrieval filter (`workspace_id` + `visibility`) is applied at BOTH the SQL query and the Chroma metadata filter — enforced in exactly two functions, not scattered through the codebase. A private fact must be excluded *before* it reaches the answer-generation LLM call, even when it's the closest embedding match — that's the real privacy test, not just "the answer doesn't mention it."

## 6. API Surface (FastAPI)

- `POST /login` — `{name}` → `{session_token}`
- `POST /workspaces/{id}/messages` — `{text}` (identity from session) → ingest
- `POST /workspaces/{id}/query` — `{question, as_of?: ISO8601}` → `{answer, memory_ids_used, supersede_chain, disputed_flags}`. `as_of` filters on `valid_from`/`valid_to` for the bi-temporal demo beat; omit it for "current truth."
- `GET /workspaces/{id}/memories` — full timeline for the inspector panel (identity-filtered)
- `POST /workspaces/{id}/what-changed` — `{since_timestamp}` → `{added, updated, superseded, resolved, disputed, stale, forgotten}` — broader than just superseded facts
- `POST /eval/run` — runs the fixed test suite (Section 8), returns pass/fail scoreboard

## 7. Free-Tier Stack

| Layer | Choice | Note |
|---|---|---|
| Backend | FastAPI | no infra, fast to stand up |
| Store | SQLite | canonical memory state |
| Semantic index | Chroma (local, embedded, `PersistentClient`) | candidate discovery / paraphrase matching only — never the source of truth |
| Embeddings | local sentence-transformers (all-MiniLM-L6-v2) | free, offline, no rate-limit risk — **download and cache it in hour 0, then verify it loads with wifi off**; this is the top offline-availability risk in the whole build |
| LLM | Gemini 2.5 Flash-Lite (free tier via AI Studio) | primary extraction/answer model |
| Backup LLM | Groq free tier (llama-3.3-70b-versatile) | fallback if Gemini throttles mid-demo — verify current rate limits on the actual demo account, don't assume "unlimited free" |
| Frontend | plain HTML/CSS/JS → FastAPI JSON | no build step, still supports a clean inspector panel |

Treat the LLM as replaceable infrastructure — the product is judged on whether the memory engine is correct, not on model choice. Build behind a small `LLMProvider` interface (Gemini / Groq / local-mock) so the eval suite can run the deterministic resolver tests with zero live API calls.

## 8. Demo Script (6 beats)

1. **Persistence** — "We're using MongoDB." → close/reopen the app → query confirms MongoDB.
2. **Correct** — "Actually we moved to PostgreSQL." → query → PostgreSQL; inspector shows MongoDB superseded.
3. **Why?** — Click "Why PostgreSQL?" → show Memory M042, from Message M183, Alice, Sept 17, override=confirmed, supersedes M019.
4. **Time-travel** — "What did we use on Sept 15?" → MongoDB, with its own valid window shown separately from when we learned it.
5. **Dispute → resolve** — Alice: "deadline is Oct 10." Bob: "I think it's Oct 3." → system shows DISPUTED, refuses to guess. Then: "The client confirmed the deadline is Oct 3." → resolves, Oct 10 superseded.
6. **Privacy + scoreboard** — Alice's private note excluded from Bob's query, proven via the inspector showing it filtered out *before* generation. Close by running the eval suite live on screen.

## 9. Memory Evaluation Suite (16 cases — 12 shown to judges, 4 folded in as adversarial)

**Core 12 (on the scoreboard):**
1. Persistence across a real process restart (not same-process save/load)
2. Direct correction (override_signal=true) → supersede
3. Genuine contradiction, no override signal, different users → disputed
4. Paraphrase dedupe ("Postgres" = "we're on Postgres now")
5. Duplicate exact re-assertion → no-op
6. Historical/`as_of` query ("what was true on day 1")
7. Provenance returned for every answer (memory_id + timestamp + source)
8. Explicit forget → excluded from SQLite AND Chroma
9. Private fact never appears in another user's answer or inspector
10. Cross-workspace query returns empty (no leakage)
11. Opinion/proposal never overwrites active truth
12. Stale task excluded from default answer, visible in inspector

**Additional 4 (adversarial, folded into the same scoreboard):**
13. Private fact excluded even when it's the closest Chroma embedding match
14. Cross-workspace leakage attempted via multiple phrasings, all blocked
15. Bi-temporal distinction holds for both "what was true on X" and "when did we learn this"
16. Malformed/nonsense input doesn't crash extraction or insert garbage facts

## 10. Explicit Cuts (do not build)

- **Actor authority / role hierarchy** (e.g. `project_lead > team_member`). The scenario it would fix — an unhedged "I think X" shouldn't override an existing fact — is already handled: `epistemic_status='uncertain'` inserts as `status='proposed'`, which by rule (a) never touches active truth. Adding a role field means new schema, a login-flow change, a new resolver branch, and a new test — for a case the design already gets right. If challenged live: *"an uncorroborated assertion creates a dispute, not a supersession — only explicit correction language tied to a confirmed source overrides."*
- Graphiti/Neo4j/FalkorDB · full RBAC/auth · Postgres · voice · document ingestion · Slack/Discord integration · multi-agent orchestration · ML-based decay modeling · more than ~16 eval cases · a numeric "confidence %" as a headline UI element (show status/source/evidence instead — a bare percentage is unfalsifiable and a judge will ask what it means).

## 11. Judging-Rubric Map

| Criterion | Weight | Evidence in this build |
|---|---|---|
| Problem Depth | 25% | Real team-decision-drift problem, not "remembers your name" |
| Technical Execution | 25% | Deterministic resolver + working end-to-end, restart-tested persistence, 16-case eval suite as proof |
| Rule Compliance | 20% | Contradiction handling, provenance, multi-user isolation are the literal feature set |
| Edge Case Handling | 15% | Dispute state, forget verification, cross-workspace/private-leak tests rehearsed live |
| Explanation & Demo | 15% | Inspector panel + scoreboard *is* the explanation; team can explain every line of their own resolver in one sentence: "five states, everything else is UI around it" |
