# Changelog — Team Memory

## v0.4 (Phase 4, pending approval)
- Version control: GET /memories/{id}/history (chain + events, @username blame), POST /memories/{id}/revert (lead/owner or author; keeps chain walkable), GET /digest, GET /onboard

## v0.3 (Phase 3)
- Read path: scope-safe retrieve + rerank, Ledger-7b answers with citations + second-person own facts, GET /memories + /memories/at, prompt-injection guard

## v0.2 (Phase 2)
- Write path: extract (7a + offline fallback) -> resolve (M4 rules + cardinality + pinned-PR) -> transactional write; POST /chat; projects + invite-by-username

## v0.1 (Phase 1)
- Auth (bcrypt + JWT) + schema (users/projects/memberships/messages/memory + M3) + seed (alice/bob/charlie, orca/phoenix, 8 memories)

## v0.0 (Phase 0)
- Bootstrap: git repo, docker-compose pgvector:pg16, init.sql (vector+pgcrypto), backend stub, frontend Next.js+ReUI Base UI, NextAuth credentials frozen, .env.example
