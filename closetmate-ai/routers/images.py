"""
Image processing router: packages app.py endpoints into a FastAPI APIRouter
so they can be included in main.py under /images/.

Endpoints:
  POST /images/analyze-lighting  — lighting analysis
  POST /images/remove-background — PNG binary output
  POST /images/remove-bg         — base64 JSON output
  POST /images/style             — editorial background + garment placement
"""
from __future__ import annotations

import base64
import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

from services.image_processing import remove_background_and_save

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers (imported from app.py logic via shared modules,
# duplicated here to keep app.py fully standalone)
# ---------------------------------------------------------------------------

def _analyze_lighting(image: Image.Image) -> dict:
    from PIL import ImageStat
    import numpy as np

    img = image.convert("RGB")
    grayscale = img.convert("L")
    brightness = ImageStat.Stat(grayscale).mean[0]
    contrast = ImageStat.Stat(grayscale).stddev[0]
    np_img = np.array(img)
    warmth = (float(np_img[:, :, 0].mean()) - float(np_img[:, :, 2].mean())) / 255.0
    return {
        "brightness": round(brightness / 255.0, 3),
        "contrast": round(min(contrast / 128.0, 1.0), 3),
        "warmth": round(warmth, 3),
    }


@router.post(
    "/analyze-lighting",
    summary="Analyze image lighting: brightness, contrast, warmth",
)
async def analyze_lighting_endpoint(file: UploadFile = File(...)) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        image = Image.open(io.BytesIO(body))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Cannot decode image: {e}") from e
    return _analyze_lighting(image)


@router.post(
    "/remove-bg",
    summary="Remove background and return base64-encoded PNG",
)
async def remove_bg_endpoint(file: UploadFile = File(...)) -> dict:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        from rembg import remove as rembg_remove
        image = Image.open(io.BytesIO(body))
        output = rembg_remove(image)
        buf = io.BytesIO()
        output.save(buf, format="PNG")
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return {"image": b64}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {e}") from e


@router.post(
    "/remove-background",
    summary="Remove background and return PNG binary",
)
async def remove_background_endpoint(file: UploadFile = File(...)) -> Response:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        from rembg import remove as rembg_remove
        image = Image.open(io.BytesIO(body))
        output = rembg_remove(image)
        buf = io.BytesIO()
        output.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {e}") from e


@router.post(
    "/style",
    summary="Remove background and place garment on editorial background",
)
async def style_image_endpoint(file: UploadFile = File(...)) -> Response:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        from rembg import remove as rembg_remove
        from PIL import ImageFilter, ImageEnhance
        import numpy as np

        original = Image.open(io.BytesIO(body)).convert("RGBA")

        # Lighting analysis
        analysis = _analyze_lighting(original)

        # Remove background
        foreground = rembg_remove(original)

        # Create editorial gradient background
        CANVAS_SIZE = (768, 768)
        top_color = (250, 250, 250)
        bottom_color = (241, 241, 241)
        canvas = Image.new("RGBA", CANVAS_SIZE, top_color)
        pixels = canvas.load()
        for y in range(CANVAS_SIZE[1]):
            ratio = y / CANVAS_SIZE[1]
            r = int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio)
            g = int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio)
            b = int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio)
            for x in range(CANVAS_SIZE[0]):
                pixels[x, y] = (r, g, b, 255)

        # Scale and position garment
        scale = min(CANVAS_SIZE[0] / foreground.width, CANVAS_SIZE[1] / foreground.height) * 0.88
        new_size = (int(foreground.width * scale), int(foreground.height * scale))
        foreground = foreground.resize(new_size, Image.LANCZOS)
        x = (CANVAS_SIZE[0] - foreground.width) // 2
        y = int((CANVAS_SIZE[1] - foreground.height) * 0.38)

        # Ambient shadow
        shadow = Image.new("RGBA", foreground.size, (0, 0, 0, 90))
        shadow = shadow.filter(ImageFilter.GaussianBlur(28))
        canvas.paste(shadow, (x + 6, y + 18), shadow)
        canvas.paste(foreground, (x, y), foreground)

        # Output as JPEG
        buf = io.BytesIO()
        canvas.convert("RGB").save(buf, format="JPEG", quality=95)
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Style image failed: {e}") from e
