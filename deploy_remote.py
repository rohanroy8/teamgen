import psycopg2
import os

pwd = "nightswamp888%40"
base = f"postgresql://postgres.yeyodpcyopahlbvctbmr:{pwd}@aws-0-ap-northeast-1.pooler.supabase.com"

# Let's try port 6543 first, as it's the standard pooler port for IPv4.
# If it fails, fallback to 5432.
urls = [
    f"{base}:6543/postgres?sslmode=require",
    f"{base}:5432/postgres?sslmode=require"
]

conn = None
working_url = None
for url in urls:
    try:
        print(f"Trying {url} ...")
        # Connect using the URL
        conn = psycopg2.connect(url, connect_timeout=10)
        working_url = url
        print(f"Success!")
        break
    except Exception as e:
        print(f"Failed: {e}")

if not conn:
    print("Could not connect to the database!")
    exit(1)

# Enable extensions
with conn.cursor() as cur:
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
conn.commit()
print("Extensions enabled.")

# Apply schema
# The schema file may contain multiple statements. psycopg2 handles this if executed all at once.
try:
    with conn.cursor() as cur:
        with open('backend/schema.sql', 'r') as f:
            cur.execute(f.read())
    conn.commit()
    print("Schema applied!")
except Exception as e:
    print(f"Schema application failed: {e}")

conn.close()

# Export working URL for seeding
with open("env_url.txt", "w") as f:
    f.write(working_url)

