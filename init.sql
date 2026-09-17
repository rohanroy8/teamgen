-- Phase 0: extensions required for TEAM MEMORY loop
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- NOTE: full schema (users, projects, memberships, memory) lands in Phase 1: backend/schema.sql
-- This file only guarantees extensions exist on fresh `docker compose up`.
