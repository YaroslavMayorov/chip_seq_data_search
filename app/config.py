import os

DB_URL = "postgresql://bed_user:securepassword@db:5432/bed_db"

MINIO_BUCKET = "bed-files"
MINIO_ENDPOINT = "http://minio:9000"
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "password")



