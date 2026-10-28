"""
Image processing service: background removal and image normalisation.
Runs in CPU-only mode — compatible with Cloud Run and other serverless hosts.

Nothing here stores anything: photos are kept by services/photo_store.py (private storage).
"""
import io
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Optional

# Prevent threading contention on single-core hosts
os.environ.setdefault("OMP_NUM_THREADS", "1")

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# rembg is loaded lazily, once, behind a lock.
#
# Loading at import time meant every process start (and every test run) paid
# for the ONNX model, and a failed download crashed or silently disabled the
# whole module. Now the first caller loads it; call prewarm_rembg() at startup
# (main.py does, in a background thread) so the first user request is fast.
# In Docker the model is baked into the image (see Dockerfile) so there is no
# network download on cold start.
# ---------------------------------------------------------------------------
_rembg_lock = threading.Lock()
_rembg_remove = None
_rembg_session = None
_rembg_error: Optional[str] = None


def _load_rembg() -> None:
    """Load rembg + the ONNX model on first use. Raises ValueError if unavailable."""
    global _rembg_remove, _rembg_session, _rembg_error
    if _rembg_session is not None:
        return
    with _rembg_lock:
        if _rembg_session is not None:
            return
        if _rembg_error:
            raise ValueError(_rembg_error)
        try:
            from rembg import new_session, remove
            model = os.getenv("RMBG_MODEL", "u2netp").strip() or "u2netp"
            _rembg_session = new_session(model)
            _rembg_remove = remove
            log.info("[image_processing] rembg ready (model: %s)", model)
        except Exception as exc:  # noqa: BLE001
            _rembg_error = (
                "rembg is not available. Check that 'rembg[cpu]' and 'onnxruntime' "
                f"are installed and the ONNX model is present ({type(exc).__name__})."
            )
            log.error("[image_processing] %s", _rembg_error, exc_info=True)
            raise ValueError(_rembg_error) from exc


_model_sessions: dict = {}


def remove_background_with_model(image: Image.Image, model_name: str) -> Image.Image:
    """
    Background removal with a specific rembg model, sessions cached per model name.

    The app-wide default (RMBG_MODEL, a tiny fast model) is fine for previews, but the
    studio-shot pipeline wants cleaner edges, so it can ask for a larger model without
    changing what every other endpoint loads. Blocking: call from a worker thread.
    """
    try:
        from rembg import new_session, remove
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"rembg is not available ({type(exc).__name__}).") from exc
    with _rembg_lock:
        session = _model_sessions.get(model_name)
        if session is None:
            session = _model_sessions[model_name] = new_session(model_name)
            log.info("[image_processing] rembg ready (model: %s)", model_name)

    # Take only the MASK from the model and apply it to the photo's own pixels. rembg's
    # default cutout blends semi-transparent edge pixels toward black, which shows up as
    # dark fringes and wedges (white shirts look grubby). Colours must stay true.
    rgb = image.convert("RGB")
    mask = remove(rgb, session=session, only_mask=True)
    cut = rgb.convert("RGBA")
    cut.putalpha(mask.convert("L"))
    return cut


def prewarm_rembg() -> None:
    """Best-effort warm-up; never raises."""
    try:
        _load_rembg()
    except ValueError:
        pass


def remove_background_image(image: Image.Image) -> Image.Image:
    """Run background removal on a PIL image (blocking — call from a worker thread)."""
    _load_rembg()
    return _rembg_remove(image, session=_rembg_session)  # type: ignore[misc]

def _process_image_bytes(image_bytes: bytes) -> bytes:
    """
    Run rembg background removal on raw image bytes and composite result onto
    a white background.

    Returns:
        PNG bytes of the processed image (white background, no transparency).
    """
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
        output_image = remove_background_image(input_image)
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


# Public name for routers (the underscore version is kept for older imports).
process_image_bytes = _process_image_bytes


def normalize_to_jpeg(image_bytes: bytes, max_side: int = 1600) -> bytes:
    """
    Decode and re-encode an upload as a plain JPEG.

    Used whenever we must keep the user's original photo: it guarantees the stored object
    really is an image (never an SVG/HTML file smuggled in with an image/* content type),
    strips EXIF metadata including GPS location, and bounds the stored size.
    Raises ValueError if the bytes are not a decodable image.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid or unsupported image: {type(exc).__name__}") from exc
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)   # no exif= argument => metadata dropped
    return buf.getvalue()
