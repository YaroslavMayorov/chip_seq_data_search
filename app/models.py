from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String
from flask import Flask
import config
import hashlib


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URL
db = SQLAlchemy(app)


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

