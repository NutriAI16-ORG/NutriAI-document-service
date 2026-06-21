"""
Document Service - Azure Blob Storage Operations
"""

import logging
import uuid
from datetime import datetime, timedelta

from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions, ContentSettings

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


import os

def get_blob_service_client() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)


def upload_document(file_content: bytes, original_filename: str, content_type: str) -> dict:
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    is_mock = not conn_str or conn_str == "" or "base64" in conn_str or "your-" in conn_str or conn_str.startswith("<")

    if is_mock:
        logger.warning("Azure Storage connection string is empty or placeholder. Running in LOCAL STORAGE MOCK mode.")
        upload_dir = "/app/uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_extension = original_filename.rsplit(".", 1)[-1] if "." in original_filename else ""
        blob_name = f"{uuid.uuid4()}.{file_extension}"
        filepath = os.path.join(upload_dir, blob_name)
        try:
            with open(filepath, "wb") as f:
                f.write(file_content)
            logger.info(f"Saved mock upload file to: {filepath}")
            return {"blob_name": blob_name, "blob_url": f"/mock-uploads/{blob_name}"}
        except Exception as e:
            logger.error(f"Error saving mock file locally: {e}")
            raise

    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)

        # Auto-create the container if it does not exist
        try:
            container_client.create_container()
            logger.info(f"Created Azure Storage container: '{settings.AZURE_STORAGE_CONTAINER_NAME}'")
        except Exception as ex:
            # If the container already exists, Azure returns ContainerAlreadyExists which we can safely ignore
            if "ContainerAlreadyExists" not in str(ex):
                logger.debug(f"Container check/creation details: {ex}")

        file_extension = original_filename.rsplit(".", 1)[-1] if "." in original_filename else ""
        blob_name = f"{uuid.uuid4()}.{file_extension}"

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(
            file_content,
            content_settings=ContentSettings(content_type=content_type),
            overwrite=True,
        )

        return {"blob_name": blob_name, "blob_url": blob_client.url}

    except Exception as e:
        logger.error(f"Error uploading document to Azure Storage: {e}")
        raise


def get_document_url(blob_name: str) -> str:
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    is_mock = not conn_str or conn_str == "" or "base64" in conn_str or "your-" in conn_str or conn_str.startswith("<")

    if is_mock:
        return f"/api/documents/mock-uploads/{blob_name}"

    try:
        blob_service_client = get_blob_service_client()
        account_name = blob_service_client.account_name
        account_key = blob_service_client.credential.account_key

        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=1),
        )

        return f"https://{account_name}.blob.core.windows.net/{settings.AZURE_STORAGE_CONTAINER_NAME}/{blob_name}?{sas_token}"

    except Exception as e:
        logger.error(f"Error generating SAS URL for blob {blob_name}: {e}")
        raise


def delete_document_blob(blob_name: str) -> bool:
    conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
    is_mock = not conn_str or conn_str == "" or "base64" in conn_str or "your-" in conn_str or conn_str.startswith("<")

    if is_mock:
        filepath = os.path.join("/app/uploads", blob_name)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"Deleted mock upload file: {filepath}")
            except Exception as e:
                logger.warning(f"Could not delete local mock file {filepath}: {e}")
        return True

    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.delete_blob()
        return True
    except Exception as e:
        logger.error(f"Error deleting document from Azure Storage: {e}")
        raise
