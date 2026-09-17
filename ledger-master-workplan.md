# LEDGER — Master Workplan (LOCKED v1)
### Epochesque 2.0, Track 3 · Team 2-3 · 12 hours · $0 budget

---

## 0. How To Use This Document

This is the **single source of truth**. If you paste this into Claude Code, Cursor, ChatGPT, or any other agent, paste the **whole file** as context before giving it a phase-specific prompt from Section 9. Rules for any agent working from this doc:

1. **Do not deviate from the schema in Section 2 or the algorithm in Section 3.** If something seems missing, say so and ask — do not silently redesign it.
2. **Do not add anything listed in Section 12 (Explicit Cuts).** If you think one of those cuts is a mistake, say so in one sentence and wait for confirmation. Do not build it preemptively.
3. **Work phase by phase (Section 9).** Each phase has an explicit "Output" list and "Verify" step. Do not start the next phase's files until the current phase's verify step passes.
4. **Minimum code that satisfies the phase.** No abstractions, config flags, or error handling for scenarios not in this doc.
5. When a phase prompt says "do NOT touch X," treat that as a hard boundary, not a suggestion.

---

## 1. Locked Spec

**Problem**: teams change decisions (owners, deadlines, stack) constantly; naive memory tools either dump everything into a vector DB (fails this track's explicit rule) or silently overwrite old facts (loses history, can't explain "why").

**Target user**: a small team that needs one source of truth for "what do we currently believe, and why."

**Positioning**: *"Most assistants retrieve memories. Ledger maintains state — and can prove why it believes what it tells you."*

**Must work end-to-end (graded, non-negotiable)**:
- Persistence across a real process restart (not just same-process save/load)
- Contradiction → supersession vs. dispute, correctly distinguished
- Provenance for every answer (which memory, which message, which user, when)

**Strong-plus (committed)**: multi-user isolation (private vs. team visibility), disputed-conflict state, bi-temporal query ("what did we believe on date X" vs "when did we learn it").

**Differentiation claims — stay factual, do not overclaim**:
- Naive "vector DB + top-k" fails this track's own rule — say this plainly.
- Say: *"we make conflict resolution explicit and inspectable, rather than hidden inside a general memory framework."*
- Do NOT claim to be "the only" team doing anything.
- Do NOT call Graphiti "peer-reviewed" (only Zep's paper is).
- Do NOT claim Mem0 "can't handle change" — it has ADD/UPDATE/DELETE. The real differentiator is the explicit version chain + dispute state + inspectable resolution, not that competitors lack update capability.

---

## 2. Data Model (SQLite — exact schema, do not modify field names)

```sql
CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL
);

CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    created_at TEXT NOT NULL
);

CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE facts (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    source_user_id TEXT NOT NULL REFERENCES users(id),   -- resolved server-side from session token, NEVER client-supplied
    visibility TEXT NOT NULL CHECK (visibility IN ('private','team')),

    subject TEXT NOT NULL,
    attribute TEXT NOT NULL,
    fact_key TEXT NOT NULL,          -- = normalize(subject) || '::' || normalize(attribute); computed at insert time
    value TEXT NOT NULL,

    type TEXT NOT NULL CHECK (type IN ('fact','decision','task')),
    epistemic_status TEXT NOT NULL CHECK (epistemic_status IN ('asserted','correction','proposal','opinion','uncertain')),
    status TEXT NOT NULL CHECK (status IN ('active','proposed','superseded','disputed','stale','forgotten')),

    valid_from TEXT NOT NULL,        -- when the fact became true (from message context; default = recorded_at)
    valid_to TEXT,                   -- null if still active
    recorded_at TEXT NOT NULL,       -- when Ledger ingested it (wall-clock ingestion time)

    supersedes_id TEXT REFERENCES facts(id),
    conflicts_with_id TEXT REFERENCES facts(id),

    asserted_strength REAL NOT NULL, -- 0-1, how confidently it was PHRASED — never used as a truth score, never shown as a bare % in UI
    override_signal INTEGER NOT NULL CHECK (override_signal IN (0,1)),

    source_message_id TEXT NOT NULL REFERENCES messages(message_id),
    expires_at TEXT                  -- for decay; tasks/temporary facts only
);

CREATE INDEX idx_facts_lookup ON facts(workspace_id, fact_key, status);
```

**Explicit design notes (do not "fix" these — they're intentional)**:
- `fact_key` is used ONLY to find candidate matches (structured lookup, then Chroma paraphrase fallback). It never decides truth — the resolver rules do.
- `status='proposed'` pairs with `epistemic_status='proposal'`; `status='active'` pairs with `epistemic_status='asserted'`. Do not merge these two fields.
- No `actor_role` / authority-hierarchy field. This is an **explicit cut** — see Section 12 for why.

---

## 3. Resolution Algorithm (deterministic-first; LLM is fallback only)

```
1. EXTRACT (1 LLM call per message — see Section 7 for exact prompt)
   message text → list of candidate facts:
     {subject, attribute, value, type, epistemic_status, override_signal, valid_from, asserted_strength}

2. For each candidate:
   a. fact_key = normalize(subject) + '::' + normalize(attribute)
   b. STRUCTURED LOOKUP: exact fact_key match, scoped to workspace_id,
      filtered by visibility (visibility='team' OR source_user_id = requester)
      → match found → go to step 3
      → no match → CHROMA PARAPHRASE CHECK (same workspace/visibility filter)
           → match found (e.g. "Postgres" vs "we're on Postgres now") → go to step 3
           → still no match → INSERT new fact, status='active' (or 'proposed' if epistemic_status
             is proposal/opinion/uncertain — never insert those as 'active')

3. Apply rules in this exact order (first match wins):
   a. epistemic_status IN ('opinion','proposal','uncertain')
        → INSERT new row, status='proposed'. NEVER touches the existing active fact.
   b. epistemic_status = 'correction' OR override_signal = true
        → SUPERSEDE: old.status='superseded', old.valid_to=now
                      new.status='active', new.supersedes_id=old.id
   c. epistemic_status = 'asserted', value contradicts existing active fact,
      source_user_id != existing active fact's source_user_id, override_signal = false
        → new.status='disputed', new.conflicts_with_id=old.id
          old fact STAYS active/untouched — do not guess a winner
   d. same value re-asserted (matches existing active fact's value)
        → no-op (dedupe); do not insert a duplicate row
   e. Anything not matching a-d → single LLM fallback call: classify as
      same / update / contradiction / unrelated, then re-apply a-d with that label.
      This must be the MINORITY path — if it's firing often, the extraction
      prompt needs better few-shot coverage, not a bigger fallback.

4. FORGET command ("forget that X", "delete X"):
   target.status='forgotten', target.valid_to=now
   → remove from Chroma index explicitly (verify with a direct query — do not assume delete cascades)
   → excluded from all future SQLite active-query results

5. DECAY (computed lazily on READ, no background job):
   type='task' AND now - valid_from > threshold AND no re-confirmation
     → status='stale' (excluded from default answers, visible in inspector only)
```

**Hard rule for the query pipeline**: privacy/workspace filtering happens at the SQL query AND the Chroma metadata filter, BEFORE any fact reaches the answer-generation LLM call. A private fact must never enter the LLM's context window for another user's query, even if it's the closest embedding match. This is enforced in exactly two functions — do not scatter filtering logic elsewhere.

---

## 4. API Surface (FastAPI)

| Endpoint | Body | Returns |
|---|---|---|
| `POST /login` | `{name}` | `{session_token}` |
| `POST /workspaces/{id}/messages` | `{text}` (identity from session token) | ingest result: candidate facts + resolution outcome per candidate |
| `POST /workspaces/{id}/query` | `{question, as_of?: ISO8601}` | `{answer, memory_ids_used, supersede_chain, disputed_flags}`. `as_of` filters on `valid_from`/`valid_to` for the bi-temporal demo beat — omit for "current truth." |
| `GET /workspaces/{id}/memories` | — | full identity-filtered timeline for the inspector panel |
| `POST /workspaces/{id}/what-changed` | `{since_timestamp}` | `{added, updated, superseded, resolved, disputed, stale, forgotten}` — broader than just superseded facts |
| `POST /eval/run` | — | pass/fail scoreboard for the fixed test suite (Section 10) |

Identity (`user_id`, `workspace_id`) is ALWAYS resolved server-side from the session token. Never trust a client-supplied `user_id` field, even if the UI never sends one — validate this is impossible via raw JSON.

---

## 5. Stack (pinned — verify current before hour 0, then freeze)

| Layer | Choice | Note |
|---|---|---|
| Backend | FastAPI | no infra |
| Store | SQLite | canonical state |
| Semantic index | Chroma, `PersistentClient`, local | candidate discovery only, never source of truth |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | **download and cache in Phase 0, verify it loads with wifi off** — this is your #1 offline-availability risk |
| LLM (primary) | Gemini 2.5 Flash-Lite, free tier via AI Studio | extraction + answer generation |
| LLM (fallback) | Groq free tier, `llama-3.3-70b-versatile` | check current rate limits on the actual account you'll demo with — don't assume "unlimited free" |
| Frontend | plain HTML/CSS/JS → FastAPI JSON | no build step |

Wrap the LLM behind a small `LLMProvider` interface (Gemini / Groq / local-mock) so the eval suite in Section 10 can run the deterministic resolver tests with **zero live API calls**.

---

## 6. Repo Structure

```
ledger/
  schema.sql
  resolver.py            # pure functions, no I/O — steps 2-5 of Section 3
  extraction.py           # LLM call wrapper, Section 7 prompt
  llm_provider.py         # Gemini/Groq/mock interface
  chroma_store.py         # candidate discovery + paraphrase check + forget-exclusion
  api.py                  # FastAPI routes, Section 4
  auth.py                 # session token resolution
  static/                 # chat UI + inspector panel
  tests/
    fixtures/
      resolver_cases.json
      eval_suite.json
    test_resolver.py
    test_eval_suite.py
```

---

## 7. Runtime LLM Prompts (used INSIDE the app, not agent-build prompts)

### 7a. Extraction prompt (called once per ingested message)

```
SYSTEM:
You extract candidate facts from a team message for a memory system. Return ONLY a JSON array, no prose, no markdown fences.

Each element:
{
  "subject": string,
  "attribute": string,
  "value": string,
  "type": "fact" | "decision" | "task",
  "epistemic_status": "asserted" | "correction" | "proposal" | "opinion" | "uncertain",
  "override_signal": boolean,
  "valid_from": ISO8601 string or null (null = assume "now"),
  "asserted_strength": number between 0 and 1 (how strongly WORDED, not how true)
}

Classification rules:
- "asserted": a plain factual statement with no hedge and no correction language, and no prior context implied.
- "correction": explicit correction language ("actually", "we moved to", "correction:", "no wait") OR confirms/overrides something previously stated.
- "proposal": suggests something for consideration ("maybe we should", "what if we used").
- "opinion" / "uncertain": hedged belief ("I think", "I believe", "probably", "not sure but").
- override_signal = true ONLY when the message explicitly frames itself as correcting or confirming a prior fact (e.g. "actually", "correction", "confirmed", "the client confirmed") — NOT merely because it contradicts something.

FEW-SHOT EXAMPLES:
Input: "We're using MongoDB."
Output: [{"subject":"project","attribute":"database","value":"MongoDB","type":"fact","epistemic_status":"asserted","override_signal":false,"valid_from":null,"asserted_strength":0.9}]

Input: "Actually we moved to PostgreSQL."
Output: [{"subject":"project","attribute":"database","value":"PostgreSQL","type":"fact","epistemic_status":"correction","override_signal":true,"valid_from":null,"asserted_strength":0.95}]

Input: "I think the deadline might be Oct 3rd."
Output: [{"subject":"project","attribute":"deadline","value":"Oct 3","type":"decision","epistemic_status":"uncertain","override_signal":false,"valid_from":null,"asserted_strength":0.4}]

Input: "Maybe we should use Redis for caching."
Output: [{"subject":"project","attribute":"caching","value":"Redis","type":"proposal","epistemic_status":"proposal","override_signal":false,"valid_from":null,"asserted_strength":0.5}]

Input: "The client confirmed the deadline is Oct 3."
Output: [{"subject":"project","attribute":"deadline","value":"Oct 3","type":"decision","epistemic_status":"correction","override_signal":true,"valid_from":null,"asserted_strength":0.95}]

Input: "The deadline is Oct 10." (no hedge, no correction language — used to seed a disputed case when it contradicts an existing fact from another user)
Output: [{"subject":"project","attribute":"deadline","value":"Oct 10","type":"decision","epistemic_status":"asserted","override_signal":false,"valid_from":null,"asserted_strength":0.85}]

Input: "Client changed the requirement yesterday, but we only found out today."
Output: [{"subject":"project","attribute":"requirement","value":"<the changed requirement text>","type":"decision","epistemic_status":"correction","override_signal":true,"valid_from":"<yesterday's date>","asserted_strength":0.9}]

If the message contains no extractable fact (small talk, a question), return [].
```

### 7b. Answer-generation prompt (called once per query)

```
SYSTEM:
You answer a question using ONLY the facts provided below. These facts have already been
filtered for workspace and privacy — do not second-guess that filtering.
Do not use any fact whose status is 'superseded', 'forgotten', or 'stale' UNLESS the user is
explicitly asking about history or what changed.
If the relevant facts include a status='disputed' entry, say so explicitly and do not pick a side.
Cite every fact you use by its id in a separate memory_ids_used list — never invent an id.
Return JSON: {"answer": string, "memory_ids_used": [ids]}

FACTS:
<inject filtered fact rows here as JSON>

QUESTION:
<user question>
```

---

## 8. Build Order & Verification Checkpoints (12h, 2-3 people)

| Time | Person A | Person B | Person C | **Verify at end of block** |
|---|---|---|---|---|
| 0–0.5h | — all — | Repo scaffold, pinned deps installed, embedding model downloaded and cached | | Disable wifi, confirm embedding model still loads |
| 0.5–2h | Schema + resolver.py (steps 2-5) against 10 hardcoded fixtures, NO LLM/Chroma | Chroma wrapper + workspace-filtered semantic search | Login/session endpoint, messages table, chat UI scaffold | Resolver rules a-e pass on fixtures with zero LLM/Chroma calls |
| 2–4.5h | Extraction prompt (7a) wired to `llm_provider.py` | Wire resolver rules a-d + LLM fallback (rule e) into `/messages` endpoint | Wire UI to backend stubs; inspector skeleton | One live message per resolver branch (a/b/c/d) produces the correct `status` in the DB |
| 4.5–7.5h | Query/answer pipeline (7b) + provenance + `as_of` param + `/what-changed` | Forget command + lazy decay; verify Chroma exclusion on forget | Timeline/inspector UI: active/proposed/superseded/disputed/stale states | Cross-workspace query returns empty; forgotten fact absent from BOTH SQLite and a direct Chroma query |
| 7.5–9.5h | Write + run eval suite (Section 10) as real pytest fixtures | Integration; seed 2 workspaces with a realistic multi-day, multi-user history including the bi-temporal seed case | Polish inspector + scoreboard UI | Eval suite passes; **kill the server process and Chroma, restart both, re-query — same answers** |
| 9.5–11.5h | Rehearse demo (all) | Adversarial pass: private-leak attempt, cross-workspace query, malformed input, simulate Gemini failure → confirm Groq fallback fires | Rehearse dispute→resolve and privacy beats specifically | Full 6-beat demo (Section 11) runs with zero manual correction |
| 11.5–12h | Buffer / final audit (Section 13) | | | |

---

## 9. Agent Build Prompts (paste one at a time, in order, after pasting this whole doc as context)

### Prompt — Phase 0 (scaffold)
```
Using Section 6's repo structure, Section 5's stack, and Section 2's schema.sql exactly as written:
1. Scaffold the repo with empty modules matching the file list in Section 6.
2. Create schema.sql verbatim from Section 2 — do not add or rename fields.
3. Write a script that downloads and caches all-MiniLM-L6-v2 locally.
4. Do NOT write any resolver, API, or extraction logic yet.
Output: repo skeleton + schema.sql + the model-download script. Tell me exactly how to verify the model loads offline.
```

### Prompt — Phase 1 (resolver core)
```
Implement resolver.py: pure Python functions, NO I/O, NO LLM calls, NO Chroma calls. Cover
Section 3 steps 2-5 exactly — the a/b/c/d/e branching and fact_key normalization.
Create tests/fixtures/resolver_cases.json with 10 cases: 2 for rule a, 2 for rule b, 2 for rule c,
2 for rule d, 2 that should fall through to rule e (return the correct pre-fallback label only —
mock the LLM call in the test).
Write tests/test_resolver.py that runs all 10 against resolver.py.
Explicit scope: do NOT add an authority/role field or any concept not in Section 2's schema.
Success criterion: all 10 fixtures pass with zero network calls. Show me the test output.
```

### Prompt — Phase 2 (extraction + wiring)
```
Implement extraction.py using the EXACT prompt in Section 7a, calling llm_provider.py (Gemini
primary, Groq fallback per Section 5). Wire resolver.py + extraction.py into the
POST /workspaces/{id}/messages endpoint per Section 4.
Do NOT modify the prompt text in Section 7a. Do NOT add a second LLM call in this endpoint —
extraction is exactly one call, resolution is deterministic except rule e's fallback.
Success criterion: send one message per resolver branch (asserted/correction/opinion/contradiction)
and show me the resulting row's status and epistemic_status match Section 3's rules.
```

### Prompt — Phase 3 (query, forget, decay)
```
Implement the query pipeline using the EXACT prompt in Section 7b, plus the /what-changed and
forget-command logic per Section 3 step 4 and Section 4's endpoint table. Support the optional
`as_of` param on /query for bi-temporal filtering (filter on valid_from/valid_to, not recorded_at).
Enforce workspace + visibility filtering in exactly two functions (the SQL query builder and the
Chroma query wrapper) — do not duplicate this filter logic elsewhere.
Success criterion: (1) a private fact from user A never appears in user B's query results even when
it's the closest Chroma match; (2) a forgotten fact is absent from both a SQLite query and a direct
Chroma query afterward. Show me both tests passing.
```

### Prompt — Phase 4 (eval suite + persistence)
```
Write tests/fixtures/eval_suite.json and tests/test_eval_suite.py implementing the 16 cases in
Section 10 as automated pytest fixtures (not manual demo-only steps).
Separately, write a persistence test that: starts the API as a real subprocess, sends messages,
kills the subprocess entirely, starts a fresh subprocess, and queries — confirming state and
Chroma index both survived. Do NOT implement this as save()/load() calls within one process.
Success criterion: show me the eval suite pass count and the subprocess-restart test passing.
```

---

## 10. Eval Suite (16 cases — 12 shown to judges, 4 folded in as reverse-direction/adversarial)

**Core 12 (from the PRD, shown on the scoreboard):**
1. Persistence across a real process restart
2. Direct correction (override_signal=true) → supersede
3. Genuine contradiction, no override signal, different users → disputed
4. Paraphrase dedupe ("Postgres" = "we're on Postgres now")
5. Duplicate exact re-assertion → no-op
6. Historical/`as_of` query ("what was true on day 1")
7. Provenance returned for every answer (memory_id + timestamp + source message)
8. Explicit forget → excluded from SQLite AND Chroma
9. Private fact never appears in another user's answer or inspector
10. Cross-workspace query returns empty (no leakage)
11. Opinion/proposal never overwrites active truth
12. Stale task excluded from default answer, visible in inspector

**Additional 4 (internal, adversarial — fold results into the same scoreboard without needing a separate slide):**
13. A private fact is excluded even when it is the closest Chroma embedding match to the query (proves filtering happens before generation, not after)
14. A user cannot retrieve another workspace's team-visible memory by any query phrasing
15. Bi-temporal distinction: a fact whose `valid_from` is in the past but `recorded_at` is today returns correctly for both "what was true on X" and "when did we learn this" framings
16. Malformed/nonsense message input does not crash extraction or insert garbage facts

---

## 11. Demo Script (6 beats — exact lines to say)

1. **Persistence** — "What database are we using?" → *no answer yet*. Say: "MongoDB." Restart the app. Ask again → still MongoDB.
2. **Change** — "Actually we moved to PostgreSQL." → query → PostgreSQL is now active; MongoDB shows superseded.
3. **Why?** — Click "Why PostgreSQL?" in the inspector → show: Memory M042, from Message M183, Alice, Sept 17, override=confirmed, supersedes M019.
4. **Time-travel** — "What did we use on Sept 15?" → MongoDB, with its own valid window shown (valid_from/valid_to vs. recorded_at).
5. **Dispute → resolve** — Alice: "Deadline is Oct 10." Bob: "I think it's Oct 3." → system shows DISPUTED, refuses to pick a side. Then: "The client confirmed the deadline is Oct 3." → resolves; Oct 10 superseded.
6. **Privacy + scoreboard** — Show Alice's private note excluded from Bob's query (inspector shows it was filtered before generation, not just missing from the answer). Close with: run `/eval/run` live → "16/16 passed" on screen.

---

## 12. Explicit Cuts (do not build these — said no on purpose)

- **Actor authority / role hierarchy** (`project_lead > team_member`). The scenario it would fix — an unhedged "I think X" shouldn't override an existing fact — is already handled by `epistemic_status='uncertain'` inserting as `status='proposed'`, which by rule (a) never touches active truth. Adding a role field means new schema, new login-flow step, new resolver branch, and a new test, for a case already covered. If asked live: *"an uncorroborated assertion creates a dispute, not a supersession — only explicit correction language tied to a confirmed source overrides."*
- Graphiti / Neo4j / FalkorDB, full RBAC/auth, Postgres, voice, document ingestion, Slack/Discord integration, multi-agent orchestration, ML-based decay modeling.
- More than ~16 eval cases.
- A bare numeric "confidence %" as a headline UI element — show status/source/evidence instead; a percentage with no defined meaning invites a judge question you can't answer well.
- A second or third LLM call per message/query beyond what Section 3/7 specifies, except the rare rule-e fallback.

---

## 13. Pre-Submission Audit Checklist

- [ ] Resolver rules a-e pass with zero network calls (Phase 1 test still green)
- [ ] Full subprocess restart test passes (not same-process save/load)
- [ ] Cross-workspace query returns empty
- [ ] Private fact excluded even as closest embedding match
- [ ] Forgotten fact gone from SQLite AND Chroma (checked directly, not assumed)
- [ ] 16-case eval suite passes; scoreboard renders live via `/eval/run`
- [ ] Embedding model verified to load with no internet connection
- [ ] Groq fallback fires correctly if Gemini call is forced to fail
- [ ] Full 6-beat demo run once, start to finish, with zero manual correction
- [ ] One-paragraph verbal architecture explanation rehearsed without notes:
      *"Every fact has two dates — when it became true, and when we learned it. When someone
      corrects a fact, we mark it superseded and keep it, never overwrite. When two people
      disagree with neither confirming, we mark it disputed and refuse to guess. That's the
      whole engine — five states, everything else is UI around it."*
- [ ] No claim in the pitch says "only team," "peer-reviewed" (re: Graphiti), or "Mem0 can't handle X"
