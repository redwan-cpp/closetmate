"""
photo_store.py — where closet photos live.

Photos are PRIVATE. The database keeps only an object *key*

    photos/<user_id>/<photo_id>.webp        a cutout with a transparent background
    photos/<user_id>/<photo_id>.jpg         an opaque photo
    photos/<user_id>/<photo_id>_t.<ext>     its thumbnail

and every API response that shows a photo turns the key into a short-lived link
(`files/<key>?e=<expiry>&s=<signature>`) that the app opens through GET /files/…
(routers/files.py). The signature is an HMAC we compute locally, so a closet of 200 pieces costs
microseconds — real GCS signed URLs would need a service-account key or one IAM call per image.
A photo id never changes its content, so the app caches it forever.

Two backends share one interface: GcsStore (production, a PRIVATE bucket with public access
prevention on; the Cloud Run service account needs only roles/storage.objectUser on it) and
DiskStore (dev and tests, in photo_store/).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text

from settings import get_settings

log = logging.getLogger(__name__)

# user ids are UUIDs today, but accept any URL-safe id: the pattern is the path-traversal guard.
KEY_RE = re.compile(
    # \Z, not $: "$" also matches just before a trailing newline, which would let "…/x.webp\n" through.
    r"^photos/(?P<uid>[A-Za-z0-9_-]{1,64})/(?P<pid>[0-9a-f]{32})(?P<thumb>_t)?\.(?P<ext>webp|jpg)\Z"
)
_CONTENT_TYPES = {"webp": "image/webp", "jpg": "image/jpeg"}

# Only real photo formats are ever decoded (Pillow can also open EPS via Ghostscript and more). Plugins
# register lazily, so load them first and keep only the ones this Pillow build actually has.
Image.init()
_PHOTO_FORMATS = [f for f in ("JPEG", "PNG", "WEBP", "GIF", "MPO", "BMP") if f in Image.OPEN]

MAX_SIDE = 1280               # longest side of a stored photo
THUMB_BOX = (320, 400)        # thumbnails fit inside this


class PhotoError(ValueError):
    """The upload is not a usable photo (the message is safe to show to the user)."""


class PhotoLimitError(RuntimeError):
    """The user already stores the maximum number of photos (or bytes)."""


class AccountGone(RuntimeError):
    """The account this write is for no longer exists (e.g. a token that outlived a deletion)."""


# ---------------------------------------------------------------------------
# Keys and links
# ---------------------------------------------------------------------------

def make_keys(user_id: str, ext: str, photo_id: Optional[str] = None) -> Tuple[str, str, str]:
    """(photo_id, key, thumb_key) for a new photo."""
    pid = photo_id or uuid.uuid4().hex
    return pid, f"photos/{user_id}/{pid}.{ext}", f"photos/{user_id}/{pid}_t.{ext}"


def key_owner(path: Optional[str]) -> Optional[str]:
    """The user id a photo key belongs to, or None if `path` is not a (full-size) photo key."""
    m = KEY_RE.match(path or "")
    return m.group("uid") if m and not m.group("thumb") else None


def content_type_for(key: str) -> str:
    m = KEY_RE.match(key)
    return _CONTENT_TYPES[m.group("ext")] if m else "application/octet-stream"


def _link_secret() -> bytes:
    # Derived from the JWT secret, so rotating it also invalidates every outstanding link
    # (the app just refetches its lists) and no second secret has to be managed.
    return hmac.new(get_settings().jwt_secret.encode("utf-8"), b"closetmate-photo-links", hashlib.sha256).digest()


def _sign(key: str, expires: int) -> str:
    digest = hmac.new(_link_secret(), f"{key}|{expires}".encode("utf-8"), hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def link(key: str, now: Optional[float] = None) -> str:
    """
    A relative link (the app prefixes the backend URL, like it does for uploads/…).

    The expiry is rounded to fixed windows, so the same photo gets the SAME link for hours: lists
    don't churn the app's image cache, and a link is always valid for between ttl/2 and ttl.
    """
    ttl = max(120, get_settings().photo_url_ttl_seconds)
    window = ttl // 2
    expires = (int((now if now is not None else time.time()) // window) + 2) * window
    return f"files/{key}?e={expires}&s={_sign(key, expires)}"


def verify_link(key: str, expires: str, signature: str, now: Optional[float] = None) -> bool:
    """True only for a link we signed that has not expired. Never raises: it faces the public internet."""
    try:
        # isascii(): str.isdigit() also accepts characters like "²" that int() then rejects.
        if not KEY_RE.match(key) or not (expires.isascii() and expires.isdigit()) or len(expires) > 12:
            return False
        if not signature or not signature.isascii():
            return False
        if int(expires) < (now if now is not None else time.time()):
            return False
        return hmac.compare_digest(_sign(key, int(expires)).encode("ascii"), signature.encode("ascii"))
    except Exception:  # noqa: BLE001
        return False


def present(path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    (image, thumbnail) to put in an API response for a stored image path.

    A photo key becomes two signed links; anything older (file://, uploads/…, a URL) is returned
    unchanged with no thumbnail, exactly as before.
    """
    m = KEY_RE.match(path or "")
    if not path or not m or m.group("thumb"):
        return path, None
    thumb_key = f"photos/{m.group('uid')}/{m.group('pid')}_t.{m.group('ext')}"
    return link(path), link(thumb_key)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class DiskStore:
    """Dev and tests. Files live under `root`; nothing leaves the machine."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not KEY_RE.match(key):
            raise ValueError("not a photo key")
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("key escapes the storage root")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> Optional[bytes]:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_user(self, user_id: str) -> int:
        folder = (self.root / "photos" / user_id).resolve()
        if (self.root / "photos").resolve() not in folder.parents:
            raise ValueError("not a user folder")
        if not folder.is_dir():
            return 0
        count = sum(1 for p in folder.iterdir() if p.is_file())
        shutil.rmtree(folder, ignore_errors=True)
        return count


class GcsStore:
    """Production. A PRIVATE bucket: objects are never made public and never signed."""

    def __init__(self, bucket_name: str):
        from google.cloud import storage  # imported lazily: dev/test never need it

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        blob = self._bucket.blob(key)
        blob.cache_control = "private, max-age=31536000, immutable"
        blob.upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> Optional[bytes]:
        from google.api_core.exceptions import NotFound

        try:
            return self._bucket.blob(key).download_as_bytes()
        except NotFound:
            return None

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self._bucket.blob(key).delete()
        except NotFound:
            pass

    def delete_user(self, user_id: str) -> int:
        """Delete every object under the user's prefix. Raises if any deletion fails (so the caller can retry)."""
        from concurrent.futures import ThreadPoolExecutor

        from google.api_core.exceptions import NotFound

        blobs = list(self._client.list_blobs(self._bucket, prefix=f"photos/{user_id}/"))

        def remove(blob) -> None:
            try:
                blob.delete()
            except NotFound:                   # already gone: fine
                pass

        # One request per object, but 16 at a time: a 600-photo closet (1,200 objects) takes seconds, not minutes.
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(remove, blobs))      # list(): surface the first exception
        return len(blobs)


_store: Any = None


def get_store() -> Any:
    """The configured backend (created on first use)."""
    global _store
    if _store is None:
        bucket = get_settings().gcs_bucket
        # NOT under uploads/: that folder is served as static files in dev, which would publish
        # photos without a signature. Here they are reachable only through GET /files/….
        _store = GcsStore(bucket) if bucket else DiskStore(Path(__file__).resolve().parent.parent / "photo_store")
    return _store


def set_store(store: Any) -> None:
    """Swap the backend (tests); pass None to forget it and re-read the settings."""
    global _store
    _store = store


# ---------------------------------------------------------------------------
# Preparing an upload
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Prepared:
    full: bytes
    thumb: bytes
    ext: str                 # "webp" (has transparency) | "jpg" (opaque)
    width: int
    height: int


def _has_transparency(img: Image.Image) -> bool:
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    if img.mode not in ("RGBA", "LA"):
        return False
    return img.getchannel("A").getextrema()[0] < 255      # a fully opaque alpha channel is just a JPEG


def _encode(img: Image.Image, ext: str) -> bytes:
    buf = io.BytesIO()
    if ext == "webp":
        img.convert("RGBA").save(buf, format="WEBP", quality=85, method=4)
    else:
        img.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def prepare_photo(body: bytes) -> Prepared:
    """
    Decode an uploaded image and re-encode it from scratch: orientation applied, longest side
    capped, EXIF (GPS!) and anything else hiding in the file dropped, and a thumbnail made.
    Transparent images stay WebP (cutouts); opaque ones become JPEG.
    """
    try:
        # Only real photo formats: Pillow can also open EPS (Ghostscript) and a few exotic ones.
        img = Image.open(io.BytesIO(body), formats=_PHOTO_FORMATS)
        if img.format == "JPEG":
            # Let the decoder shrink big JPEGs while reading (1/2, 1/4 or 1/8): a 36 MP photo then
            # needs a fraction of the memory, and we cap the stored size far below it anyway.
            img.draft("RGB", (MAX_SIDE * 2, MAX_SIDE * 2))
        img.load()
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise PhotoError("Cannot decode image") from exc

    ext = "webp" if _has_transparency(img) else "jpg"
    img = img.convert("RGBA" if ext == "webp" else "RGB")
    # Pillow carries a JPEG comment (and similar text chunks) through convert() and save(): drop
    # everything that is not pixels, so nothing personal (or arbitrary) is stored or served back.
    img.info.clear()
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    width, height = img.size
    thumb = img.copy()
    thumb.thumbnail(THUMB_BOX, Image.LANCZOS)
    return Prepared(_encode(img, ext), _encode(thumb, ext), ext, width, height)


# ---------------------------------------------------------------------------
# Records (the `photos` table) + storage
# ---------------------------------------------------------------------------

def photo_count(db: Any, user_id: str) -> int:
    return int(db.execute(
        text("SELECT COUNT(*) AS n FROM photos WHERE user_id = :u"), {"u": user_id}
    ).fetchone()["n"])


def store_encoded(db: Any, user_id: str, full: bytes, thumb: bytes, ext: str) -> dict:
    """
    Save an already-encoded photo + thumbnail and record it. Returns
    {photo_id, image_path (the key), bytes}. Raises PhotoLimitError when the user is at their
    cap. If anything fails halfway, what was written is removed again.
    """
    # A still-valid access token outlives account deletion by up to 15 minutes: never create rows
    # (or objects) for a user that no longer exists.
    if db.execute(text("SELECT 1 FROM users WHERE user_id = :u"), {"u": user_id}).fetchone() is None:
        raise AccountGone("account no longer exists")
    limits = get_settings()
    used = db.execute(
        text("SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS b FROM photos WHERE user_id = :u"), {"u": user_id}
    ).fetchone()
    if int(used["n"]) >= limits.max_photos_per_user or int(used["b"]) + len(full) + len(thumb) > limits.max_photo_bytes_per_user:
        raise PhotoLimitError("photo limit reached")

    photo_id, key, thumb_key = make_keys(user_id, ext)
    store = get_store()
    content_type = _CONTENT_TYPES[ext]
    written = []
    try:
        for k, data in ((key, full), (thumb_key, thumb)):
            store.put(k, data, content_type)
            written.append(k)
        db.execute(
            text("""INSERT INTO photos (photo_id, user_id, key, thumb_key, size_bytes, created_at)
                    VALUES (:pid, :uid, :key, :thumb, :size, :at)"""),
            {"pid": photo_id, "uid": user_id, "key": key, "thumb": thumb_key,
             "size": len(full) + len(thumb), "at": datetime.now(timezone.utc).isoformat()},
        )
        db.commit()
    except Exception:
        for k in written:
            try:
                store.delete(k)
            except Exception:  # noqa: BLE001 — the original error matters more
                log.warning("could not clean up %s after a failed save", k, exc_info=True)
        raise
    return {"photo_id": photo_id, "image_path": key, "bytes": len(full) + len(thumb)}


def owns_photo(db: Any, user_id: str, key: str) -> bool:
    """True if `key` is a full-size photo this user uploaded (and still has)."""
    if key_owner(key) != user_id:
        return False
    return db.execute(
        text("SELECT 1 FROM photos WHERE user_id = :u AND key = :k"), {"u": user_id, "k": key}
    ).fetchone() is not None


def delete_photo(db: Any, user_id: str, key: Optional[str]) -> None:
    """
    Remove one of the user's photos (objects, then the record). Anything that is not a photo key
    — legacy file:// and uploads/ paths — is ignored. Storage trouble is logged, never raised:
    a leftover object is harmless and the record stays, so a clean-up can find it.
    """
    if not key or key_owner(key) != user_id:
        return
    row = db.execute(
        text("SELECT photo_id, thumb_key FROM photos WHERE user_id = :u AND key = :k"), {"u": user_id, "k": key}
    ).fetchone()
    if row is None:
        return
    if db.execute(
        text("SELECT 1 FROM wardrobe_items WHERE user_id = :u AND image_path = :k"), {"u": user_id, "k": key}
    ).fetchone() is not None:
        return                      # some item still shows it: keep it
    store = get_store()
    try:
        store.delete(key)
        store.delete(row["thumb_key"])
    except Exception:  # noqa: BLE001
        log.warning("could not delete photo objects for %s", key, exc_info=True)
        return
    db.execute(text("DELETE FROM photos WHERE photo_id = :p"), {"p": row["photo_id"]})
    db.commit()


def delete_user_photos(db: Any, user_id: str) -> int:
    """Remove everything a user stored. Returns how many objects went. Raises if storage fails."""
    removed = get_store().delete_user(user_id)
    db.execute(text("DELETE FROM photos WHERE user_id = :u"), {"u": user_id})
    db.commit()
    return removed
