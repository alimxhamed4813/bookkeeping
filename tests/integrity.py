"""Independent arithmetic checks on a statement CSV (header + rows of strings).

Deliberately does not import the `bookkeeping` package, so it can be used as an
oracle: it checks the hand-written expected CSVs as well as the pipeline's output.
"""

from __future__ import annotations

import re
from decimal import Decimal

DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}|[A-Za-z]{3} \d{2})$")


def money(cell: str) -> tuple[Decimal, bool] | None:
    """'1,500.00 CR' -> (Decimal('1500.00'), True); '' -> None."""
    cell = cell.strip()
    if not cell:
        return None
    is_credit = cell.endswith(" CR")
    number = cell.removesuffix(" CR")
    assert re.fullmatch(r"\d{1,3}(,\d{3})*\.\d{2}", number), f"badly formatted amount: {cell!r}"
    return Decimal(number.replace(",", "")), is_credit


def find_column(header: list[str], *keywords: str) -> int | None:
    for i, name in enumerate(header):
        if any(k in name.lower() for k in keywords):
            return i
    return None


def check_running_balance(header: list[str], rows: list[list[str]]) -> None:
    """Opening balance, then each row: previous - out + in == printed balance, then closing."""
    out_col = find_column(header, "withdraw", "debit")
    in_col = find_column(header, "deposit", "credit")
    bal_col = find_column(header, "balance")
    assert None not in (out_col, in_col, bal_col), f"not a running-balance table: {header}"

    opening, *body, closing = rows
    assert money(opening[out_col]) is None and money(opening[in_col]) is None
    balance = money(opening[bal_col])[0]
    for row in body:
        out_amt, in_amt = money(row[out_col]), money(row[in_col])
        assert (out_amt is None) != (in_amt is None), f"row needs exactly one amount: {row}"
        balance = balance - (out_amt[0] if out_amt else 0) + (in_amt[0] if in_amt else 0)
        assert money(row[bal_col])[0] == balance, f"running balance broken at {row}"
    assert money(closing[out_col]) is None and money(closing[in_col]) is None
    assert money(closing[bal_col])[0] == balance, "closing balance does not match the rows"


def check_card_totals(header: list[str], rows: list[list[str]]) -> None:
    """Previous balance + charges - credits (CR) == new balance."""
    amount_col = find_column(header, "amount")
    assert amount_col is not None
    previous, *body, new = rows
    total = money(previous[amount_col])[0]
    for row in body:
        value, is_credit = money(row[amount_col])
        total += -value if is_credit else value
    assert money(new[amount_col])[0] == total, "new balance does not match the rows"


def check_structure(header: list[str], rows: list[list[str]]) -> None:
    """Shape checks that apply to every statement CSV."""
    assert rows, "no rows"
    assert len(set(header)) == len(header), "duplicate column names"
    date_cols = [i for i, name in enumerate(header) if name.lower() in {"date", "trans", "posted"}]
    for row in rows:
        assert len(row) == len(header), f"row has {len(row)} cells, header has {len(header)}: {row}"
        assert row != header, "table header repeated as a data row"
        for i in date_cols:
            assert row[i] == "" or DATE_RE.match(row[i]), f"bad date {row[i]!r} in {row}"
        joined = " ".join(row).lower()
        for furniture in ("continued on next page", "page 1 of", "page 2 of", "sample statement"):
            assert furniture not in joined, f"page furniture leaked into a row: {row}"
