from flask import Flask, redirect, url_for, render_template, request, jsonify
import os
import config
from models import db, File, get_file_hash
from minio_utils import upload_file_to_minio
import uuid

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URL
db.init_app(app)

with app.app_context():
    db.create_all()

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route('/')
@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == "GET":
        return render_template("upload.html")

    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    uploaded_file = request.files['file']
    num_matches = request.form.get('num_matches')

    if not uploaded_file.filename.endswith('.bed'):
        return jsonify({"error": "Only .bed files are allowed!"}), 400

    file_path = os.path.join(UPLOAD_FOLDER, uploaded_file.filename)
    uploaded_file.save(file_path)
    file_hash = get_file_hash(file_path)

    existing_file = File.query.filter_by(file_hash=file_hash).first()
    if existing_file:
        os.remove(file_path)
        return redirect(url_for('find_similar', file_id=existing_file.id, num_matches=num_matches, skip_self="false"))

    minio_key = f"{uuid.uuid4()}.bed"
    upload_file_to_minio(file_path, minio_key)

    os.remove(file_path)

    new_file = File(filename=uploaded_file.filename, file_hash=file_hash, minio_key=minio_key)
    db.session.add(new_file)
    db.session.commit()

    return redirect(url_for('find_similar', file_id=new_file.id, num_matches=num_matches, skip_self="true"))


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
