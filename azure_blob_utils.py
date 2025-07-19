import os
import logging
from typing import Optional, BinaryIO
from azure.storage.blob import BlobServiceClient, ContainerClient
from azure.core.exceptions import ResourceNotFoundError

logger = logging.getLogger(__name__)


class AzureBlobStorage:
    def __init__(self):
        self.connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self.container_name = os.getenv("AZURE_STORAGE_CONTAINER", "drhp-files")

        if not self.connection_string:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING environment variable is required"
            )

        self.blob_service_client = BlobServiceClient.from_connection_string(
            self.connection_string
        )
        self.container_client = self.blob_service_client.get_container_client(
            self.container_name
        )

        # Ensure container exists
        self._ensure_container_exists()

    def _ensure_container_exists(self):
        """Ensure the container exists, create if it doesn't"""
        try:
            self.container_client.get_container_properties()
        except ResourceNotFoundError:
            logger.info(f"Container {self.container_name} not found, creating...")
            self.blob_service_client.create_container(self.container_name)
            logger.info(f"Container {self.container_name} created successfully")

    def upload_file(self, local_file_path: str, blob_name: str) -> str:
        """
        Upload a file to blob storage

        Args:
            local_file_path: Path to local file
            blob_name: Name to give the blob in storage

        Returns:
            str: Blob URL
        """
        try:
            with open(local_file_path, "rb") as data:
                self.container_client.upload_blob(
                    name=blob_name, data=data, overwrite=True
                )

            blob_url = f"{self.container_client.url}/{blob_name}"
            logger.info(f"File uploaded successfully: {blob_url}")
            return blob_url
        except Exception as e:
            logger.error(f"Failed to upload file {local_file_path}: {e}")
            raise

    def upload_data(self, data: BinaryIO, blob_name: str) -> str:
        """
        Upload data from a file-like object to blob storage

        Args:
            data: File-like object (e.g., from UploadFile)
            blob_name: Name to give the blob in storage

        Returns:
            str: Blob URL
        """
        try:
            self.container_client.upload_blob(name=blob_name, data=data, overwrite=True)
            blob_url = f"{self.container_client.url}/{blob_name}"
            logger.info(f"Data uploaded successfully: {blob_url}")
            return blob_url
        except Exception as e:
            logger.error(f"Failed to upload data to {blob_name}: {e}")
            raise

    def download_file(self, blob_name: str, local_file_path: str):
        """
        Download a blob to local file

        Args:
            blob_name: Name of the blob in storage
            local_file_path: Local path to save the file
        """
        try:
            with open(local_file_path, "wb") as file:
                download_stream = self.container_client.download_blob(blob_name)
                file.write(download_stream.readall())
            logger.info(f"File downloaded successfully: {local_file_path}")
        except Exception as e:
            logger.error(f"Failed to download blob {blob_name}: {e}")
            raise

    def get_blob_url(self, blob_name: str) -> str:
        """
        Get the URL for a blob

        Args:
            blob_name: Name of the blob

        Returns:
            str: Blob URL
        """
        return f"{self.container_client.url}/{blob_name}"

    def blob_exists(self, blob_name: str) -> bool:
        """
        Check if a blob exists

        Args:
            blob_name: Name of the blob

        Returns:
            bool: True if blob exists, False otherwise
        """
        try:
            self.container_client.get_blob_client(blob_name).get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False

    def delete_blob(self, blob_name: str):
        """
        Delete a blob

        Args:
            blob_name: Name of the blob to delete
        """
        try:
            self.container_client.delete_blob(blob_name)
            logger.info(f"Blob deleted successfully: {blob_name}")
        except Exception as e:
            logger.error(f"Failed to delete blob {blob_name}: {e}")
            raise

    def list_blobs(self, name_starts_with: Optional[str] = None):
        """
        List blobs in container

        Args:
            name_starts_with: Optional prefix to filter blobs

        Returns:
            List of blob names
        """
        try:
            blobs = self.container_client.list_blobs(name_starts_with=name_starts_with)
            return [blob.name for blob in blobs]
        except Exception as e:
            logger.error(f"Failed to list blobs: {e}")
            raise


# Global instance
blob_storage = None


def get_blob_storage() -> AzureBlobStorage:
    """Get the global blob storage instance"""
    global blob_storage
    if blob_storage is None:
        blob_storage = AzureBlobStorage()
    return blob_storage
