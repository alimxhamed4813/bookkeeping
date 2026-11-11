"""Spot duplicate transactions across and within statements.

Three situations are handled differently, because they mean different things:

* The same file given twice: skipped entirely before parsing (see `cli.py`).
* The same transaction on two different statements of the same account (overlapping
  periods, or one statement downloaded twice as separate files): the later row is
  marked `duplicate_of` the earlier one so it is not imported twice.
* The same date, amount and description twice on one statement: this is often a
  genuine repeat purchase, so the row is only flagged for review.

Reversals are deliberately *not* treated as duplicates: "CHEQUE #1189 -480.00" followed
by "NSF ITEM RETURNED +480.00" are two real rows that cancel out.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .models import Statement, Transaction

CROSS_STATEMENT_DAY_WINDOW = 3  # posting dates can shift by a day or two between downloads


def normalize_description(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def mark_duplicates(statements: list[Statement]) -> list[str]:
    """Annotate duplicate rows in place and return human-readable findings."""
    findings: list[str] = []
    by_account: dict[tuple, list[tuple[Statement, Transaction]]] = defaultdict(list)
    for statement in statements:
        for txn in statement.transactions:
            by_account[statement.account_key].append((statement, txn))

    for rows in by_account.values():
        findings.extend(_cross_statement(rows))
        findings.extend(_same_statement(rows))
        findings.extend(_repeated_cheques(rows))
    return findings


def _same_row(a: Transaction, b: Transaction, day_window: int) -> bool:
    return (
        a.amount == b.amount
        and normalize_description(a.description) == normalize_description(b.description)
        and abs((a.date - b.date).days) <= day_window
    )


def _cross_statement(rows) -> list[str]:
    findings = []
    for i, (stmt_b, b) in enumerate(rows):
        for stmt_a, a in rows[:i]:
            if stmt_a is stmt_b or a.duplicate_of or not _same_row(a, b, CROSS_STATEMENT_DAY_WINDOW):
                continue
            b.duplicate_of = a.row_id
            b.review_notes.append(
                f"Duplicate of {a.row_id} from {stmt_a.source_file} (overlapping statements); "
                "do not import twice."
            )
            findings.append(
                f"{b.row_id} {b.date} {b.description} {b.amount} in {stmt_b.source_file} "
                f"duplicates {a.row_id} in {stmt_a.source_file}"
            )
            break
    return findings


def _same_statement(rows) -> list[str]:
    findings = []
    for i, (stmt_b, b) in enumerate(rows):
        for stmt_a, a in rows[:i]:
            if stmt_a is not stmt_b or not _same_row(a, b, 0):
                continue
            b.review_notes.append(
                f"Possible duplicate of {a.row_id}: same date, amount and description on this "
                "statement. Could be a genuine repeat; confirm before removing."
            )
            findings.append(
                f"{b.row_id} {b.date} {b.description} {b.amount} may duplicate {a.row_id} "
                f"(both on {stmt_b.source_file})"
            )
            break
    return findings


def _repeated_cheques(rows) -> list[str]:
    findings = []
    seen: dict[str, Transaction] = {}
    for _, txn in rows:
        if not txn.cheque_number or txn.amount >= 0 or txn.duplicate_of:
            continue
        if first := seen.get(txn.cheque_number):
            txn.review_notes.append(
                f"Cheque #{txn.cheque_number} already cleared as {first.row_id}; "
                "a cheque number should only clear once."
            )
            findings.append(f"Cheque #{txn.cheque_number} clears twice: {first.row_id} and {txn.row_id}")
        else:
            seen[txn.cheque_number] = txn
    return findings
