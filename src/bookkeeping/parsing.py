"""Reading and writing amounts and dates as statements print them."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

MONTHS = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}

# Characters OCR commonly confuses with digits. Only applied to tokens that are
# otherwise shaped like an amount.
_OCR_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "S": "5", "s": "5", "l": "1", "I": "1", "B": "8"})
_AMOUNT_SHAPE = re.compile(r"^\(?-?\$?[0-9OoSslIB][0-9OoSslIB,.]*[.,][0-9OoSslIB]{2}\)?-?$")


def parse_amount(token: str) -> Decimal | None:
    """Parse '1,234.56', '$1,234.56', '(12.00)' or '12.00-' into a Decimal.

    Returns None if the token is not an amount. The last '.dd' or ',dd' is always
    taken as cents, which also repairs OCR reading '990.00' as '990,00'.
    """
    token = token.strip()
    if not _AMOUNT_SHAPE.match(token):
        return None
    negative = token.startswith(("(", "-")) or token.endswith("-")
    core = token.strip("()$-").translate(_OCR_DIGIT_FIXES)
    if len(core) < 4 or core[-3] not in ".,":
        return None
    whole = core[:-3].replace(",", "").replace(".", "")
    cents = core[-2:]
    if not (whole.isdigit() and cents.isdigit()):
        return None
    value = Decimal(f"{whole}.{cents}")
    return -value if negative else value


def format_amount(value: Decimal) -> str:
    """Format the way the statements print amounts: '1,234.50'."""
    return f"{value:,.2f}"


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_DAY = re.compile(r"^([A-Za-z]{3}) (\d{1,2})$")


def is_date(text: str) -> bool:
    """'Dec 16', 'SEP 06' or '2026-08-04'."""
    text = text.strip()
    if m := _ISO_DATE.match(text):
        try:
            date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return False
        return True
    if m := _MONTH_DAY.match(text):
        return m[1].upper() in MONTHS and 1 <= int(m[2]) <= 31
    return False
