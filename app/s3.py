import boto3
from .config import AWS_ACCESS_KEY, AWS_SECRET_KEY, S3_REGION, S3_BUCKET_NAME

s3_client =  boto3.client("s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=S3_REGION
)

def get_presigned_url(key: str | None, bucket: str = S3_BUCKET_NAME, expires_in: int = 3600) -> str | None:
    if not key:
        return None
    
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key
        },
        ExpiresIn=expires_in
    )
    return url