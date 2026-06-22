"""FastAPI application and image-analysis request orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.config import MAX_UPLOAD_BYTES, UPLOAD_DIR, cors_origins
from app.services import groq_service, history_service, vision_service
from app.text import (
    classify_intent,
    extract_find_target,
    extract_target,
    format_response,
    normalize,
    prettify_target,
)


def create_app() -> FastAPI:
    application = FastAPI(title="AI Smart Glass API", version="1.0.0")
    origins = cors_origins()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return application


app = create_app()


@app.get("/")
def root() -> dict[str, object]:
    return {"ok": True, "service": "AI Smart Glass API", "docs": "/docs"}


@app.get("/ping")
def ping() -> dict[str, object]:
    return {"ok": True, "msg": "pong"}


async def _save_upload(file: UploadFile) -> Path:
    suffix = Path(file.filename or "capture.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise ValueError("Ảnh vượt quá giới hạn dung lượng")
                output.write(chunk)
        if total == 0:
            raise ValueError("Tệp ảnh rỗng")
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _target_from_history_prompt(prompt: str) -> Optional[str]:
    normalized = normalize(prompt)
    target = extract_find_target(normalized) or extract_target(normalized, ["tim"])
    if target:
        return target
    target, _ = groq_service.extract_find_target(prompt)
    return target


def _analyze_image(path: Path, intent: str, target: Optional[str], unknown: bool) -> dict:
    if intent == "ocr":
        text = groq_service.extract_text(path)
        return {"text": text or "Không đọc được văn bản trong ảnh."}

    if intent == "find":
        if not target:
            return {
                "status": "clarify",
                "text": "Bạn muốn tìm gì?",
                "need_clarification": True,
            }
        pretty_target = prettify_target(target)
        score = vision_service.similarity(pretty_target, path)
        decision = "Có thể có" if score >= 0.22 else "Khó thấy"
        return {
            "text": f"{decision} '{pretty_target}' (độ tin cậy {score:.2f}).",
            "data": {"target": pretty_target, "similarity": score},
        }

    try:
        detections = vision_service.detect_objects(path)
    except Exception:
        # Captioning can still describe a scene when object detection is unavailable.
        if intent == "count":
            raise
        detections = []
    counts = vision_service.object_counts(detections)
    if intent == "count" and target:
        pretty_target = prettify_target(target)
        target_normalized = normalize(pretty_target)
        count = next(
            (
                value
                for name, value in counts.items()
                if name == target_normalized
                or name in target_normalized
                or target_normalized in name
            ),
            0,
        )
        text = f"Có khoảng {count} {pretty_target}." if count else f"Không thấy {pretty_target}."
        return {"text": text, "data": {"target": pretty_target, "count": count, "counts": counts}}

    caption = ""
    try:
        caption = vision_service.caption_image(path)
    except Exception:
        pass
    base_text = vision_service.describe(caption, detections)
    text = groq_service.summarize(base_text, counts)
    if unknown:
        text = "Tôi chưa hiểu yêu cầu nên sẽ mô tả cảnh vật. " + text
    return {"text": text, "data": {"counts": counts}}


@app.post("/analyze")
@app.post("/analyze/")
async def analyze(
    file: UploadFile = File(...),
    prompt: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
) -> dict[str, object]:
    request_prompt = (prompt or "").strip()
    intent, target, unknown = classify_intent(request_prompt)
    try:
        history_service.add(request_prompt)
    except OSError:
        pass

    if intent == "history":
        text = history_service.query(_target_from_history_prompt(request_prompt))
        return {
            "status": "success",
            "intent": intent,
            "file": file.filename,
            "text": format_response(text, language),
        }

    path: Optional[Path] = None
    try:
        path = await _save_upload(file)
        result = _analyze_image(path, intent, target, unknown)
        status = result.pop("status", "success")
        result["text"] = format_response(str(result.get("text", "")), language)
        return {"status": status, "intent": intent, "file": file.filename, **result}
    except Exception as exc:
        return {
            "status": "error",
            "intent": intent,
            "file": file.filename,
            "text": format_response(f"Lỗi xử lý: {exc}", language),
        }
    finally:
        if path and os.getenv("KEEP_UPLOADS", "false").lower() != "true":
            path.unlink(missing_ok=True)
