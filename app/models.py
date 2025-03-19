from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String
from flask import Flask
import config
import hashlib
import os
import uuid
from minio_utils import upload_file_to_minio

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URL
db = SQLAlchemy(app)
BED_FILES = [
    "app/data/ENCFF082UWB.bed",
    "app/data/ENCFF190KNC.bed",
    "app/data/ENCFF247CME.bed",
    "app/data/ENCFF608BGQ.bed",
    "app/data/ENCFF832YGL.bed",
]


class File(db.Model):
    id = Column(Integer, primary_key=True)
    filename = Column(String(255), unique=False, nullable=False)
    minio_key = Column(String(255), unique=True, nullable=False)
    file_hash = Column(String(64), unique=True, nullable=False)


def get_file_hash(file_path):
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def initialize_bed_files():
    for file_path in BED_FILES:
        if not os.path.exists(file_path):
            print(f"File {file_path} not found, skip it.")
            continue

        file_hash = get_file_hash(file_path)

        existing_file = File.query.filter_by(file_hash=file_hash).first()
        if existing_file:
            print(f"{file_path} is already in db, skip it.")
            continue

        minio_key = f"{uuid.uuid4()}.bed"
        upload_file_to_minio(file_path, minio_key)

        new_file = File(filename=os.path.basename(file_path), file_hash=file_hash, minio_key=minio_key)
        db.session.add(new_file)

    db.session.commit()
    print("5 main db files uploaded!")
