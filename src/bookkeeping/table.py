from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Line, Word
from .parsing import format_amount, is_date, parse_amount

TEXT_HEADER_WORDS = {
    "date", "trans", "posted", "posting", "description", "transaction", "activity", "details", "particulars",
}
MONEY_HEADER_WORDS = {
    "withdrawals", "withdrawal", "deposits", "deposit", "debits", "debit", "credits", "credit", "amount", "balance",
}
DESCRIPTION_HEADER_RE = re.compile(r"description|transaction|activity|details|particulars", re.I)
CREDIT_MARKERS = {"CR", "CR."}
IGNORE_RE = re.compile(r"continued on next page|^page \d+ of \d+$", re.I)

MIN_HEADER_WORDS = 3  # a header row names at least three known columns
HEADER_WORD_GAP = 8.0  # points; words closer than this form one header ("Withdrawals ($)")
MAX_MONEY_DISTANCE = 60.0  # points between an amount's right edge and its column header's right edge
LEFT_TOLERANCE = 6.0  # points a left-aligned value may start before its header (scan skew)
MAX_DETAIL_GAP = 20.0  # points; wrapped description lines sit tight under their row


class NoTableFoundError(ValueError):
    pass


@dataclass
class Column:
    name: str
    x0: float
    x1: float
    money: bool


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]] = field(default_factory=list)


def _header_token(word: Word) -> str:
    return word.text.lower().strip("():$")


def detect_header(line: Line) -> list[Column] | None:
    tokens = [_header_token(w) for w in line.words]
    known = sum(t in TEXT_HEADER_WORDS or t in MONEY_HEADER_WORDS for t in tokens)
    if known < MIN_HEADER_WORDS:
        return None
    groups: list[list[Word]] = [[line.words[0]]]
    for word in line.words[1:]:
        if word.x0 - groups[-1][-1].x1 <= HEADER_WORD_GAP:
            groups[-1].append(word)
        else:
            groups.append([word])
    return [
        Column(
            name=" ".join(w.text for w in group),
            x0=group[0].x0,
            x1=group[-1].x1,
            money=any(_header_token(w) in MONEY_HEADER_WORDS for w in group),
        )
        for group in groups
    ]


class _Layout:
    def __init__(self, columns: list[Column]):
        self.columns = columns
        self.text_cols = [i for i, c in enumerate(columns) if not c.money]
        self.money_cols = [i for i, c in enumerate(columns) if c.money]
        named = [i for i in self.text_cols if DESCRIPTION_HEADER_RE.search(columns[i].name)]
        self.description_col = named[0] if named else self.text_cols[-1]

    def money_column_for(self, word: Word) -> int | None:
        if not self.money_cols:
            return None
        best = min(self.money_cols, key=lambda i: abs(self.columns[i].x1 - word.x1))
        return best if abs(self.columns[best].x1 - word.x1) <= MAX_MONEY_DISTANCE else None

    def text_column_for(self, word: Word) -> int:
        starts_after = [i for i in self.text_cols if self.columns[i].x0 <= word.x0 + LEFT_TOLERANCE]
        return starts_after[-1] if starts_after else self.text_cols[0]

    def split(self, line: Line) -> tuple[list[str], bool]:
        """Return the line's cells (one per column) and whether any money cell is filled."""
        cells: list[list[str]] = [[] for _ in self.columns]
        last_money_col = None
        for word in line.words:
            if word.text.upper() in CREDIT_MARKERS and last_money_col is not None:
                cells[last_money_col].append("CR")
                continue
            value = parse_amount(word.text)
            col = self.money_column_for(word) if value is not None else None
            if col is not None:
                # OCR'd amounts are rewritten in the printed format ("S,302.18" -> "5,302.18").
                text = format_amount(value) if word.confidence is not None else word.text
                cells[col].append(text)
                last_money_col = col
                continue
            cells[self.text_column_for(word)].append(word.text)
            last_money_col = None
        has_money = any(cells[i] for i in self.money_cols)
        return [" ".join(c) for c in cells], has_money


def extract_table(lines: list[Line]) -> Table:
    layout: _Layout | None = None
    table: Table | None = None
    last_row: list[str] | None = None
    last_line: Line | None = None

    for line in lines:
        if columns := detect_header(line):
            layout = _Layout(columns)
            if table is None:
                table = Table(header=[c.name for c in columns])
            last_row = None  # a repeated header (next page) is not data
            continue
        if layout is None or IGNORE_RE.search(line.text):
            continue

        cells, has_money = layout.split(line)
        if has_money or is_date(cells[layout.text_cols[0]]):
            table.rows.append(cells)
            last_row, last_line = cells, line
        elif (
            last_row is not None
            and line.page == last_line.page
            and line.top - last_line.top <= MAX_DETAIL_GAP
            and line.x0 >= layout.columns[layout.description_col].x0 - LEFT_TOLERANCE
        ):
            col = layout.description_col
            last_row[col] = f"{last_row[col]} {line.text}".strip()
            last_line = line
        else:
            last_row = None

    if table is None:
        raise NoTableFoundError(
            "No transaction table found (looked for a header row such as "
            "'Date  Description  Withdrawals  Deposits  Balance')."
        )
    if not table.rows:
        raise NoTableFoundError(f"No transaction table found: the header {table.header} has no rows under it.")
    return table
