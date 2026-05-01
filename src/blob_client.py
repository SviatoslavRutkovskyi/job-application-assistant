import os
from uuid import uuid4

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings


class BlobClient:
    def __init__(self):
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self.container = "outputs"
        self._client = BlobServiceClient(
            f"https://{account_name}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )

    def upload(self, filename: str, data: bytes, content_type: str = "application/pdf") -> str:
        blob_name = f"{uuid4()}-{filename}"
        self._client.get_blob_client(
            container=self.container, blob=blob_name
        ).upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
            metadata={"original_filename": filename},
        )
        return blob_name

    def download(self, blob_name: str) -> tuple[bytes, str]:
        """Returns (pdf_bytes, original_filename)."""
        downloader = self._client.get_blob_client(
            container=self.container, blob=blob_name
        ).download_blob()
        data = downloader.readall()
        filename = downloader.properties.metadata.get("original_filename", "resume.pdf")
        return data, filename