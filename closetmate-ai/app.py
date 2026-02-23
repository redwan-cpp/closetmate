import base64
import json
import os
import asyncio

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import Response
from openai import OpenAI
from PIL import (
    Image,
    ImageFilter,
    ImageStat,
    ImageEnhance,
)
import numpy as np
import io
from rembg import remove

# --------------------------------------------------
# App
# --------------------------------------------------

app = FastAPI(title="ClosetMate AI Service")

# --------------------------------------------------
# Lighting Analysis
# --------------------------------------------------

def analyze_lighting(image: Image.Image):
    img = image.convert("RGB")

    grayscale = img.convert("L")
    brightness = ImageStat.Stat(grayscale).mean[0]
    brightness_norm = brightness / 255.0

    contrast = ImageStat.Stat(grayscale).stddev[0]
    contrast_norm = min(contrast / 128.0, 1.0)

    np_img = np.array(img)
    r_mean = np.mean(np_img[:, :, 0])
    b_mean = np.mean(np_img[:, :, 2])
    warmth = (r_mean - b_mean) / 255.0

    return {
        "brightness": round(brightness_norm, 3),
        "contrast": round(contrast_norm, 3),
        "warmth": round(warmth, 3),
    }

# --------------------------------------------------
# Correction Rules
# --------------------------------------------------

def compute_corrections(analysis):
    brightness = analysis["brightness"]
    contrast = analysis["contrast"]
    warmth = analysis["warmth"]

    # Brightness
    brightness_factor = 1.0
    if brightness < 0.30:
        brightness_factor = 1.08
    elif brightness < 0.38:
        brightness_factor = 1.04
    elif brightness > 0.78:
        brightness_factor = 0.94
    elif brightness > 0.68:
        brightness_factor = 0.97

    # Contrast
    contrast_factor = 1.0
    if contrast < 0.14:
        contrast_factor = 1.06
    elif contrast < 0.18:
        contrast_factor = 1.03
    elif contrast > 0.55:
        contrast_factor = 0.93
    elif contrast > 0.40:
        contrast_factor = 0.96

    # Safety net
    if brightness_factor != 1.0 and contrast_factor != 1.0:
        brightness_factor = 1 + (brightness_factor - 1) * 0.5
        contrast_factor = 1 + (contrast_factor - 1) * 0.5

    # Warmth
    warmth_shift = 0
    if warmth > 0.15:
        warmth_shift = -4
    elif warmth > 0.08:
        warmth_shift = -2
    elif warmth < -0.15:
        warmth_shift = +4
    elif warmth < -0.05:
        warmth_shift = +2

    return {
        "brightness": brightness_factor,
        "contrast": contrast_factor,
        "warmth_shift": warmth_shift,
    }

# --------------------------------------------------
# Apply Corrections
# --------------------------------------------------

def apply_lighting_corrections(image: Image.Image, corrections):
    img = image

    if corrections["brightness"] != 1.0:
        img = ImageEnhance.Brightness(img).enhance(corrections["brightness"])

    if corrections["contrast"] != 1.0:
        img = ImageEnhance.Contrast(img).enhance(corrections["contrast"])

    shift = corrections["warmth_shift"]
    if shift != 0:
        r, g, b = img.split()
        r = r.point(lambda i: min(255, i + shift))
        b = b.point(lambda i: max(0, i - shift))
        img = Image.merge("RGB", (r, g, b))

    return img

# --------------------------------------------------
# Editorial Background (Style A)
# --------------------------------------------------

def create_editorial_background(size):
    width, height = size
    top_color = (250, 250, 250)
    bottom_color = (241, 241, 241)

    bg = Image.new("RGB", size, top_color)
    pixels = bg.load()

    for y in range(height):
        ratio = y / height
        r = int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio)
        g = int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio)
        b = int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio)
        for x in range(width):
            pixels[x, y] = (r, g, b)

    return bg

# --------------------------------------------------
# Clothing analysis (OpenAI Vision)
# --------------------------------------------------

CLOTHING_ANALYSIS_PROMPT = """Analyze this image of a single clothing or apparel item. Return a JSON object with exactly these three keys (no other keys, no markdown, no explanation):
- "category": one of Shirt, Saree, Panjabi, Dress, Jeans, Top, Bottom, Footwear, Outerwear, Accessory, or another specific clothing type if none fit.
- "primary_color": the main color (e.g. Navy, White, Red, Mustard, Green).
- "pattern": one of solid, striped, floral, embroidered, printed, checked, polka dot, geometric, or other if needed."""


def _analyze_clothing_image_sync(image_base64: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": CLOTHING_ANALYSIS_PROMPT,
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                ],
            }
        ],
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from model: {e}") from e
    category = data.get("category") or "Unknown"
    primary_color = data.get("primary_color") or "Unknown"
    pattern = data.get("pattern") or "solid"
    return {"category": category, "primary_color": primary_color, "pattern": pattern}


# --------------------------------------------------
# Endpoints
# --------------------------------------------------

@app.post("/analyze-image")
async def analyze_image(file: UploadFile = File(...)):
    input_bytes = await file.read()
    image = Image.open(io.BytesIO(input_bytes))
    return analyze_lighting(image)


@app.post("/analyze-clothing")
async def analyze_clothing(file: UploadFile = File(...)):
    """Analyze clothing image with OpenAI Vision. Returns category, primary_color, pattern."""
    try:
        input_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}") from e
    if not input_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    image_b64 = base64.standard_b64encode(input_bytes).decode("ascii")
    try:
        result = await asyncio.to_thread(_analyze_clothing_image_sync, image_b64)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Clothing analysis failed: {e}",
        ) from e
    return result


@app.post("/style-image")
async def style_image(file: UploadFile = File(...)):
    # Read input
    input_bytes = await file.read()
    original = Image.open(io.BytesIO(input_bytes)).convert("RGBA")

    # Analyze lighting (from original)
    analysis = analyze_lighting(original)
    corrections = compute_corrections(analysis)

    # Remove background (intermediate)
    foreground = remove(original)

    # Canvas
    CANVAS_SIZE = (768, 768)
    canvas = create_editorial_background(CANVAS_SIZE).convert("RGBA")

    # Resize foreground
    scale = min(
        CANVAS_SIZE[0] / foreground.width,
        CANVAS_SIZE[1] / foreground.height,
    ) * 0.88

    new_size = (
        int(foreground.width * scale),
        int(foreground.height * scale),
    )
    foreground = foreground.resize(new_size, Image.LANCZOS)

    # Composition (editorial offset)
    x = (CANVAS_SIZE[0] - foreground.width) // 2
    y = int((CANVAS_SIZE[1] - foreground.height) * 0.38)

    # Ambient depth
    shadow = Image.new("RGBA", foreground.size, (0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(28))
    canvas.paste(shadow, (x + 6, y + 18), shadow)

    # Paste garment
    canvas.paste(foreground, (x, y), foreground)

    # Apply lighting corrections
    final_rgb = apply_lighting_corrections(
        canvas.convert("RGB"),
        corrections,
    )

    # Output
    output_buffer = io.BytesIO()
    final_rgb.save(output_buffer, format="JPEG", quality=95)
    output_buffer.seek(0)

    return Response(
        content=output_buffer.read(),
        media_type="image/jpeg",
    )


@app.post("/remove-background")
async def remove_background(file: UploadFile = File(...)):
    # Read uploaded image
    input_bytes = await file.read()
    input_image = Image.open(io.BytesIO(input_bytes))

    # Remove background
    output_image = remove(input_image)

    # Convert to PNG
    output_buffer = io.BytesIO()
    output_image.save(output_buffer, format="PNG")
    output_buffer.seek(0)

    return Response(
        content=output_buffer.read(),
        media_type="image/png"
    )