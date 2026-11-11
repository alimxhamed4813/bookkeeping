from datetime import date
from decimal import Decimal

import pytest

from bookkeeping.parsing import find_period, parse_amount, resolve_year


@pytest.mark.parametrize(
    "token, expected",
    [
        ("1,234.56", "1234.56"),
        ("$12.00", "12.00"),
        ("0.99", "0.99"),
        ("10,859.32", "10859.32"),
        ("(48.00)", "-48.00"),
        ("48.00-", "-48.00"),
        ("390,00", "390.00"),  # OCR read the decimal point as a comma
        ("S,302.18", "5302.18"),  # OCR read 5 as S
        ("1,5OO.00", "1500.00"),  # OCR read 0 as O
    ],
)
def test_parse_amount(token, expected):
    assert parse_amount(token) == Decimal(expected)


@pytest.mark.parametrize("token", ["2026-08-01", "#214", "33", "1.371874", "CHQ#2041", "DEPOSIT", "Dec"])
def test_parse_amount_rejects_non_amounts(token):
    assert parse_amount(token) is None


def test_resolve_year_across_new_year():
    start, end = date(2025, 12, 15), date(2026, 1, 14)
    assert resolve_year(12, 16, start, end) == date(2025, 12, 16)
    assert resolve_year(1, 2, start, end) == date(2026, 1, 2)


def test_resolve_year_for_trailing_posting_date():
    # A transaction dated just before the period starts still belongs to that year.
    assert resolve_year(9, 4, date(2026, 9, 6), date(2026, 10, 5)) == date(2026, 9, 4)


@pytest.mark.parametrize(
    "text, start, end",
    [
        ("Statement period: Dec 15, 2025 to Jan 14, 2026", date(2025, 12, 15), date(2026, 1, 14)),
        ("Statement period: Sep 6, 2026 - Oct 5, 2026", date(2026, 9, 6), date(2026, 10, 5)),
        ("Period: 2026-08-01 to 2026-08-31", date(2026, 8, 1), date(2026, 8, 31)),
    ],
)
def test_find_period(text, start, end):
    assert find_period(text) == (start, end)
