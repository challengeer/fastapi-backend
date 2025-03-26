import boto3
from fastapi import HTTPException
from urllib.parse import urlparse
from PIL import Image
from io import BytesIO
import uuid

from ..config import AWS_ACCESS_KEY, AWS_SECRET_KEY, S3_REGION, S3_BUCKET_NAME, S3_URL

s3_client = boto3.client("s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=S3_REGION
)

def get_s3_url(key: str) -> str:
    return f"{S3_URL}/{key}"

def extract_key_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    return parsed_url.path.lstrip("/")

async def upload_image(file_content: bytes, 
                        folder: str,
                        identifier: str,
                        width: int = 1080,
                        height: int = 1920,
                        quality: int = 85) -> str:
    try:
        # Process image
        image = Image.open(BytesIO(file_content))
        
        # Convert to RGB if image is in RGBA mode
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        
        target_ratio = width / height
        current_ratio = image.width / image.height
        
        if current_ratio != target_ratio:
            # Crop the image to match target ratio
            if current_ratio > target_ratio:
                # Image is too wide - crop width
                new_width = int(image.height * target_ratio)
                left = (image.width - new_width) // 2
                image = image.crop((left, 0, left + new_width, image.height))
            else:
                # Image is too tall - crop height
                new_height = int(image.width / target_ratio)
                top = (image.height - new_height) // 2
                image = image.crop((0, top, image.width, top + new_height))
        
        # Resize to target dimensions
        image = image.resize((width, height), 
            Image.Resampling.LANCZOS if image.width > width 
            else Image.Resampling.BICUBIC
        )
        
        # Save processed image to memory
        output = BytesIO()
        image.save(output, format='JPEG', quality=quality)
        output.seek(0)
        
        # Generate filename and upload
        filename = f"{folder}/{identifier}{"-" if identifier else ""}{uuid.uuid4()}.jpg"
        
        s3_client.upload_fileobj(
            output,
            S3_BUCKET_NAME,
            filename,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        
        return get_s3_url(filename)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process or upload image: {str(e)}")

def delete_file(self, key: str) -> bool:
    try:
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
        return True
    except Exception as e:
        print(f"Failed to delete file {key}: {str(e)}")
        return False