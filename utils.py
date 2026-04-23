"""Utility helpers for Smart Notepad Pro."""

from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime
from typing import Any, Iterable


COLOR_LABELS = {
    "Slate": "#64748b",
    "Ocean": "#0ea5e9",
    "Emerald": "#10b981",
    "Amber": "#f59e0b",
    "Rose": "#f43f5e",
    "Violet": "#8b5cf6",
    "Teal": "#14b8a6",
    "Coral": "#fb7185",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def format_dt(value: Any) -> str:
    dt = parse_dt(value)
    if not dt:
        return "Unknown"
    return dt.strftime("%b %d, %Y %I:%M %p")


def count_words(text: str | None) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))


def count_chars(text: str | None) -> int:
    return len(text or "")


def reading_time_minutes(text: str | None, words_per_minute: int = 200) -> int:
    words = count_words(text)
    if words == 0:
        return 0
    return max(1, math.ceil(words / words_per_minute))


def snippet(text: str | None, limit: int = 180) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def strip_markdown(text: str | None) -> str:
    if not text:
        return ""
    value = text
    patterns = [
        (r"```.*?```", " "),
        (r"`([^`]*)`", r"\1"),
        (r"!\[.*?\]\(.*?\)", " "),
        (r"\[(.*?)\]\(.*?\)", r"\1"),
        (r"(^|\n)#{1,6}\s*", r"\1"),
        (r"[*_~>#-]", " "),
        (r"\s+", " "),
    ]
    for pattern, replacement in patterns:
        value = re.sub(pattern, replacement, value, flags=re.S | re.M)
    return value.strip()


def safe_json_loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    tags = []
    for tag in re.split(r"[,\n;]+", raw):
        clean = tag.strip().lstrip("#")
        if clean:
            tags.append(clean)
    seen = set()
    unique = []
    for tag in tags:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            unique.append(tag)
    return unique


def normalize_title(value: str | None, fallback: str = "Untitled Note") -> str:
    title = (value or "").strip()
    return title if title else fallback


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def color_hex(label: str | None) -> str:
    return COLOR_LABELS.get(label or "Slate", COLOR_LABELS["Slate"])


def checklist_lines(content: str | None) -> list[tuple[bool, str]]:
    lines = []
    for raw in (content or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("- [x]") or lower.startswith("* [x]"):
            lines.append((True, stripped[5:].strip()))
        elif lower.startswith("- [ ]") or lower.startswith("* [ ]"):
            lines.append((False, stripped[5:].strip()))
        else:
            lines.append((False, stripped))
    return lines


def format_bytes(num_bytes: int) -> str:
    step = 1024.0
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < step:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= step
    return f"{value:.1f} PB"


def writing_goal_progress(words_today: int, goal: int) -> float:
    if goal <= 0:
        return 0.0
    return min(words_today / goal, 1.0)


def unique_non_empty(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        clean = str(item).strip()
        if not clean:
            continue
        key = clean.lower()
        if key not in seen:
            seen.add(key)
            out.append(clean)
    return out

