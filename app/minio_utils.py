import boto3
import config

s3 = boto3.client(
    "s3",
    endpoint_url=config.MINIO_ENDPOINT,
    aws_access_key_id=config.MINIO_ACCESS_KEY,
    aws_secret_access_key=config.MINIO_SECRET_KEY
)


def create_bucket():
    try:
        s3.head_bucket(Bucket=config.MINIO_BUCKET)
    except:
        s3.create_bucket(Bucket=config.MINIO_BUCKET)


create_bucket()


def upload_file_to_minio(file_path, minio_key):
    s3.upload_file(file_path, config.MINIO_BUCKET, minio_key)
    return f"{config.MINIO_ENDPOINT}/{config.MINIO_BUCKET}/{minio_key}"


def read_file_from_minio(minio_key):
    obj = s3.get_object(Bucket=config.MINIO_BUCKET, Key=minio_key)
    return obj["Body"].read().decode("utf-8")
