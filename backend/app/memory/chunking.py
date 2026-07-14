"""Troceado de texto para RAG: por párrafos/oraciones, con solapamiento."""

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, *, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Unidades: oraciones (respetando saltos de párrafo como separadores fuertes)
    units: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if paragraph:
            units.extend(s for s in _SENTENCE_SPLIT.split(paragraph) if s.strip())

    chunks: list[str] = []
    current = ""
    for unit in units:
        # Unidad más larga que max_chars: cortar por palabras
        while len(unit) > max_chars:
            head, unit = _split_by_words(unit, max_chars)
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap > 0 else ""
            # Arranca el siguiente chunk con el solape (sin partir palabras)
            tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
            current = f"{tail} {unit}".strip()
    if current:
        chunks.append(current)
    return chunks


def _split_by_words(text: str, max_chars: int) -> tuple[str, str]:
    cut = text.rfind(" ", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    return text[:cut].strip(), text[cut:].strip()
