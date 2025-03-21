# wait_for_db.py
import time
import psycopg2
import os

db_url = os.getenv("DB_URL", "postgresql://bed_user:securepassword@db:5432/bed_db")

while True:
    try:
        conn = psycopg2.connect(db_url)
        conn.close()
        print("✅ Database is ready to accept connections")
        break
    except psycopg2.OperationalError:
        print("⏳ Waiting for database...")
        time.sleep(2)
