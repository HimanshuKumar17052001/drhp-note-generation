import os
from datetime import datetime, timedelta
import requests
import boto3
from botocore.exceptions import ClientError
from typing import Dict, List, Tuple
import pytz
from dotenv import load_dotenv
import uuid
from pydantic import BaseModel
import string
import random
import fitz
import json
import logging
import traceback
from io import BytesIO

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("UploadToBlob")


class UploadToBlob:
    def __init__(self):
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        aws_region = os.getenv("AWS_REGION_NAME", "us-east-1")

        # Use the default credential provider chain
        # This will automatically use the IAM role when running in EC2/ECS
        logger.info(
            f"Initializing S3 client for bucket: {self.bucket_name} in region: {aws_region}"
        )
        self.s3_client = boto3.client("s3", region_name=aws_region)

    def upload_to_blob(self, file_obj, file_name: str) -> Tuple[bool, str]:
        try:
            logger.info(f"[UPLOAD_START] Starting upload for file: {file_name}")
            logger.debug(f"[UPLOAD_DEBUG] File object type: {type(file_obj)}")
            logger.debug(f"[UPLOAD_DEBUG] Bucket name: {self.bucket_name}")

            # Convert bytes to BytesIO if necessary
            if isinstance(file_obj, bytes):
                logger.debug(f"[UPLOAD_DEBUG] Converting bytes to BytesIO")
                file_obj = BytesIO(file_obj)

            logger.debug(f"[UPLOAD_DEBUG] Uploading file to S3")
            # Upload to S3
            try:
                self.s3_client.upload_fileobj(
                    Fileobj=file_obj, Bucket=self.bucket_name, Key=file_name
                )
                logger.info(f"[UPLOAD_SUCCESS] File uploaded successfully to S3 bucket")
            except Exception as upload_error:
                logger.error(
                    f"[UPLOAD_ERROR] Error during S3 upload: {str(upload_error)}"
                )
                logger.error(f"[UPLOAD_TRACEBACK] {traceback.format_exc()}")
                return False, f"S3 upload error: {str(upload_error)}"

            # Generate pre-signed URL
            logger.debug(f"[UPLOAD_DEBUG] Generating pre-signed URL")
            try:
                url = self.s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": file_name},
                    ExpiresIn=3600,
                )
                logger.info(f"[UPLOAD_SUCCESS] Generated pre-signed URL: {url[:30]}...")
            except Exception as url_error:
                logger.error(
                    f"[UPLOAD_ERROR] Error generating pre-signed URL: {str(url_error)}"
                )
                logger.error(f"[UPLOAD_TRACEBACK] {traceback.format_exc()}")
                return False, f"Pre-signed URL generation error: {str(url_error)}"

            logger.info(
                f"[UPLOAD_COMPLETE] Successfully completed upload process for {file_name}"
            )
            return True, url

        except Exception as e:
            logger.error(f"[UPLOAD_ERROR] Unexpected error in upload_to_blob: {str(e)}")
            logger.error(f"[UPLOAD_TRACEBACK] {traceback.format_exc()}")
            return False, str(e)

    def get_object_url(self, key_name: str, pattern: str = None) -> str:
        """
        Returns a direct S3 URL for an object based on key name and optional pattern.

        Args:
            key_name: The key (path) of the object in S3
            pattern: Optional URL pattern. If not provided, uses default S3 URL format

        Returns:
            URL string for the S3 object
        """
        if pattern:
            # Use provided pattern to construct URL
            # Example pattern: "https://custom-domain.com/{key}"
            return pattern.format(key=key_name, bucket=self.bucket_name)
        else:
            # Use standard S3 URL format
            return f"https://{self.bucket_name}.s3.amazonaws.com/{key_name}"

    def delete_file(self, file_url: str) -> Tuple[bool, str]:
        try:
            logger.info(
                f"[DELETE_START] Attempting to delete file with URL: {file_url}"
            )

            # Extract the key from the URL
            # Better URL parsing to handle different S3 URL formats
            if "s3.amazonaws.com/" in file_url:
                # Standard URL format: https://bucket-name.s3.amazonaws.com/key
                file_path = file_url.split("s3.amazonaws.com/")[-1]
                if file_path.startswith(f"{self.bucket_name}/"):
                    file_path = file_path[len(self.bucket_name) + 1 :]
                logger.debug(
                    f"[DELETE_DEBUG] Parsed standard S3 URL to key: {file_path}"
                )
            elif ".s3." in file_url:
                # Virtual hosted style URL: https://bucket-name.s3.region.amazonaws.com/key
                file_path = file_url.split("/")[-1] if "/" in file_url else file_url
                logger.debug(
                    f"[DELETE_DEBUG] Parsed virtual hosted style URL to key: {file_path}"
                )
            else:
                # If it's just a key and not a URL
                file_path = file_url
                logger.debug(f"[DELETE_DEBUG] Using provided key directly: {file_path}")

            # Delete the object
            logger.debug(
                f"[DELETE_DEBUG] Deleting object from bucket: {self.bucket_name}, key: {file_path}"
            )
            try:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_path)
                logger.info(f"[DELETE_SUCCESS] File deleted successfully")
            except Exception as delete_error:
                logger.error(
                    f"[DELETE_ERROR] Error during delete operation: {str(delete_error)}"
                )
                logger.error(f"[DELETE_TRACEBACK] {traceback.format_exc()}")
                return False, f"Delete operation error: {str(delete_error)}"

            return True, "File deleted successfully"

        except Exception as e:
            logger.error(f"[DELETE_ERROR] Unexpected error in delete_file: {str(e)}")
            logger.error(f"[DELETE_TRACEBACK] {traceback.format_exc()}")
            return False, str(e)

    def generate_ref_id(self):
        uid = "".join(random.choices(string.ascii_letters + string.digits, k=12))
        return uid

    def check_new_files(self, time_to_check_in_mins=1) -> List[dict]:
        try:
            logger.info(
                f"[CHECK_NEW_FILES_START] Checking for new files modified in the last {time_to_check_in_mins} minutes"
            )
            logger.debug(f"[CHECK_NEW_FILES_DEBUG] Bucket name: {self.bucket_name}")

            # Convert current time to UTC
            current_time = datetime.now(pytz.UTC)
            time_to_check = current_time - timedelta(minutes=time_to_check_in_mins)
            logger.debug(f"[CHECK_NEW_FILES_DEBUG] Current time (UTC): {current_time}")
            logger.debug(
                f"[CHECK_NEW_FILES_DEBUG] Looking for files modified after: {time_to_check}"
            )

            try:
                paginator = self.s3_client.get_paginator("list_objects_v2")
                new_files = []

                for page in paginator.paginate(Bucket=self.bucket_name):
                    if "Contents" not in page:
                        logger.debug(
                            f"[CHECK_NEW_FILES_DEBUG] No contents in this page of results"
                        )
                        continue

                    logger.debug(
                        f"[CHECK_NEW_FILES_DEBUG] Found {len(page['Contents'])} objects in this page"
                    )
                    for obj in page["Contents"]:
                        try:
                            last_modified_utc = obj["LastModified"].astimezone(pytz.UTC)

                            # Check if file matches criteria
                            is_valid_extension = obj["Key"].endswith(
                                (".mp3", ".mp4", ".wav", ".m4a", ".aac")
                            )
                            is_recent = last_modified_utc >= time_to_check

                            logger.debug(
                                f"[CHECK_NEW_FILES_DEBUG] File: {obj['Key']}, Last Modified: {last_modified_utc}"
                            )
                            logger.debug(
                                f"[CHECK_NEW_FILES_DEBUG] Valid extension? {is_valid_extension}, Recent? {is_recent}"
                            )

                            if is_recent and is_valid_extension:
                                file_url = f"https://{self.bucket_name}.s3.amazonaws.com/{obj['Key']}"
                                ref_id = self.generate_ref_id()
                                new_files.append(
                                    {
                                        "status": True,
                                        "url": file_url,
                                        "ref_id": ref_id,
                                        "file_name": obj["Key"],
                                        "bucket": self.bucket_name,
                                    }
                                )
                                logger.info(
                                    f"[CHECK_NEW_FILES_SUCCESS] Added file to results: {obj['Key']}"
                                )
                            else:
                                continue
                        except Exception as obj_error:
                            logger.error(
                                f"[CHECK_NEW_FILES_ERROR] Error processing object: {str(obj_error)}"
                            )
                            continue

                logger.info(
                    f"[CHECK_NEW_FILES_COMPLETE] Found {len(new_files)} new files"
                )
                return new_files

            except Exception as list_error:
                logger.error(
                    f"[CHECK_NEW_FILES_ERROR] Error listing objects: {str(list_error)}"
                )
                logger.error(f"[CHECK_NEW_FILES_TRACEBACK] {traceback.format_exc()}")
                return []

        except Exception as e:
            logger.error(
                f"[CHECK_NEW_FILES_ERROR] Unexpected error in check_new_files: {str(e)}"
            )
            logger.error(f"[CHECK_NEW_FILES_TRACEBACK] {traceback.format_exc()}")
            return []

    def download_file(self, file_name: str, download_path: str):
        try:
            logger.info(
                f"[DOWNLOAD_START] Starting download for file: {file_name} to path: {download_path}"
            )
            logger.debug(f"[DOWNLOAD_DEBUG] Bucket name: {self.bucket_name}")

            try:
                self.s3_client.download_file(
                    Bucket=self.bucket_name, Key=file_name, Filename=download_path
                )
                logger.info(
                    f"[DOWNLOAD_SUCCESS] File downloaded successfully to {download_path}"
                )
            except Exception as download_error:
                logger.error(
                    f"[DOWNLOAD_ERROR] Error during file download: {str(download_error)}"
                )
                logger.error(f"[DOWNLOAD_TRACEBACK] {traceback.format_exc()}")
                return False, f"Download error: {str(download_error)}"

            return True, f"File downloaded successfully to {download_path}"
        except Exception as e:
            logger.error(
                f"[DOWNLOAD_ERROR] Unexpected error in download_file: {str(e)}"
            )
            logger.error(f"[DOWNLOAD_TRACEBACK] {traceback.format_exc()}")
            return False, str(e)

    def check_file_exists(self, file_path: str) -> bool:
        try:
            logger.info(f"[CHECK_FILE_START] Checking if file exists: {file_path}")
            logger.debug(f"[CHECK_FILE_DEBUG] Bucket name: {self.bucket_name}")

            try:
                self.s3_client.head_object(Bucket=self.bucket_name, Key=file_path)
                logger.info(f"[CHECK_FILE_SUCCESS] File exists: {file_path}")
                return True
            except Exception as check_error:
                logger.info(f"[CHECK_FILE_INFO] File does not exist: {file_path}")
                logger.debug(f"[CHECK_FILE_DEBUG] Error details: {str(check_error)}")
                return False
        except Exception as e:
            logger.error(
                f"[CHECK_FILE_ERROR] Unexpected error in check_file_exists: {str(e)}"
            )
            logger.error(f"[CHECK_FILE_TRACEBACK] {traceback.format_exc()}")
            return False


class PDFContentExtractor:
    def __init__(self):
        aws_region = os.getenv("AWS_REGION_NAME")
        logger.info(f"Initializing Textract client in region: {aws_region}")
        self.textract = boto3.client("textract", region_name=aws_region)

    def download_pdf(self, pdf_url: str) -> str:
        try:
            # Create a temporary directory if it doesn't exist
            temp_dir = "temp_pdfs"
            if not os.path.exists(temp_dir):
                os.makedirs(temp_dir)

            # Generate a unique filename
            filename = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            local_path = os.path.join(temp_dir, filename)

            # Download the file
            response = requests.get(pdf_url)
            response.raise_for_status()  # Raise an error for bad status codes

            # Save the file locally
            with open(local_path, "wb") as f:
                f.write(response.content)

            logger.info(f"Downloaded PDF to: {local_path}")
            return local_path

        except Exception as e:
            logger.error(f"Error downloading PDF: {e}")
            raise

    def get_content_from_pdf(self, pdf_path: str) -> Dict:
        logger.info(f"Converting PDF: {pdf_path}")
        try:
            images = self.convert_pdf_to_images(pdf_path)

            result = {}
            full_text = ""
            for i, img_bytes in enumerate(images, 1):
                textract_response = self.process_with_textract(img_bytes)
                page_content = self.extract_text_to_json(textract_response)
                result[str(i)] = page_content
                full_text += page_content
            return full_text

        except Exception as e:
            logger.error(f"Error converting PDF: {str(e)}")
            raise
