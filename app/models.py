from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String
from flask import Flask
import config
import hashlib
import os
import uuid
from minio_utils import upload_file_to_minio
import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

db = SQLAlchemy()

# Consts
CHUNK_SIZE = 4096
CLM_SIZE = 255
HASH_SIZE = 64

# Main db files
BED_FILES = [
    "app/data/ENCFF082UWB.bed",
    "app/data/ENCFF190KNC.bed",
    "app/data/ENCFF247CME.bed",
    "app/data/ENCFF608BGQ.bed",
    "app/data/ENCFF832YGL.bed",
]


# Define the file model in the database
class File(db.Model):
    id = Column(Integer, primary_key=True)
    filename = Column(String(CLM_SIZE), unique=False, nullable=False)
    minio_key = Column(String(CLM_SIZE), unique=True, nullable=False)
    file_hash = Column(String(HASH_SIZE), unique=True, nullable=False)


# Calculate the SHA256 hash of a file (to compare files contents)
def get_file_hash(file_path):
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def initialize_main_bed_files():
    for file_path in BED_FILES:
        if not os.path.exists(file_path):
            logger.info(f"File {file_path} not found, skip it.")
            continue

        file_hash = get_file_hash(file_path)

        existing_file = File.query.filter_by(file_hash=file_hash).first()
        if existing_file:
            logger.info(f"{file_path} is already in db, skip it.")
            continue

        minio_key = f"{uuid.uuid4()}.bed"
        upload_file_to_minio(file_path, minio_key)

        new_file = File(filename=os.path.basename(file_path), file_hash=file_hash, minio_key=minio_key)
        db.session.add(new_file)

    db.session.commit()
    logger.info("5 main db files uploaded!")
