-- TEAM MEMORY Phase 1 schema (merged AGENT_LOOP + M3 Ledger addendum)
-- Re-runnable: IF NOT EXISTS throughout. Extensions also in init.sql.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    display_name TEXT,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memberships (
    project_id UUID NOT NULL REFERENCES projects(id),
    user_id UUID NOT NULL REFERENCES users(id),
    role TEXT NOT NULL DEFAULT 'member'
        CHECK (role IN ('owner','lead','member','viewer')),
    joined_at TIMESTAMPTZ DEFAULT now(),
    left_at TIMESTAMPTZ,
    PRIMARY KEY (project_id, user_id)
);

-- M3 provenance chain: fact -> message -> user -> timestamp
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    author_id UUID NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- WHO said it (blame, never null, from JWT — never client body)
    author_id UUID NOT NULL REFERENCES users(id),
    -- scope owner key: personal = user UUID string, project = project UUID string
    user_id TEXT NOT NULL,
    project_id UUID REFERENCES projects(id),
    scope TEXT NOT NULL CHECK (scope IN ('personal','project')),
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    -- M3: normalized lookup key, computed at insert: lower(trim(subject))||'::'||lower(trim(predicate))
    fact_key TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'fact',
    -- M3 epistemic axis (how it was phrased; never a truth score)
    epistemic_status TEXT NOT NULL DEFAULT 'asserted'
        CHECK (epistemic_status IN ('asserted','correction','proposal','opinion','uncertain')),
    override_signal BOOLEAN NOT NULL DEFAULT false,
    asserted_strength REAL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','superseded','retracted','expired','proposed',
                          'rejected','disputed','stale','forgotten')),
    -- bi-temporal: valid_* = when true; recorded_at = when learned
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    supersedes UUID REFERENCES memory(id),
    superseded_by UUID REFERENCES memory(id),
    conflicts_with_id UUID REFERENCES memory(id),
    source_message_id UUID REFERENCES messages(id),
    is_pinned BOOLEAN NOT NULL DEFAULT false,
    idempotency_key TEXT UNIQUE,
    embedding VECTOR(768),
    evidence_count INTEGER NOT NULL DEFAULT 1,
    -- retrieval (Phase 3 rerank): confidence, importance, access stats + quote for blame UI
    confidence REAL,
    importance REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed TIMESTAMPTZ,
    quote TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_scope
    ON memory (user_id, scope, project_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_factkey
    ON memory (user_id, scope, project_id, fact_key, status);
CREATE INDEX IF NOT EXISTS idx_memory_subject_predicate
    ON memory (subject, predicate);
CREATE INDEX IF NOT EXISTS idx_memory_embedding
    ON memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- append-only action log (Phase 2 write path logs every action here)
CREATE TABLE IF NOT EXISTS memory_event (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id UUID REFERENCES memory(id),
    action TEXT NOT NULL,
    actor_id UUID REFERENCES users(id),
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- interpersonal conflicts (Phase 5 resolves; Phase 2 rule M4-c opens rows)
CREATE TABLE IF NOT EXISTS conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    memory_a_id UUID REFERENCES memory(id),
    memory_b_id UUID REFERENCES memory(id),
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open','resolved','accepted_both')),
    winner_id UUID REFERENCES memory(id),
    note TEXT,
    resolver_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
