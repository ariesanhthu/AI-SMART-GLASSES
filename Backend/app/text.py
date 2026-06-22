"""Text normalization, intent parsing and response formatting."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from deep_translator import GoogleTranslator

from app.services import groq_service


INTENTS = {"describe", "count", "find", "ocr", "history"}


def normalize(text: str) -> str:
    # Unicode decomposition does not turn Vietnamese đ into ASCII d.
    lowered = (text or "").lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", without_accents)).strip()


def prettify_sentence(text: str) -> str:
    value = re.sub(r"\s+", " ", (text or "").strip())
    if not value:
        return value
    value = value[0].upper() + value[1:]
    return value if value[-1] in ".!?…" else value + "."


def prettify_target(term: Optional[str]) -> str:
    value = (term or "").strip()
    if not value:
        return value
    try:
        return GoogleTranslator(source="auto", target="vi").translate(value).strip()
    except Exception:
        return value


def extract_target(prompt: str, markers: list[str]) -> Optional[str]:
    for marker in markers:
        if marker in prompt:
            target = prompt.split(marker, 1)[1].strip()
            if target:
                return target
    return None


def extract_find_target(prompt: str) -> Optional[str]:
    if prompt.startswith("co ") and (" khong" in prompt or " ko" in prompt):
        target = prompt[3:].split(" khong", 1)[0].split(" ko", 1)[0]
        target = target.replace(" o phia truoc", " ").replace(" phia truoc", " ")
        target = target.strip()
        return target[5:].strip() if target.startswith("thay ") else target or None
    if prompt.startswith("tim "):
        return prompt[4:].strip() or None
    return None


def _keyword_intent(prompt: str) -> tuple[str, Optional[str], bool]:
    if any(word in prompt for word in ("dem", "bao nhieu", "how many", "count")):
        target = extract_target(prompt, ["dem", "bao nhieu", "how many", "count"])
        return "count", target, False
    if any(word in prompt for word in ("ocr", "doc chu", "van ban", "read text")):
        return "ocr", None, False
    if any(
        word in prompt
        for word in ("lich su", "history", "da khi nao", "vao ngay nao", "trong qua khu")
    ):
        return "history", None, False
    if any(word in prompt for word in ("tim", "o dau", "where", "find")) or (
        prompt.startswith("co ") and (" khong" in prompt or " ko" in prompt)
    ):
        target = extract_target(prompt, ["tim", "o dau", "where", "find"])
        return "find", target or extract_find_target(prompt), False
    if any(word in prompt for word in ("mo ta", "co gi", "describe", "caption", "nhan dang")):
        return "describe", None, False
    return "describe", None, True


def classify_intent(prompt: str) -> tuple[str, Optional[str], bool]:
    normalized = normalize(prompt)
    if not normalized:
        return "describe", None, True

    fallback = _keyword_intent(normalized)
    label = groq_service.classify_intent(prompt)
    if label not in INTENTS:
        return fallback
    if label == "count":
        target = extract_target(normalized, ["dem", "bao nhieu", "how many", "count"])
        return label, target, False
    if label == "find":
        target = extract_target(normalized, ["tim", "o dau", "where", "find"])
        target = target or extract_find_target(normalized)
        if not target:
            target, _ = groq_service.extract_find_target(prompt)
        return label, target, False
    return label, None, False


def format_response(text: str, language: Optional[str]) -> str:
    if not text:
        return text
    if (language or "vi").lower() != "en":
        return prettify_sentence(text)
    return prettify_sentence(groq_service.translate(text, "en"))
