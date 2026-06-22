"""JSON-backed request history with atomic writes."""

from __future__ import annotations

import json
import threading
from datetime import datetime

from app.config import HISTORY_FILE
from app.text import normalize, prettify_target


_LOCK = threading.Lock()


def _read() -> list[dict[str, str]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def add(prompt: str) -> None:
    """Append a prompt using replace-on-write to avoid partial JSON files."""
    with _LOCK:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _read()
        data.append(
            {"datetime": datetime.now().isoformat(timespec="seconds"), "content": prompt}
        )
        temporary = HISTORY_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(HISTORY_FILE)


def query(target: str | None = None) -> str:
    entries = _read()
    if not entries:
        return "Chưa có lịch sử."

    target_normalized = normalize(target or "")
    dates: dict[str, int] = {}
    for entry in entries:
        if target_normalized and target_normalized not in normalize(entry.get("content", "")):
            continue
        date = str(entry.get("datetime", ""))[:10]
        if date:
            dates[date] = dates.get(date, 0) + 1

    if not dates:
        return "Không tìm thấy lịch sử phù hợp."
    details = ", ".join(f"{date} (×{count})" for date, count in sorted(dates.items()))
    if target_normalized:
        return f"Bạn đã nhắc về '{prettify_target(target)}' vào: {details}."
    return f"Các ngày có hoạt động: {details}."

