import os
import psycopg2

try:
    conn = psycopg2.connect(
        host="db.yeyodpcyopahlbvctbmr.supabase.co",
        port=5432,
        user="postgres",
        password="nightswamp888@",
        dbname="postgres",
        connect_timeout=10
    )
    print("Connection successful!")
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
        print("Extensions enabled.")
    conn.commit()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
