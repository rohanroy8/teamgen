"""DB helper — single place for connections (psycopg2, server-side cursors where needed)."""
import os

import psycopg2
import psycopg2.extras


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (copy .env.example to .env)")
    return url


def get_conn():
    conn = psycopg2.connect(database_url())
    conn.autocommit = True
    return conn


def get_dict_cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
