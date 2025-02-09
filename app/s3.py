import boto3
from .config import AWS_ACCESS_KEY, AWS_SECRET_KEY, S3_REGION, S3_BUCKET_NAME

s3_client =  boto3.client("s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=S3_REGION
)