"""Parse bank and credit card statements into transactions.

The parser is layout-driven rather than bank-specific:

1. Find the table header ("Date  Description  Withdrawals  Deposits  Balance",
   "TRANS  POSTED  ACTIVITY DESCRIPTION  AMOUNT", ...) and note where each money
   column sits on the page.
2. Every following line that starts with a date is a transaction. Amounts at the
   right of the line are assigned to the nearest column, which tells us whether
   they are money out, money in, a single signed amount, or the running balance.
3. Indented lines under a transaction with no date or amount (city, FX details,
   "AUTO-PAY") are kept as that transaction's details.
4. Opening/closing balance lines are captured, and the running balance on each
   row is used to verify (and, for OCR misreads, correct) each amount.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .models import Line, Statement, Transaction, Word
from .parsing import MONTHS, find_period, parse_amount, parse_full_date, resolve_year
from .pdf_lines import read_lines

# Header words for money columns, and what a number in that column means.
MONEY_HEADERS = {
    "withdrawals": "out",
    "withdrawal": "out",
    "debits": "out",
    "debit": "out",
    "deposits": "in",
    "deposit": "in",
    "credits": "in",
    "credit": "in",
    "amount": "amount",
    "balance": "balance",
}
DATE_HEADERS = {"date", "trans", "posted", "posting"}
DESCRIPTION_HEADERS = {"description", "transaction", "activity", "details", "particulars"}

OPENING_RE = re.compile(r"opening balance|balance forward|previous (statement )?balance|brought forward", re.I)
CLOSING_RE = re.compile(r"closing balance|new balance|ending balance", re.I)
IGNORE_RE = re.compile(r"continued on next page|^page \d+ of \d+$|^sample statement", re.I)
CHEQUE_RE = re.compile(r"\b(?:CHEQUE|CHQ|CHECK|CHK)\s*#?\s*(\d{3,})", re.I)
FX_RE = re.compile(r"\b([A-Z]{3})\s+([\d,]+\.\d{2})\s*@\s*(\d+(?:\.\d+)?)")
HOLDER_RE = re.compile(r"^(.*?\b(?:LTD|LIMITED|INC|CORP|CORPORATION|LLC|LLP|CO)\b\.?)(?:\s|$)", re.I)
ACCOUNT_RE = re.compile(r"\bAccount(?:\s+(?:number|no\.?|#))?\s*:\s*([0-9][0-9X*\-]{2,})", re.I)
CARD_RE = re.compile(r"\bcard ending\s+(\d{4})", re.I)

MAX_COLUMN_DISTANCE = 60.0  # points; a number farther than this from every column is not an amount
MAX_DETAIL_GAP = 20.0  # points; detail lines sit tight under their transaction
LOW_OCR_CONFIDENCE = 60.0


@dataclass
class Column:
    role: str  # "out", "in", "amount" or "balance"
    right: float  # amounts are right-aligned, so the header's right edge is the anchor


@dataclass
class Layout:
    columns: list[Column]
    description_x0: float
    has_posted_date: bool

    def column_for(self, word: Word) -> Column | None:
        best = min(self.columns, key=lambda c: abs(c.right - word.x1), default=None)
        if best is None or abs(best.right - word.x1) > MAX_COLUMN_DISTANCE:
            return None
        return best


def parse_statement(path: Path) -> Statement:
    path = Path(path)
    lines, used_ocr = read_lines(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return parse_lines(lines, source_file=path.name, file_sha256=sha, ocr=used_ocr)


def parse_lines(lines: list[Line], source_file: str, file_sha256: str, ocr: bool = False) -> Statement:
    """Parse already-extracted lines. Split out from `parse_statement` for testing."""
    sha = file_sha256
    statement = _read_header_info(source_file, sha, lines, ocr)
    _read_transactions(statement, lines)
    _check_running_balances(statement)
    _check_totals(statement)
    for i, txn in enumerate(statement.transactions, start=1):
        txn.row_id = f"{sha[:8]}-{i:03d}"
    return statement


# --------------------------------------------------------------------------- header


def _read_header_info(source_file: str, sha: str, lines: list[Line], used_ocr: bool) -> Statement:
    first_page = [ln for ln in lines if ln.page == 1]
    text = "\n".join(ln.text for ln in first_page)
    period_start, period_end = find_period(text)

    lowered = text.lower()
    if re.search(r"credit card|card statement|visa|mastercard|amex", lowered):
        account_type = "credit_card"
    elif re.search(r"chequing|checking", lowered):
        account_type = "chequing"
    elif "savings" in lowered:
        account_type = "savings"
    else:
        account_type = "unknown"

    holder = ""
    for ln in first_page:
        if m := HOLDER_RE.match(ln.text):
            holder = m[1].strip()
            break

    if m := ACCOUNT_RE.search(text):
        account_number = m[1]
    elif m := CARD_RE.search(text):
        account_number = f"card ending {m[1]}"
    else:
        account_number = ""

    return Statement(
        source_file=source_file,
        file_sha256=sha,
        institution=first_page[0].text if first_page else "",
        account_type=account_type,
        account_holder=holder,
        account_number=account_number,
        period_start=period_start,
        period_end=period_end,
        opening_balance=None,
        closing_balance=None,
        ocr=used_ocr,
    )


def _detect_layout(line: Line) -> Layout | None:
    lowered = [w.text.lower().strip("():$") for w in line.words]
    if not any(t in DATE_HEADERS for t in lowered):
        return None
    columns: list[Column] = []
    description_x0 = None
    for i, (word, token) in enumerate(zip(line.words, lowered)):
        if token in MONEY_HEADERS:
            right = word.x1
            # Include a trailing "($)" that belongs to this header cell.
            if i + 1 < len(line.words) and line.words[i + 1].text in {"($)", "$", "(CAD)"}:
                right = line.words[i + 1].x1
            columns.append(Column(role=MONEY_HEADERS[token], right=right))
        elif token in DESCRIPTION_HEADERS and description_x0 is None:
            description_x0 = word.x0
    if not columns:
        return None
    return Layout(
        columns=columns,
        description_x0=description_x0 if description_x0 is not None else line.words[1].x0,
        has_posted_date="posted" in lowered or "posting" in lowered,
    )


# --------------------------------------------------------------------------- rows


def _take_date(words: list[Word], statement: Statement):
    """If `words` start with a date, return (date, number_of_words_used)."""
    if not words:
        return None, 0
    if (d := parse_full_date(words[0].text)) is not None:
        return d, 1
    if len(words) >= 2:
        month = MONTHS.get(words[0].text[:3].upper())
        day = words[1].text.rstrip(",")
        if month and day.isdigit() and 1 <= int(day) <= 31 and len(words[0].text) <= 9:
            return resolve_year(month, int(day), statement.period_start, statement.period_end), 2
    return None, 0


def _split_amounts(words: list[Word], layout: Layout):
    """Peel amount tokens (and 'CR' markers) off the right end of a line.

    Returns (remaining_words, [(Column, Decimal, Word, is_credit_marker)]).
    """
    found = []
    words = list(words)
    credit_marker = False
    while words:
        last = words[-1]
        if last.text.upper() in {"CR", "CR.", "-CR"}:
            credit_marker = True
            words.pop()
            continue
        value = parse_amount(last.text)
        column = layout.column_for(last) if value is not None else None
        if value is None or column is None:
            break
        found.append((column, value, last, credit_marker))
        credit_marker = False
        words.pop()
    found.reverse()
    return words, found


def _read_transactions(statement: Statement, lines: list[Line]) -> None:
    layout: Layout | None = None
    current: Transaction | None = None
    last_line: Line | None = None

    for line in lines:
        if new_layout := _detect_layout(line):
            layout, current = new_layout, None
            continue
        if layout is None or IGNORE_RE.search(line.text):
            continue

        first_date, used = _take_date(line.words, statement)
        rest = line.words[used:]
        posted = None
        if first_date is not None and layout.has_posted_date:
            posted, used2 = _take_date(rest, statement)
            rest = rest[used2:]

        description_words, amounts = _split_amounts(rest, layout)
        description = " ".join(w.text for w in description_words)

        # Opening / closing balance lines.
        if amounts and (OPENING_RE.search(description) or CLOSING_RE.search(description)):
            value = amounts[-1][1]
            if OPENING_RE.search(description):
                statement.opening_balance = value
            else:
                statement.closing_balance = value
            current = None
            continue

        if first_date is not None and amounts:
            current = _build_transaction(statement, line, first_date, posted, description_words, amounts)
            statement.transactions.append(current)
            last_line = line
            continue

        # Detail line under the previous transaction (city, FX info, "AUTO-PAY").
        if (
            current is not None
            and last_line is not None
            and not amounts
            and line.page == last_line.page
            and line.top - last_line.top <= MAX_DETAIL_GAP
            and line.x0 >= layout.description_x0 - 2
        ):
            current.details = f"{current.details} {line.text}".strip()
            _apply_fx(current)
            last_line = line
            continue

        current = None
        if amounts or first_date is not None:
            statement.issues.append(
                f"Page {line.page}: could not read this line as a transaction: {line.text!r}"
            )


def _build_transaction(statement, line, txn_date, posted, description_words, amounts) -> Transaction:
    description = " ".join(w.text for w in description_words)
    txn = Transaction(date=txn_date, posted_date=posted, description=description, amount=Decimal("0"), page=line.page)
    money = [a for a in amounts if a[0].role != "balance"]
    balances = [a for a in amounts if a[0].role == "balance"]
    if balances:
        txn.balance = balances[-1][1]

    if len(money) != 1:
        txn.review_notes.append(f"Expected one amount on this row, found {len(money)}.")
    if money:
        column, value, word, credit_marker = money[0]
        if column.role == "out":
            txn.amount = -abs(value)
        elif column.role == "in":
            txn.amount = abs(value)
        elif statement.account_type == "credit_card":
            # Card statements list charges as positive and credits with "CR".
            txn.amount = abs(value) if (credit_marker or value < 0) else -abs(value)
        else:
            txn.amount = value
        txn.amount_confidence = word.confidence

    if any(w.confidence is not None and w.confidence < LOW_OCR_CONFIDENCE for w in description_words):
        txn.review_notes.append("OCR was unsure about part of the description; check the wording.")

    if m := CHEQUE_RE.search(description):
        txn.cheque_number = m[1]
    return txn


def _apply_fx(txn: Transaction) -> None:
    m = FX_RE.search(txn.details)
    if not m:
        return
    txn.foreign_currency = m[1]
    txn.foreign_amount = Decimal(m[2].replace(",", ""))
    txn.fx_rate = Decimal(m[3])
    converted = (txn.foreign_amount * txn.fx_rate).quantize(Decimal("0.01"))
    if converted != abs(txn.amount):
        txn.review_notes.append(
            f"{txn.foreign_currency} {txn.foreign_amount} x {txn.fx_rate} = {converted}, "
            f"but the statement charged {abs(txn.amount)}."
        )


# --------------------------------------------------------------------------- checks


def _check_running_balances(statement: Statement) -> None:
    """Use each row's printed running balance to verify the amount read for it."""
    txns = statement.transactions
    previous = statement.opening_balance
    for i, txn in enumerate(txns):
        if txn.balance is None or previous is None:
            # Nothing to verify the amount against, so a shaky OCR read needs a human.
            if txn.amount_confidence is not None and txn.amount_confidence < LOW_OCR_CONFIDENCE:
                txn.review_notes.append(f"OCR confidence on the amount was only {txn.amount_confidence:.0f}%.")
            previous = None if previous is None else previous + txn.amount
            continue

        implied = txn.balance - previous
        if implied != txn.amount:
            next_amount = txns[i + 1].amount if i + 1 < len(txns) else Decimal("0")
            next_balance = txns[i + 1].balance if i + 1 < len(txns) else statement.closing_balance
            balance_is_trustworthy = next_balance is not None and next_balance - txn.balance == next_amount
            if implied == -txn.amount:
                txn.review_notes.append(
                    f"Amount was in the wrong column for the running balance; recorded as {implied}."
                )
                txn.amount = implied
            elif balance_is_trustworthy:
                txn.review_notes.append(
                    f"Amount read as {abs(txn.amount)} but the running balance implies {abs(implied)}; "
                    f"used {abs(implied)}. Please confirm against the statement."
                )
                txn.amount = implied
            else:
                txn.review_notes.append(
                    f"Running balance does not add up: {previous} + ({txn.amount}) != {txn.balance}."
                )
        previous = txn.balance


def _check_totals(statement: Statement) -> None:
    if statement.opening_balance is None:
        statement.issues.append("No opening balance found; totals could not be checked.")
    if statement.closing_balance is None:
        statement.issues.append("No closing balance found; totals could not be checked.")
    if statement.reconciles is False:
        statement.issues.append(
            f"Transactions do not reconcile: opening {statement.opening_balance} plus activity gives "
            f"{statement.computed_closing_balance}, but the statement closes at {statement.closing_balance}."
        )
    if not statement.transactions:
        statement.issues.append("No transactions were found.")
