try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from routers import auth, upload, wardrobe, recommend, skin_tone, images
from database import init_db

app = FastAPI(
  title="ClosetMate AI Backend",
  description="AI-powered wardrobe management and outfit recommendation API",
  version="0.1.0",
)

# ---------------------------------------------------------------------------
# CORS — allow any origin so physical devices, emulators, and web clients
# can all reach the API without preflight failures.
# In production, replace "*" with your specific allowed origins.
# ---------------------------------------------------------------------------
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=False,
  allow_methods=["*"],
  allow_headers=["*"],
)

# Ensure database schema is created on startup/import.
init_db()

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])
app.include_router(wardrobe.router, prefix="/wardrobe", tags=["Wardrobe"])
app.include_router(recommend.router, prefix="/recommend", tags=["Recommend"])
app.include_router(skin_tone.router, prefix="", tags=["Skin Tone"])
app.include_router(images.router, prefix="/images", tags=["Images"])

# Root-level aliases so the mobile app can call /remove-bg and /style-image directly
# (same handlers, just exposed at the root path the frontend expects)
app.include_router(images.router, prefix="", tags=["Images (root aliases)"])

# Serve uploaded/processed images over HTTP so any device can display them
_uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")


@app.get("/")
def root():
  return {"message": "ClosetMate Backend Running"}


@app.get("/health")
def health():
  """Simple health-check endpoint for uptime monitors and CI checks."""
  return {"status": "ok", "version": "0.1.0"}
