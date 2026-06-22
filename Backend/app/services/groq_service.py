"""Small, failure-tolerant wrapper around Groq chat and vision APIs."""

from __future__ import annotations

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import Optional

from groq import Groq

from app.config import GROQ_MODEL, GROQ_OCR_MODEL


def _client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Thiếu GROQ_API_KEY trong biến môi trường")
    return Groq(api_key=api_key)


def _content(completion) -> str:
    if not completion or not completion.choices:
        return ""
    return (completion.choices[0].message.content or "").strip()


def classify_intent(prompt: str) -> Optional[str]:
    """Classify a prompt; return None so callers can use deterministic keywords."""
    if not os.getenv("GROQ_API_KEY", "").strip():
        return None
    try:
        completion = _client().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            max_tokens=4,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Phân loại yêu cầu và chỉ trả về một số: "
                        "0=không rõ, 1=mô tả, 2=đếm, 3=tìm, 4=đọc chữ, 5=lịch sử."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        digit = next((char for char in _content(completion) if char.isdigit()), "0")
        return {
            "1": "describe",
            "2": "count",
            "3": "find",
            "4": "ocr",
            "5": "history",
        }.get(digit)
    except Exception:
        return None


def extract_find_target(prompt: str) -> tuple[Optional[str], Optional[int]]:
    try:
        completion = _client().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0,
            max_tokens=16,
            messages=[
                {
                    "role": "system",
                    "content": "Chỉ trả về '<SỐ>|<TÊN ĐỒ VẬT>', không giải thích.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        match = re.match(r"^\s*(\d+)\s*\|\s*(.+?)\s*$", _content(completion))
        if match:
            return match.group(2), int(match.group(1))
    except Exception:
        pass
    return None, None


def extract_text(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    completion = _client().chat.completions.create(
        model=GROQ_OCR_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Đọc toàn bộ văn bản trong ảnh. Chỉ trả về văn bản.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    },
                ],
            }
        ],
    )
    return _content(completion)


def summarize(caption: str, counts: dict[str, int]) -> str:
    if not os.getenv("GROQ_API_KEY", "").strip():
        return caption
    try:
        stats = "\n".join(f"- {name}: {count}" for name, count in sorted(counts.items()))
        completion = _client().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.2,
            max_tokens=180,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Gộp dữ liệu thành 1-2 câu tiếng Việt tự nhiên. "
                        "Chỉ dùng thông tin được cung cấp và không giải thích."
                    ),
                },
                {"role": "user", "content": f"Mô tả: {caption}\nĐối tượng:\n{stats}"},
            ],
        )
        return _content(completion) or caption
    except Exception:
        return caption


def translate(text: str, target_language: str) -> str:
    if not text or target_language not in {"en", "vi"}:
        return text
    try:
        language = "English" if target_language == "en" else "Vietnamese"
        completion = _client().chat.completions.create(
            model=GROQ_MODEL,
            temperature=0.1,
            max_tokens=1024,
            messages=[
                {
                    "role": "system",
                    "content": f"Translate to {language}. Return only the translation.",
                },
                {"role": "user", "content": text},
            ],
        )
        return _content(completion) or text
    except Exception:
        return text

