"""
Image processing service: background removal and saving processed clothing images.
Runs in CPU-only mode — compatible with Render and other serverless hosts.
"""
import io
import os
import uuid
from pathlib import Path

# Prevent threading contention on Render / single-core hosts
os.environ.setdefault("OMP_NUM_THREADS", "1")

from PIL import Image
from rembg import remove

print("[image_processing] Using CPU-based background removal")

# Directory for processed images: project_root/uploads/processed/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOADS_PROCESSED_DIR = _PROJECT_ROOT / "uploads" / "processed"


def _ensure_processed_dir() -> Path:
    """Create uploads/processed/ if it does not exist. Return the directory path."""
    UPLOADS_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOADS_PROCESSED_DIR


def remove_background_and_save(image_bytes: bytes) -> str:
    """
    Run background removal on the given image bytes and save the result to
    uploads/processed/<unique_id>.png.

    Args:
        image_bytes: Raw bytes of the uploaded image (e.g. JPEG/PNG).

    Returns:
        Relative path to the saved image, e.g. "uploads/processed/<uuid>.png".

    Raises:
        ValueError: If the image cannot be opened or processed.
    """
    _ensure_processed_dir()

    try:
        input_image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as e:
        raise ValueError(f"Invalid or unsupported image: {e}") from e

    output_image = remove(input_image)

    filename = f"{uuid.uuid4().hex}.png"
    output_path = UPLOADS_PROCESSED_DIR / filename
    output_image.save(output_path, format="PNG")

    return os.path.join("uploads", "processed", filename)


def remove_background_and_save_from_path(input_path: str) -> str:
    """
    Run background removal on an image file and save the result to
    uploads/processed/<unique_id>.png.

    Args:
        input_path: Path to the temporary uploaded image file.

    Returns:
        Relative path to the saved image, e.g. "uploads/processed/<uuid>.png".
    """
    with open(input_path, "rb") as f:
        image_bytes = f.read()
    return remove_background_and_save(image_bytes)
