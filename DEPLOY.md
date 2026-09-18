# Deploy — TeamGen Memory (Phase 8)

I (the agent) cannot deploy to your accounts — you run these steps, I verify after.
Total: ~20 min. Do backend first, then frontend.

## 0. Prereqs (you)

- GitHub repo pushed (`git push origin main --tags`), keys ready (see below).
- Free accounts: Railway **or** Render/Fly (backend+DB), Vercel (frontend).

## 1. Database (pick one)

- **Railway**: New Project → Add Postgres → extensions: it runs pg16; add the
  `pgvector` plugin if offered, else run `CREATE EXTENSION vector;` in its SQL tab.
- Copy `DATABASE_URL` (use the **public** URL for the backend service).

## 2. Backend (Railway/Render/Fly — Dockerfile at `backend/Dockerfile`)

Build context = repo root, Dockerfile path = `backend/Dockerfile`.
Env vars (copy values from local `.env`, then rotate secrets after the event):

| Var | Value |
|---|---|
| `DATABASE_URL` | from step 1 |
| `JWT_SECRET` | fresh `python3 -c "import secrets;print(secrets.token_hex(32))"` |
| `GEMINI_API_KEY` | AI Studio key |
| `GROQ_API_KEY` | console.groq.com key |
| `FRONTEND_URL` | your Vercel URL (step 3), comma-separated if several |
| `EMBEDDING_MODE` | `bge-small` |

After deploy: apply schema + seed **once** against prod (local, pointed at prod DB):

```bash
DATABASE_URL=<prod-url> .venv/bin/python -c "
from backend.db import get_conn
import os
os.environ['DATABASE_URL'] = '<prod-url>'
with get_conn() as c, c.cursor() as cur:
    cur.execute(open('backend/schema.sql').read())
print('schema ok')"
DATABASE_URL=<prod-url> JWT_SECRET=<prod-jwt> .venv/bin/python backend/seed.py
```

Health: `curl $PROD_API/health` → `{"ok":true}`.

## 3. Frontend (Vercel)

- Import the repo, Root Directory = `frontend`.
- Env vars: `BACKEND_URL=$PROD_API`, `NEXT_PUBLIC_BACKEND_URL=$PROD_API`,
  `NEXTAUTH_SECRET=<fresh hex>`, `NEXTAUTH_URL=<vercel url>`.
- Deploy. Open `/login` → sign in `alice/demo123`.

## 4. Prod checks (from phone data, NOT wifi — then tell me the URL)

```bash
TOKEN=$(curl -s -X POST $PROD_API/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"demo123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s $PROD_API/me -H "Authorization: Bearer $TOKEN" | grep alice
curl -s -X POST $PROD_API/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"text":"where do I live?"}' | grep -i bangalore
```

Restart the backend service in the dashboard, re-run the last curl → same answer
(restart survival). Invite check: alice invites `bob`, bob logs in on his phone.

## 5. Rehearse (3x, <5 min each)

Demo beats in `HACKATHON_GUIDE.md` slide 7 + close with `POST $PROD_API/eval/run`
(live scoreboard). Final: `git tag v1.0-demo` (agent does this on your approval).
