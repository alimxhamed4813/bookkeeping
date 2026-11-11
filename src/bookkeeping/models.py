"""Positioned text read from a PDF page."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    """One word on a page, with its horizontal extent and top edge (in PDF points)."""

    text: str
    x0: float
    x1: float
    top: float
    confidence: float | None = None  # OCR confidence 0-100; None for text-layer PDFs


@dataclass
class Line:
    """Words that sit on the same visual row of a page, left to right."""

    words: list[Word]
    page: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def x0(self) -> float:
        return self.words[0].x0
