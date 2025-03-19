from flask import Flask, redirect, url_for, render_template, request, jsonify
import os
import config
from models import db, File, get_file_hash
from minio_utils import upload_file_to_minio, read_file_from_minio
import uuid
import tempfile
import subprocess

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URL
db.init_app(app)

with app.app_context():
    db.create_all()

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def sort_bed(input_bed_str):
    with tempfile.NamedTemporaryFile(mode='w', suffix=".bed", delete=False) as tmp_in:
        tmp_in.write(input_bed_str)
        tmp_in.flush()
        input_path = tmp_in.name

    with tempfile.NamedTemporaryFile(mode='w', suffix=".bed", delete=False) as tmp_out:
        output_path = tmp_out.name

    try:
        cmd = ["bedtools", "sort", "-i", input_path]
        with open(output_path, "w") as out_f:
            proc = subprocess.run(cmd, stdout=out_f, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0:
                raise RuntimeError(f"Sort error:\n{proc.stderr}")

        with open(output_path, "r") as f:
            sorted_str = f.read()
        return sorted_str
    finally:
        os.remove(input_path)
        os.remove(output_path)


def jaccard_bedtools_in_memory(bed1_content, bed2_content):
    with tempfile.NamedTemporaryFile(mode='w', suffix=".bed", delete=False) as f1:
        f1.write(bed1_content)
        f1.flush()
        bed1_path = f1.name

    with tempfile.NamedTemporaryFile(mode='w', suffix=".bed", delete=False) as f2:
        f2.write(bed2_content)
        f2.flush()
        bed2_path = f2.name

    try:
        cmd = ["bedtools", "jaccard", "-sorted", "-a", bed1_path, "-b", bed2_path]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Error jaccard bedtools:\n{result.stderr}")

        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("Unexpected output format:\n" + result.stdout)

        headers = lines[0].split("\t")
        data = lines[1].split("\t")
        jaccard_dict = dict(zip(headers, data))
        return float(jaccard_dict["jaccard"])

    finally:
        os.remove(bed1_path)
        os.remove(bed2_path)


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


@app.route('/find_similar/<int:file_id>', methods=['GET'])
def find_similar(file_id):
    skip_self = request.args.get('skip_self', '1')
    skip_self = int(skip_self)
    num_matches = int(request.args.get('num_matches', 5))

    file = File.query.get(file_id)
    if not file:
        return jsonify({"error": "File not found"}), 404

    bed1_content = read_file_from_minio(file.minio_key)
    bed1_sorted = sort_bed(bed1_content)

    similarities = []
    for db_file in File.query.all():
        if skip_self and db_file.id == file_id:
            continue

        bed2_content = read_file_from_minio(db_file.minio_key)

        bed2_sorted = sort_bed(bed2_content)

        jaccard_score = jaccard_bedtools_in_memory(bed1_sorted, bed2_sorted)
        similarities.append((db_file.id, db_file.filename, jaccard_score))

    similarities.sort(key=lambda x: x[2], reverse=True)

    return render_template("similar_files.html", file_id=file_id, matches=similarities[:num_matches],
                           num_matches=str(num_matches), skip_self=str(skip_self))


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
