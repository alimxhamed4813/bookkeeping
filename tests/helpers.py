"""Build fake statement lines so parser logic can be tested without a PDF."""

from __future__ import annotations

from decimal import Decimal

from bookkeeping.models import Line, Word
from bookkeeping.statements import parse_lines

CHAR_WIDTH = 5.0
# Right edges of the money columns, matching the header below.
OUT_RIGHT, IN_RIGHT, BALANCE_RIGHT = 403.0, 479.0, 558.0


def words_at(text: str, x0: float, top: float) -> list[Word]:
    words, x = [], x0
    for token in text.split():
        words.append(Word(token, x, x + len(token) * CHAR_WIDTH, top))
        x += (len(token) + 1) * CHAR_WIDTH
    return words


def right_aligned(text: str, right: float, top: float) -> Word:
    return Word(text, right - len(text) * CHAR_WIDTH, right, top)


def chequing_statement(rows, opening="1,000.00", closing=None, page=1):
    """rows: (date, description, withdrawal, deposit, balance); amounts as printed strings or None."""
    top = 20.0
    lines = []

    def add(words):
        nonlocal top
        lines.append(Line(words=words, page=page))
        top += 15

    add(words_at("Test Bank", 54, top))
    add(words_at("Business Chequing Account Statement", 54, top))
    add(words_at("TEST CO LTD.", 54, top) + words_at("Account: 123-456", 454, top))
    add(words_at("Statement period: Jan 1, 2026 to Jan 31, 2026", 366, top))
    add(
        words_at("Date", 54, top)
        + words_at("Description", 104, top)
        + [Word("Withdrawals", 337, 390, top), Word("($)", 392, OUT_RIGHT, top)]
        + [Word("Deposits", 427, 465, top), Word("($)", 468, IN_RIGHT, top)]
        + [Word("Balance", 510, 544, top), Word("($)", 547, BALANCE_RIGHT, top)]
    )
    add(words_at("Jan 01 Opening balance", 54, top) + [right_aligned(opening, BALANCE_RIGHT, top)])
    for date, description, out, inn, balance in rows:
        words = words_at(date, 54, top) + words_at(description, 104, top)
        if out:
            words.append(right_aligned(out, OUT_RIGHT, top))
        if inn:
            words.append(right_aligned(inn, IN_RIGHT, top))
        if balance:
            words.append(right_aligned(balance, BALANCE_RIGHT, top))
        add(words)
    if closing:
        add(words_at("Jan 31 Closing balance", 54, top) + [right_aligned(closing, BALANCE_RIGHT, top)])
    return lines


def parse(lines, name="test.pdf", sha="0" * 64):
    return parse_lines(lines, source_file=name, file_sha256=sha)


def D(x) -> Decimal:
    return Decimal(x)
