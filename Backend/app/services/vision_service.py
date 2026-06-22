"""Image captioning, object detection and CLIP similarity services."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from deep_translator import GoogleTranslator

from app.config import CAPTION_MODEL, OBJECT_DETECTION_MODEL
from app.text import normalize


@lru_cache(maxsize=1)
def _caption_pipeline():
    # Imports and model initialization stay lazy so health checks start quickly.
    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    return pipeline("image-to-text", model=CAPTION_MODEL, device=device)


def caption_image(image_path: Path) -> str:
    result = _caption_pipeline()(str(image_path))
    if not isinstance(result, list) or not result:
        return ""
    first = result[0]
    return str(first.get("generated_text") or first.get("caption") or "").strip()


def detect_objects(image_path: Path) -> list[dict[str, Any]]:
    token = os.getenv("HF_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Thiếu HF_API_TOKEN trong biến môi trường")
    url = f"https://api-inference.huggingface.co/models/{OBJECT_DETECTION_MODEL}"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        data=image_path.read_bytes(),
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Phản hồi nhận diện không hợp lệ: {payload}")
    return payload


def object_counts(detections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for detection in detections:
        label = normalize(str(detection.get("label", "")))
        if label:
            counts[label] = counts.get(label, 0) + 1
    return counts


def describe(caption: str, detections: list[dict[str, Any]]) -> str:
    if caption:
        try:
            return GoogleTranslator(source="auto", target="vi").translate(caption)
        except Exception:
            return caption
    counts = object_counts(detections)
    if not counts:
        return "Không nhận diện được nội dung trong ảnh."
    items = [f"{count} {name}" for name, count in counts.items()]
    return "Phía trước có " + ", ".join(items) + "."


@lru_cache(maxsize=1)
def _clip_model():
    import clip
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, preprocess = clip.load("ViT-B/32", device=device)
    return model, preprocess, device


def similarity(text: str, image_path: Path) -> float:
    import clip
    import torch
    from langdetect import detect
    from PIL import Image

    query = text
    try:
        if detect(query) == "vi":
            query = GoogleTranslator(source="vi", target="en").translate(query)
    except Exception:
        pass

    model, preprocess, device = _clip_model()
    image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)
    tokens = clip.tokenize([query]).to(device)
    with torch.no_grad():
        image_features = model.encode_image(image)
        text_features = model.encode_text(tokens)
    image_features /= image_features.norm(dim=-1, keepdim=True)
    text_features /= text_features.norm(dim=-1, keepdim=True)
    return float((image_features @ text_features.T).item())

