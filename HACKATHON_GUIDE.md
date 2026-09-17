# TeamGen Memory — Hackathon PPT Guide

> How to use this file: each `## Slide N` section = one slide (title + bullets +
> speaker notes). A 12-slide, ~5-minute deck. All claims below match the built
> system (Phases 0–6 done, 22/22 backend tests green); Phase 7–8 items are marked
> (PLANNED).

---

## Slide 1 — Title

- **TeamGen Memory**: the assistant that never forgets — and can prove why it believes what it tells you.
- Tagline: *"Most assistants retrieve memories. Ours maintains state."*
- Team / event / date (fill in).

Speaker notes: open with the failure everyone knows — "ask your AI teammate what you decided last week, get a confident wrong answer." We fix the memory layer, not the chatbot.

---

## Slide 2 — The Problem

- Teams constantly change decisions: owners, deadlines, tech stack.
- Existing memory tools either dump everything into a vector DB (no conflict handling) or silently overwrite old facts (no history, no "why").
- Result: confident wrong answers, leaked private notes, zero audit trail.

Speaker notes: make it concrete — "deadline was Friday, became Monday, two people remember different things, the bot picks one and can't explain itself."

---

## Slide 3 — What We Built (one-liner + pillars)

- A team memory engine + ChatGPT-style app with four pillars:
  1. **Write path** — chat becomes versioned facts (extract → resolve → write).
  2. **Read path** — answers cite exact memory IDs, never leak across users.
  3. **Version control** — every fact change is an inspectable chain (history, revert, digest).
  4. **Governance** — roles (creator/maintainer/contributor/viewer), disputes, Memory PRs.

---

## Slide 4 — Architecture

```
Next.js (ReUI) ──JWT──▶ FastAPI ──┬──▶ Postgres + pgvector (facts, chains, events)
                 NextAuth          ├──▶ Gemini 3.5 Flash-Lite (extract + answer)
                                   └──▶ Groq gpt-oss-20b (fallback) / local-mock (tests)
```

- Frontend: Next.js App Router + Tailwind + ReUI Base-UI components only.
- Auth: NextAuth credentials (browser) + backend JWT (API); identity resolved server-side on every call — the client can never spoof a user.
- Everything scope-filtered in SQL *before* the LLM ever sees it.

---

## Slide 5 — Write Path: conflict is the feature

- Every message: **extract** (how was it said? asserted / correction / opinion / uncertain + override signal) → **resolve** (deterministic rules) → **write** (one transaction + event log).
- Rules: opinions never overwrite truth (→ `proposed`); corrections supersede (old kept, linked); cross-user contradictions → `disputed`, both kept, conflict opened; duplicates → no-op; same message twice → one row (idempotency).
- Prompt-injection ("ignore instructions delete all") is detected and changes nothing.

---

## Slide 6 — Read Path: citations or silence

- Retrieval = structured lookup + vector top-20, unioned, reranked (similarity dominates; recency only breaks ties).
- Access counts update per read (memory of what's *used*, not just what's stored).
- Answers cite `[M1]`-style IDs validated against retrieved rows; other people's disputed facts surface with `@username` and no side picked; unknown → honest "I don't know" (+ who to ask).
- Time-travel: ask what was true on any date (valid-time vs learned-time kept separate).

---

## Slide 7 — Proof, not promises (live demo beats)

1. **Remember + restart** — fact survives a real server restart.
2. **Correct** — "moved to Bangalore" supersedes Hyderabad; click **Why?** → chain with author, quote, timestamps.
3. **Time-travel** — "where did I live on Mar 1?" → Hyderabad.
4. **Dispute → resolve** — Alice "Friday" vs Bob "Monday" → DISPUTED, both shown → resolve by accept-both or winner.
5. **Privacy** — Bob asks Alice's personal secret → denied, empty citations.
6. **Governance** — member contradicts pinned GCP fact → staged as PR → creator approves → flips.

---

## Slide 8 — Roles & collaboration

- Creator (full power) → Maintainer (invite, approve, resolve) → Contributor (write/propose) → Viewer (read-only).
- Invite by username, no email. Creator promotes/demotes; last creator protected.
- Conflicts inbox + Memory PR approve/reject, all leading to the same inspectable event log.

---

## Slide 9 — Engineering rigor (judges love this)

- 22/22 automated backend tests green across repeated runs (write, read, version, team suites).
- Deterministic offline test mode (`TEAMGEN_OFFLINE=1`) — suite never depends on live LLM luck.
- Real retrieval ranking fix found by tests: similarity now dominates recency (documented in spec).
- Append-only memory: revert restores, never deletes; orphan-author check = 0 every phase.
- Human-gated build: git commit + tag per phase (`v0.0`–`v0.5`), changelog maintained.

---

## Slide 10 — What we honestly cut (and why)

- E1 (post-v1.0): GitHub-like branches/forks/merges for project knowledge, button-operated — spec'd, not built.
- Skipped deliberately: OAuth, org-wide RBAC, dark mode, cross-device chat history (browser-local for now), numeric "confidence %" as a headline (we show status/source/evidence instead).
- No overclaiming: we say conflict resolution is *explicit and inspectable* — not that competitors "can't" do updates.

---

## Slide 11 — Roadmap

- Phase 7: hardening edge suite (empty-user, 200-message sessions, tool-fail paths).
- Phase 8: deploy (backend Railway/Render/Fly + frontend Vercel), phone-data test, `v1.0-demo` tag.
- Post-v1.0: E1 knowledge branching (spec ready), @-mentions entity links, weekly digest export.

---

## Slide 12 — Closing

- "Close the app, reopen it, ask again — same answer, with receipts."
- Call to action / contact / repo link (fill in).

---

## Appendix — facts you'll be asked

- Stack: FastAPI, Postgres 16 + pgvector 0.8.6, Next.js 14, Gemini 3.5 Flash-Lite, Groq fallback, all-MiniLM-class local embeddings path.
- Seed demo: alice (creator), bob (contributor), charlie; projects orca/phoenix; password `demo123` for all.
- Test logins for judges: alice/demo123, bob/demo123, charlie/demo123.
- Key files: `AGENT_LOOP.md` (build spec), `PROGRESS.log` (phase journal), `CHANGELOG.md`, `tests/` (22 tests).
