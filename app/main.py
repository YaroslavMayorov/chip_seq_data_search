from flask import Flask, redirect, url_for, render_template, request, jsonify, Response, flash
import os
import config
from models import db, File, get_file_hash, initialize_main_bed_files
from minio_utils import upload_file_to_minio, read_file_from_minio
import uuid
import tempfile
import subprocess
import logging
import sys

# Logger configuration
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)
logger.info("TEST log statement: main.py has started.")

# Creating an instance of a Flash app
app = Flask(__name__)
app.secret_key = "your_secret_key"

# Database configuration
app.config["SQLALCHEMY_DATABASE_URI"] = config.DB_URL
db.init_app(app)

# Creating tables in the database and initializing the main BED files
with app.app_context():
    db.create_all()
    initialize_main_bed_files()

# File download directory (temporary)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Consts
INIT_NUM = 5
PORT = 5000


def sort_bed(input_bed_str):
    """ Accepts the contents of the BED as a string, returns the same string, but sorted. """
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
    """
    Runs 'bedtools jaccard' for two string contents of BED files,
    returns the jaccard index (float).
    """
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
    """ File upload handler. """
    if request.method == "GET":
        return render_template("upload.html")

    if 'file' not in request.files:
        logger.warning("Upload attempt without a file.")
        flash("Error: No file uploaded!", "danger")
        return redirect(url_for("upload_file"))

    uploaded_file = request.files['file']
    num_matches = request.form.get('num_matches')

    if not uploaded_file.filename.endswith('.bed'):
        logger.warning(f"Invalid file format uploaded: {uploaded_file.filename}")
        flash("Error: Only .bed files allowed!", "danger")
        return redirect(url_for("upload_file"))

    file_path = os.path.join(UPLOAD_FOLDER, uploaded_file.filename)
    uploaded_file.save(file_path)
    file_hash = get_file_hash(file_path)

    logger.info(f"File {uploaded_file.filename} received, calculating hash...")

    # Check if the file already exists in the database
    existing_file = File.query.filter_by(file_hash=file_hash).first()
    if existing_file:
        logger.info(f"Duplicate file detected: {uploaded_file.filename} (id={existing_file.id}), skipping upload.")
        os.remove(file_path)
        return redirect(url_for('find_similar', file_id=existing_file.id, num_matches=num_matches, skip_self="0"))

    # Uploading a file to the cloud storage (MinIO)
    logger.info(f"Uploading file {uploaded_file.filename} (hash: {file_hash}) to MinIO...")
    minio_key = f"{uuid.uuid4()}.bed"
    upload_file_to_minio(file_path, minio_key)

    os.remove(file_path)

    # Add a new file to the database
    new_file = File(filename=uploaded_file.filename, file_hash=file_hash, minio_key=minio_key)
    db.session.add(new_file)
    db.session.commit()

    logger.info(f"File {uploaded_file.filename} uploaded successfully (id={new_file.id})")
    return redirect(url_for('find_similar', file_id=new_file.id, num_matches=num_matches, skip_self="true"))


@app.route('/find_similar/<int:file_id>', methods=['GET'])
def find_similar(file_id):
    """ Finds files similar to the uploaded one using the jaccard index. """
    skip_self = request.args.get('skip_self', '1')
    skip_self = int(skip_self)
    num_matches = int(request.args.get('num_matches', INIT_NUM))

    file = db.session.get(File, file_id)
    if not file:
        return render_template("similar_files.html", file_id=file_id, matches='',
                               num_matches=str(num_matches), skip_self=str(skip_self),
                               error_message="Error: File not found."), 404

    bed1_content = read_file_from_minio(file.minio_key)
    bed1_sorted = sort_bed(bed1_content)

    logger.info(f"Finding similar files for file ID={file_id}...")

    similarities = []
    # Go through all the files in the database
    for db_file in File.query.all():
        if skip_self and db_file.id == file_id:
            continue

        bed2_content = read_file_from_minio(db_file.minio_key)
        bed2_sorted = sort_bed(bed2_content)

        # Calculate the jaccard coefficient between the uploaded file and the current file
        jaccard_score = jaccard_bedtools_in_memory(bed1_sorted, bed2_sorted)
        similarities.append((db_file.id, db_file.filename, jaccard_score))

    # Sort by descending jaccard index
    similarities.sort(key=lambda x: x[2], reverse=True)

    logger.info(f"Similar files for ID={file_id} computed successfully.")
    return render_template("similar_files.html", file_id=file_id, matches=similarities[:num_matches],
                           num_matches=str(num_matches), skip_self=str(skip_self))


@app.route('/file/<int:file_id>', methods=['GET'])
def file_details(file_id):
    """Shows the contents of the file """
    file = File.query.get(file_id)
    if not file:
        logger.error(f"Try to see content of non-existent file {file_id}")
        return render_template("file_details.html",
                               filename=file.filename,
                               file_id=file.id,
                               content="",
                               num_matches=request.args.get('num_matches', INIT_NUM),
                               skip_self=request.args.get('skip_self', 'true'),
                               error_message="Error: File not found."), 404

    bed_content = read_file_from_minio(file.minio_key)
    logger.info(f"Showing content of {file_id}")

    return render_template(
        "file_details.html",
        filename=file.filename,
        file_id=file.id,
        content=bed_content,
        num_matches=request.args.get('num_matches', INIT_NUM),
        skip_self=request.args.get('skip_self', 'true'),
        error_message=""
    )


@app.route('/download/<int:file_id>', methods=['GET'])
def download_file(file_id):
    """ Allows to download a PDF file. """
    file = File.query.get(file_id)
    if not file:
        logger.warning(f"Try to upload a non-existent file {file_id} ")
        flash("Error: Can't download. File not found!", "danger")
        return redirect(request.referrer or url_for("upload_file"))

    bed_content = read_file_from_minio(file.minio_key)

    response = Response(bed_content, mimetype="text/plain")
    response.headers["Content-Disposition"] = f"attachment; filename={file.filename}"
    logger.info(f"File {file_id} successfully downloaded")
    return response


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=PORT, debug=True)
