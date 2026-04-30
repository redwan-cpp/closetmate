"""
gcs_storage.py — Google Cloud Storage helper for ClosetMate.

In production (Cloud Run), set the GCS_BUCKET environment variable to your
bucket name.  The Cloud Run service account must have roles/storage.objectAdmin
on the bucket.

In local development, leave GCS_BUCKET unset — this module becomes a no-op
and the local uploads/ directory is used as a fallback.
"""
from __future__ import annotations

import io
import os
from typing import Optional

GCS_BUCKET: str = os.getenv("GCS_BUCKET", "")


def upload_bytes(
    data: bytes,
    destination_filename: str,
    content_type: str = "image/png",
    folder: str = "uploads",
) -> Optional[str]:
    """
    Upload raw bytes to GCS and return the public HTTPS URL.

    Args:
        data:                 Raw image bytes to upload.
        destination_filename: Filename to store in the bucket (e.g. "abc123.png").
        content_type:         MIME type of the data.
        folder:               Logical folder prefix inside the bucket.

    Returns:
        Public URL like ``https://storage.googleapis.com/<bucket>/<path>``
        or ``None`` if GCS is not configured or the upload fails.
    """
    if not GCS_BUCKET:
        return None  # local dev — caller uses local disk instead

    try:
        from google.cloud import storage  # type: ignore

        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob_name = f"{folder}/{destination_filename}"
        blob = bucket.blob(blob_name)
        blob.upload_from_file(io.BytesIO(data), content_type=content_type)
        blob.make_public()
        url = blob.public_url
        print(f"[gcs_storage] Uploaded to {url}")
        return url
    except Exception as exc:
        print(f"[gcs_storage] Upload failed ({exc}); falling back to local storage")
        return None


def upload_file(
    file_path: str,
    destination_filename: str,
    content_type: str = "image/png",
    folder: str = "uploads",
) -> Optional[str]:
    """Convenience wrapper — reads a file from disk, then calls upload_bytes."""
    with open(file_path, "rb") as fh:
        return upload_bytes(fh.read(), destination_filename, content_type, folder)
