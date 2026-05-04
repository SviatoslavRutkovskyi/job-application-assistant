import json
import logging
import os

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)

_CONTAINER = "user-profiles"
_PERSONAL_FILE = "personal.json"
_CANDIDATE_FILE = "candidate.json"
_PERSONAL_SUMMARY_FILE = "personal_summary.json"


class UserDataClient:
    """Reads and writes per-user profile JSON files from Azure Blob Storage.

    Blob paths follow the pattern: {oid}/{filename}
    A user is considered fully set up when all three profile files are present.
    """

    def __init__(self):
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self._client = BlobServiceClient(
            f"https://{account_name}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )

    def _blob(self, oid: str, filename: str):
        return self._client.get_blob_client(
            container=_CONTAINER,
            blob=f"{oid}/{filename}",
        )

    def load(self, oid: str, filename: str) -> dict | None:
        """Return parsed JSON for the given user file, or None if it doesn't exist."""
        try:
            data = self._blob(oid, filename).download_blob().readall()
            return json.loads(data)
        except ResourceNotFoundError:
            return None
        except Exception:
            logger.exception(f"Failed to load {filename} for user {oid}")
            raise

    def save(self, oid: str, filename: str, data: dict) -> None:
        """Serialize and upload data as JSON for the given user file."""
        try:
            self._blob(oid, filename).upload_blob(
                json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                overwrite=True,
            )
        except Exception:
            logger.exception(f"Failed to save {filename} for user {oid}")
            raise

    def exists(self, oid: str) -> bool:
        """Return True only if all three profile files are present."""
        for filename in (_PERSONAL_FILE, _CANDIDATE_FILE, _PERSONAL_SUMMARY_FILE):
            try:
                self._blob(oid, filename).get_blob_properties()
            except ResourceNotFoundError:
                return False
            except Exception:
                logger.exception(f"Failed to check existence of {filename} for user {oid}")
                raise
        return True
