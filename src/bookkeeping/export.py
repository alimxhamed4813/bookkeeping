"""Write parsed statements to CSV."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import Statement

TRANSACTION_COLUMNS = [
    "row_id",
    "source_file",
    "page",
    "institution",
    "account_type",
    "account_holder",
    "account_number",
    "date",
    "posted_date",
    "description",
    "details",
    "money_out",
    "money_in",
    "amount",
    "balance",
    "cheque_number",
    "foreign_currency",
    "foreign_amount",
    "fx_rate",
    "duplicate_of",
    "needs_review",
    "review_notes",
]

STATEMENT_COLUMNS = [
    "source_file",
    "file_sha256",
    "institution",
    "account_type",
    "account_holder",
    "account_number",
    "period_start",
    "period_end",
    "opening_balance",
    "closing_balance",
    "computed_closing_balance",
    "reconciles",
    "transaction_count",
    "rows_needing_review",
    "ocr",
    "issues",
]


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def transaction_rows(statements: list[Statement]) -> list[dict[str, str]]:
    rows = []
    for s in statements:
        for t in s.transactions:
            rows.append(
                {
                    "row_id": t.row_id,
                    "source_file": s.source_file,
                    "page": _fmt(t.page),
                    "institution": s.institution,
                    "account_type": s.account_type,
                    "account_holder": s.account_holder,
                    "account_number": s.account_number,
                    "date": t.date.isoformat(),
                    "posted_date": _fmt(t.posted_date and t.posted_date.isoformat()),
                    "description": t.description,
                    "details": t.details,
                    "money_out": _fmt(-t.amount if t.amount < 0 else None),
                    "money_in": _fmt(t.amount if t.amount > 0 else None),
                    "amount": _fmt(t.amount),
                    "balance": _fmt(t.balance),
                    "cheque_number": _fmt(t.cheque_number),
                    "foreign_currency": _fmt(t.foreign_currency),
                    "foreign_amount": _fmt(t.foreign_amount),
                    "fx_rate": _fmt(t.fx_rate),
                    "duplicate_of": _fmt(t.duplicate_of),
                    "needs_review": _fmt(t.needs_review),
                    "review_notes": " | ".join(t.review_notes),
                }
            )
    return rows


def statement_rows(statements: list[Statement]) -> list[dict[str, str]]:
    return [
        {
            "source_file": s.source_file,
            "file_sha256": s.file_sha256,
            "institution": s.institution,
            "account_type": s.account_type,
            "account_holder": s.account_holder,
            "account_number": s.account_number,
            "period_start": _fmt(s.period_start),
            "period_end": _fmt(s.period_end),
            "opening_balance": _fmt(s.opening_balance),
            "closing_balance": _fmt(s.closing_balance),
            "computed_closing_balance": _fmt(s.computed_closing_balance),
            "reconciles": _fmt(s.reconciles),
            "transaction_count": _fmt(len(s.transactions)),
            "rows_needing_review": _fmt(sum(t.needs_review for t in s.transactions)),
            "ocr": _fmt(s.ocr),
            "issues": " | ".join(s.issues),
        }
        for s in statements
    ]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
