"""Application configuration and filesystem paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "history.json"

GROQ_MODEL = os.getenv(
    "GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
)
GROQ_OCR_MODEL = os.getenv("GROQ_OCR_MODEL", GROQ_MODEL)
CAPTION_MODEL = os.getenv(
    "CAPTION_MODEL", "Salesforce/blip-image-captioning-large"
)
OBJECT_DETECTION_MODEL = os.getenv(
    "OBJECT_DETECTION_MODEL", "facebook/detr-resnet-50"
)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024


def cors_origins() -> list[str]:
    """Return configured CORS origins, using `*` for local development."""
    value = os.getenv("CORS_ORIGINS", "*").strip()
    return [origin.strip() for origin in value.split(",") if origin.strip()] or ["*"]

