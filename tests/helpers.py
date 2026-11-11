"""Build fake page lines so table extraction can be tested without a PDF."""

from __future__ import annotations

from bookkeeping.models import Line, Word

CHAR_WIDTH = 5.0


def words_at(text: str, x0: float, top: float) -> list[Word]:
    """Left-aligned words starting at x0, one space apart."""
    words, x = [], x0
    for token in text.split():
        words.append(Word(token, x, x + len(token) * CHAR_WIDTH, top))
        x += (len(token) + 1) * CHAR_WIDTH
    return words


def right_aligned(text: str, right: float, top: float) -> list[Word]:
    """Words ending at `right`, e.g. an amount (and 'CR') under a right-aligned header."""
    width = len(text) * CHAR_WIDTH
    return words_at(text, right - width, top)


class Page:
    """Accumulates lines top to bottom, like a printed page."""

    def __init__(self, page: int = 1, top: float = 20.0):
        self.page, self.top, self.lines = page, top, []

    def add(self, *parts, gap: float = 15.0) -> "Page":
        """parts: ("text", x0) for left-aligned text, ("text", "right", x1) for right-aligned."""
        words = []
        for part in parts:
            if len(part) == 3:
                words += right_aligned(part[0], part[2], self.top)
            else:
                words += words_at(part[0], part[1], self.top)
        self.lines.append(Line(words=words, page=self.page))
        self.top += gap
        return self


# Column positions for a chequing-style table: Date | Description | Withdrawals | Deposits | Balance
DATE_X, DESC_X, OUT_R, IN_R, BAL_R = 54, 104, 403, 479, 558


def chequing_header(page: Page) -> Page:
    return page.add(
        ("Date", DATE_X),
        ("Description", DESC_X),
        ("Withdrawals ($)", 330),
        ("Deposits ($)", 420),
        ("Balance ($)", 503),
    )


def chequing_row(page: Page, date: str, description: str, out: str = "", inn: str = "", balance: str = "", gap=15.0):
    parts = []
    if date:
        parts.append((date, DATE_X))
    parts.append((description, DESC_X))
    if out:
        parts.append((out, "right", OUT_R))
    if inn:
        parts.append((inn, "right", IN_R))
    if balance:
        parts.append((balance, "right", BAL_R))
    return page.add(*parts, gap=gap)
