"""
Image processing service: background removal and saving processed clothing images.
Runs in CPU-only mode — compatible with Cloud Run and other serverless hosts.

Storage strategy (checked at runtime):
  1. If GCS_BUCKET env var is set  → upload to Google Cloud Storage → return public URL
  2. Otherwise (local dev)         → save to uploads/processed/ → return relative path
"""
import io
import logging
import os
import uuid
from pathlib import Path

# Prevent threading contention on single-core hosts
os.environ.setdefault("OMP_NUM_THREADS", "1")

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

print("[image_processing] Using CPU-based background removal")

# Import rembg here so any model-download errors appear at startup, not mid-request
try:
    from rembg import remove as _rembg_remove, new_session as _new_session
    _RMBG_MODEL = os.getenv("RMBG_MODEL", "u2netp").strip() or "u2netp"
    _rembg_session = _new_session(_RMBG_MODEL)
    log.info("[image_processing] rembg imported successfully (model: %s)", _RMBG_MODEL)
except Exception as _e:
    log.error("[image_processing] rembg import FAILED: %s", _e)
    _rembg_remove = None  # type: ignore
    _rembg_session = None  # type: ignore


def _ensure_rembg():
    """Raise a clear ValueError if rembg is unavailable."""
    if _rembg_remove is None:
        raise ValueError(
            "rembg is not available. Check that 'rembg[cpu]' and 'onnxruntime' "
            "are installed and that the ONNX model downloaded correctly."
        )

# Directory for local fallback: project_root/uploads/processed/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOADS_PROCESSED_DIR = _PROJECT_ROOT / "uploads" / "processed"


def _ensure_processed_dir() -> Path:
    """Create uploads/processed/ if it does not exist. Return the directory path."""
    UPLOADS_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOADS_PROCESSED_DIR


def _process_image_bytes(image_bytes: bytes) -> bytes:
    """
    Run rembg background removal on raw image bytes and composite result onto
    a white background.

    Returns:
        PNG bytes of the processed image (white background, no transparency).
    """
    _ensure_rembg()

    try:
        input_image = Image.open(io.BytesIO(image_bytes))
        input_image = ImageOps.exif_transpose(input_image).convert("RGBA")
    except Exception as e:
        raise ValueError(f"Invalid or unsupported image: {e}") from e

    # Speed/Memory guardrail for server workloads:
    # rembg on large phone photos can be very slow and memory-heavy.
    max_side = int(os.getenv("RMBG_MAX_SIDE", "1280"))
    if max(input_image.size) > max_side:
        input_image.thumbnail((max_side, max_side), Image.LANCZOS)

    try:
        output_image = _rembg_remove(input_image, session=_rembg_session)  # type: ignore[misc]
    except Exception as e:
        log.error("[image_processing] rembg.remove() failed: %s", e, exc_info=True)
        raise ValueError(f"Background removal failed: {e}") from e

    # Log transparency ratio for diagnostics
    import numpy as np
    arr = np.array(output_image)
    if arr.shape[-1] == 4:
        transparent_ratio = (arr[:, :, 3] < 10).sum() / arr[:, :, 3].size
        log.info("[image_processing] Transparency ratio: %.1f%%", transparent_ratio * 100)

    # Composite onto white background so saved file is always visible
    final = Image.new("RGB", output_image.size, (255, 255, 255))
    if output_image.mode == "RGBA":
        final.paste(output_image, mask=output_image.split()[3])
    else:
        final.paste(output_image)

    buf = io.BytesIO()
    # JPEG is much smaller/faster to write and transfer than PNG for photos.
    final.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()


def remove_background_and_save(image_bytes: bytes) -> str:
    """
    Run background removal on the given image bytes.

    Storage:
      - If GCS is configured (GCS_BUCKET env var set) → uploads to GCS,
        returns the public ``https://storage.googleapis.com/…`` URL.
      - Otherwise → saves to uploads/processed/<uuid>.png,
        returns the relative path ``uploads/processed/<uuid>.png``.

    Args:
        image_bytes: Raw bytes of the uploaded image (JPEG/PNG/etc.).

    Returns:
        Either a full GCS URL or a relative path string.

    Raises:
        ValueError: If the image cannot be opened or processed.
    """
    filename = f"{uuid.uuid4().hex}.jpg"

    try:
        processed_bytes = _process_image_bytes(image_bytes)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Image processing error: {e}") from e

    # ── 1. Try GCS first (production) ───────────────────────────────────────
    from services.gcs_storage import upload_bytes as _gcs_upload
    gcs_url = _gcs_upload(processed_bytes, filename, content_type="image/jpeg")
    if gcs_url:
        return gcs_url  # full https:// URL

    # ── 2. Fall back to local disk (development) ─────────────────────────────
    _ensure_processed_dir()
    output_path = UPLOADS_PROCESSED_DIR / filename
    output_path.write_bytes(processed_bytes)
    log.info("[image_processing] Saved locally: %s", output_path)
    return f"uploads/processed/{filename}"


def remove_background_and_save_from_path(input_path: str) -> str:
    """
    Run background removal on an image file path.
    Delegates to remove_background_and_save() after reading the file.
    """
    with open(input_path, "rb") as f:
        image_bytes = f.read()
    return remove_background_and_save(image_bytes)
