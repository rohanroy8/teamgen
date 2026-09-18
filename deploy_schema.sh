#!/bin/bash
export DATABASE_URL="postgresql://postgres:nightswamp888%40@db.yeyodpcyopahlbvctbmr.supabase.co:5432/postgres"
export JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "- Schema migration:"
.venv/bin/python -c "
from backend.db import get_conn
import os
with get_conn() as c, c.cursor() as cur:
    cur.execute(open('backend/schema.sql').read())
print('Schema applied!')"
echo "- Seeding:"
.venv/bin/python backend/seed.py
echo "JWT_SECRET to use for backend deployment: $JWT_SECRET"
