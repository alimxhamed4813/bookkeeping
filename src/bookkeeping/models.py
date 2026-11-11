"""Data shapes shared by the extractor, the duplicate checker and the CSV export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class Word:
    """One word on a page, with its horizontal position (in page points)."""

    text: str
    x0: float
    x1: float
    top: float
    confidence: float | None = None  # OCR confidence 0-100; None for text-layer PDFs

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2


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


@dataclass
class Transaction:
    date: date
    description: str
    amount: Decimal  # signed: negative = money out of the business, positive = money in
    page: int
    posted_date: date | None = None
    details: str = ""  # continuation lines printed under the description
    balance: Decimal | None = None  # running balance printed on the statement, if any
    cheque_number: str | None = None
    foreign_currency: str | None = None
    foreign_amount: Decimal | None = None
    fx_rate: Decimal | None = None
    amount_confidence: float | None = None  # OCR confidence for the amount, if it was OCR'd
    review_notes: list[str] = field(default_factory=list)
    row_id: str = ""
    duplicate_of: str | None = None

    @property
    def needs_review(self) -> bool:
        return bool(self.review_notes)


@dataclass
class Statement:
    source_file: str
    file_sha256: str
    institution: str
    account_type: str  # "chequing", "credit_card", or "unknown"
    account_holder: str
    account_number: str
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    ocr: bool
    transactions: list[Transaction] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)  # statement-level problems

    @property
    def account_key(self) -> tuple[str, str, str]:
        """Identifies the account, so rows from overlapping statements can be compared."""
        return (self.institution.upper(), self.account_holder.upper(), self.account_number)

    @property
    def computed_closing_balance(self) -> Decimal | None:
        if self.opening_balance is None:
            return None
        total = sum((t.amount for t in self.transactions), Decimal("0"))
        if self.account_type == "credit_card":
            # Card balances are amounts owed: spending (negative amount) increases them.
            return self.opening_balance - total
        return self.opening_balance + total

    @property
    def reconciles(self) -> bool | None:
        computed = self.computed_closing_balance
        if computed is None or self.closing_balance is None:
            return None
        return computed == self.closing_balance
