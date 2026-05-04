"""
Migrate candidate.json files in Azure Blob Storage.

Usage:
    AZURE_STORAGE_ACCOUNT_NAME=<name> python scripts/migrate_candidate.py [--dry-run]

Each migration is a plain function that receives the raw candidate dict and
returns the transformed dict. Edit `transform` below for each new migration.
Back up originals are written to candidate_backup.json before any changes.

Run with --dry-run first to preview changes without writing anything.

Authentication: uses DefaultAzureCredential (az login for local runs,
managed identity in Azure).
"""

import argparse
import json
import logging
import os
import sys

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_CONTAINER = "user-profiles"
_CANDIDATE_FILE = "candidate.json"
_BACKUP_FILE = "candidate_backup.json"


# ── Migration ────────────────────────────────────────────────────────────────
# Edit this function for each new migration.
# Receives the raw dict as stored in blob (pre-Pydantic).
# Returns the transformed dict. Raise an exception to abort this user's migration.

def transform(data: dict) -> dict:
    """No active migration."""
    return data


# ── Runner ───────────────────────────────────────────────────────────────────

def run(dry_run: bool) -> None:
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if not account_name:
        logger.error("AZURE_STORAGE_ACCOUNT_NAME is not set")
        sys.exit(1)

    client = BlobServiceClient(
        f"https://{account_name}.blob.core.windows.net",
        credential=DefaultAzureCredential(),
    )
    container = client.get_container_client(_CONTAINER)

    blobs = [
        b.name for b in container.list_blobs()
        if b.name.endswith(f"/{_CANDIDATE_FILE}")
    ]

    if not blobs:
        logger.info("No candidate.json files found.")
        return

    logger.info(f"Found {len(blobs)} candidate file(s). dry_run={dry_run}")

    migrated = skipped = failed = 0

    for blob_name in blobs:
        user_id = blob_name.split("/")[0]
        try:
            raw = container.get_blob_client(blob_name).download_blob().readall()
            original = json.loads(raw)
        except ResourceNotFoundError:
            logger.warning(f"[{user_id}] Not found — skipping")
            skipped += 1
            continue
        except Exception as e:
            logger.error(f"[{user_id}] Load failed: {e}")
            failed += 1
            continue

        try:
            transformed = transform(json.loads(json.dumps(original)))  # deep copy via round-trip
        except Exception as e:
            logger.error(f"[{user_id}] Transform failed: {e}")
            failed += 1
            continue

        if transformed == original:
            logger.info(f"[{user_id}] No changes — skipping")
            skipped += 1
            continue

        if dry_run:
            logger.info(f"[{user_id}] Would migrate (dry run)")
            migrated += 1
            continue

        try:
            # Backup first
            backup_name = f"{user_id}/{_BACKUP_FILE}"
            container.get_blob_client(backup_name).upload_blob(raw, overwrite=True)

            # Write transformed
            container.get_blob_client(blob_name).upload_blob(
                json.dumps(transformed, ensure_ascii=False, indent=2).encode("utf-8"),
                overwrite=True,
            )
            logger.info(f"[{user_id}] Migrated (backup saved to {_BACKUP_FILE})")
            migrated += 1
        except Exception as e:
            logger.error(f"[{user_id}] Write failed: {e}")
            failed += 1

    logger.info(f"Done. migrated={migrated} skipped={skipped} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate candidate.json files in blob storage.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
