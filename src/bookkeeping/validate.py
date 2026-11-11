from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .parsing import format_amount, is_date, parse_amount
from .table import DESCRIPTION_HEADER_RE, Table


@dataclass
class CheckResult:
    reconciles: bool | None  # None: the table has no balances to check against
    warnings: list[str] = field(default_factory=list)


def _value(cell: str) -> Decimal | None:
    cell = cell.strip()
    if not cell:
        return None
    return parse_amount(cell.removesuffix("CR").strip())


def _find(header: list[str], *keywords: str) -> int | None:
    for i, name in enumerate(header):
        if any(k in name.lower() for k in keywords):
            return i
    return None


def check_table(table: Table) -> CheckResult:
    out_col = _find(table.header, "withdraw", "debit")
    in_col = _find(table.header, "deposit", "credit")
    balance_col = _find(table.header, "balance")
    amount_col = _find(table.header, "amount")
    if None not in (out_col, in_col, balance_col):
        return _RunningBalance(table, out_col, in_col, balance_col).check()
    if amount_col is not None:
        return _check_amount_column(table, amount_col)
    return CheckResult(None, [f"Could not check totals: no balance or amount columns in {table.header}."])


def _label(table: Table, index: int) -> str:
    row = table.rows[index]
    desc_col = next((i for i, n in enumerate(table.header) if DESCRIPTION_HEADER_RE.search(n)), 1)
    return f"row {index + 1} ({' '.join(filter(None, [row[0], row[desc_col]]))})"


class _RunningBalance:
    def __init__(self, table: Table, out_col: int, in_col: int, balance_col: int):
        self.table, self.out_col, self.in_col, self.balance_col = table, out_col, in_col, balance_col
        self.warnings: list[str] = []

    def change(self, row) -> Decimal | None:
        """Money in minus money out for the row, or None for a balance-only row."""
        out, inn = _value(row[self.out_col]), _value(row[self.in_col])
        if out is None and inn is None:
            return None
        return (inn or Decimal(0)) - (out or Decimal(0))

    def next_row_confirms(self, index: int, balance: Decimal) -> bool:
        """Does the next row with a printed balance agree with `balance`?"""
        for row in self.table.rows[index + 1 :]:
            next_balance = _value(row[self.balance_col])
            if next_balance is not None:
                return next_balance - balance == (self.change(row) or Decimal(0))
        return False

    def set_amount(self, row, amount: Decimal) -> None:
        row[self.out_col] = format_amount(-amount) if amount < 0 else ""
        row[self.in_col] = format_amount(amount) if amount > 0 else ""

    def check(self) -> CheckResult:
        rows = self.table.rows
        opening = _value(rows[0][self.balance_col])
        if opening is None or self.change(rows[0]) is not None:
            return CheckResult(None, ["Could not check totals: the first row is not an opening balance."])

        reconciles = True
        balance, balance_trusted = opening, True
        for i in range(1, len(rows)):
            row = rows[i]
            printed = _value(row[self.balance_col])
            change = self.change(row)

            if change is None:  # balance-only row: closing balance, or a carried-forward balance
                if printed is not None and printed != balance:
                    kind = "Closing balance" if i == len(rows) - 1 else "Balance"
                    self.warnings.append(
                        f"{kind} on {_label(self.table, i)} is {row[self.balance_col]}, but the rows above "
                        f"add up to {format_amount(balance)}."
                    )
                    reconciles = False
                    balance = printed
                continue

            if printed is None:  # no balance printed on this row; carry the running total
                balance += change
                continue

            implied = printed - balance
            if implied == change:
                balance_trusted = True
            elif implied == -change:
                self.set_amount(row, implied)
                self.warnings.append(
                    f"{_label(self.table, i)}: the amount was in the wrong column for the running balance; moved it."
                )
                balance_trusted = True
            elif balance_trusted and implied != 0 and self.next_row_confirms(i, printed):
                was = row[self.out_col] or row[self.in_col]
                self.set_amount(row, implied)
                self.warnings.append(
                    f"{_label(self.table, i)}: amount read as {was}, but the balances before and after it "
                    f"show {format_amount(abs(implied))}. Corrected it; please check this row against the PDF."
                )
                balance_trusted = True
            else:
                self.warnings.append(
                    f"{_label(self.table, i)}: {format_amount(balance)} {'+' if change >= 0 else '-'} "
                    f"{format_amount(abs(change))} does not equal the printed balance {row[self.balance_col]}."
                )
                reconciles = False
                balance_trusted = False
            balance = printed

        if self.change(rows[-1]) is not None:
            self.warnings.append("Could not confirm totals: the last row is not a closing balance.")
            return CheckResult(None if reconciles else False, self.warnings)
        return CheckResult(reconciles, self.warnings)


def _check_amount_column(table: Table, amount_col: int) -> CheckResult:
    rows = table.rows
    first, last = rows[0], rows[-1]
    if len(rows) < 2 or is_date(first[0]) or is_date(last[0]):
        return CheckResult(None, ["Could not check totals: no previous/new balance rows around the transactions."])

    warnings = []
    total = _value(first[amount_col])
    for i, row in enumerate(rows[1:-1], start=1):
        value = _value(row[amount_col])
        if value is None:
            warnings.append(f"{_label(table, i)} has no amount.")
            continue
        total += -value if row[amount_col].endswith("CR") else value
    new_balance = _value(last[amount_col])
    if new_balance != total:
        warnings.append(
            f"New balance is {last[amount_col]}, but the previous balance plus the rows above "
            f"comes to {format_amount(total)}."
        )
        return CheckResult(False, warnings)
    return CheckResult(not warnings, warnings)
