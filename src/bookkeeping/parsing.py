"""Small, well-tested helpers for reading amounts and dates as statements print them."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}

# Characters OCR commonly confuses with digits, only applied to tokens that are
# otherwise shaped like an amount.
_OCR_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "S": "5", "s": "5", "l": "1", "I": "1", "B": "8"})

_AMOUNT_SHAPE = re.compile(r"^\(?-?\$?[0-9OoSslIB][0-9OoSslIB,. ]*[.,][0-9OoSslIB]{2}\)?-?$")


def parse_amount(token: str) -> Decimal | None:
    """Parse '1,234.56', '$1,234.56', '(12.00)' or '12.00-' into a Decimal.

    Returns None if the token is not an amount. A trailing '.dd' or ',dd' is always
    taken as cents, which also repairs OCR reading '990.00' as '990,00'.
    """
    token = token.strip()
    if not _AMOUNT_SHAPE.match(token):
        return None
    negative = token.startswith("(") or token.startswith("-") or token.endswith("-")
    core = token.strip("()$-").translate(_OCR_DIGIT_FIXES).replace(" ", "")
    if len(core) < 4 or core[-3] not in ".,":
        return None
    whole, cents = core[:-3], core[-2:]
    whole = whole.replace(",", "").replace(".", "")
    if not whole.isdigit() and whole != "":
        return None
    if not cents.isdigit():
        return None
    value = Decimal(f"{whole or '0'}.{cents}")
    return -value if negative else value


def is_amount(token: str) -> bool:
    return parse_amount(token) is not None


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_NAME_DATE = re.compile(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?(?:\s+(\d{4}))?$")


def parse_full_date(text: str) -> date | None:
    """Parse a date that carries its own year: '2026-08-01' or 'Dec 15, 2025'."""
    text = text.strip()
    if m := _ISO_DATE.match(text):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if (m := _MONTH_NAME_DATE.match(text)) and m[3]:
        month = MONTHS.get(m[1].upper())
        if month:
            return date(int(m[3]), month, int(m[2]))
    return None


def resolve_year(month: int, day: int, start: date | None, end: date | None) -> date:
    """Pick the year for a 'Dec 16'-style date using the statement period.

    Statements that span New Year print 'Dec 16' and 'Jan 02' without a year;
    the period ('Dec 15, 2025 to Jan 14, 2026') tells us which year each belongs to.
    """
    if start is None or end is None:
        year = (end or start or date.today()).year
        return date(year, month, day)
    candidates = [date(y, month, day) for y in range(start.year - 1, end.year + 2)]
    # Closest candidate to the period (zero distance if it falls inside it).
    def distance(d: date) -> int:
        if d < start:
            return (start - d).days
        if d > end:
            return (d - end).days
        return 0

    return min(candidates, key=distance)


_PERIOD_PATTERNS = [
    # "Statement period: Dec 15, 2025 to Jan 14, 2026" / "Sep 6, 2026 - Oct 5, 2026"
    re.compile(
        r"([A-Za-z]{3,9}\.? \d{1,2}, \d{4})\s*(?:to|-|–|through)\s*([A-Za-z]{3,9}\.? \d{1,2}, \d{4})",
        re.I,
    ),
    # "Period: 2026-08-01 to 2026-08-31"
    re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:to|-|–|through)\s*(\d{4}-\d{2}-\d{2})", re.I),
]


def find_period(text: str) -> tuple[date | None, date | None]:
    for pattern in _PERIOD_PATTERNS:
        if m := pattern.search(text):
            return parse_full_date(m[1]), parse_full_date(m[2])
    return None, None
