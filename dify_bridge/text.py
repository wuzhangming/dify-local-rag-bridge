from __future__ import annotations

import re

MIN_CHARS = 30
TARGET_CHARS = 700
OVERLAP = 120
MAX_CHARS = 1400


def chunks_for_text(text: str, markdown: bool = False) -> list[tuple[str, str]]:
    """Small, deterministic document chunker; returns (section, body)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    section = ""
    records: list[tuple[str, str]] = []
    paragraphs: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line) if markdown else None
        if match:
            records.extend(_pack(paragraphs, section))
            paragraphs = []
            section = match.group(1)
        else:
            paragraphs.append(line)
    records.extend(_pack(paragraphs, section))
    return [(s, b) for s, b in records if len(b.strip()) >= MIN_CHARS]


def _pack(lines: list[str], section: str) -> list[tuple[str, str]]:
    paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
    result: list[tuple[str, str]] = []
    current: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHARS:
            if current:
                result.append((section, "\n\n".join(current)))
                current, size = [], 0
            result.extend((section, piece) for piece in _hard_split(paragraph))
        elif current and size + len(paragraph) > TARGET_CHARS:
            result.append((section, "\n\n".join(current)))
            current, size = [paragraph], len(paragraph)
        else:
            current.append(paragraph)
            size += len(paragraph)
    if current:
        result.append((section, "\n\n".join(current)))
    return result


def _hard_split(text: str) -> list[str]:
    step = TARGET_CHARS - OVERLAP
    return [text[i:i + TARGET_CHARS].strip() for i in range(0, len(text), step) if text[i:i + TARGET_CHARS].strip()]
