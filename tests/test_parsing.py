from decimal import Decimal

import pytest

from bookkeeping.parsing import format_amount, is_date, parse_amount


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


@pytest.mark.parametrize("token", ["2026-08-01", "#214", "33", "1.371874", "CHQ#2041", "DEPOSIT", "Dec", ""])
def test_parse_amount_rejects_non_amounts(token):
    assert parse_amount(token) is None


@pytest.mark.parametrize(
    "value, text",
    [("990", "990.00"), ("1234.5", "1,234.50"), ("10859.32", "10,859.32"), ("0.99", "0.99")],
)
def test_format_amount(value, text):
    assert format_amount(Decimal(value)) == text


@pytest.mark.parametrize("text", ["Dec 16", "SEP 06", "Jan 02", "2026-08-04"])
def test_is_date(text):
    assert is_date(text)


@pytest.mark.parametrize("text", ["PINECREST", "Dec", "2026", "Opening balance", "Page 2", "Foo 12", "2026-13-01"])
def test_is_not_date(text):
    assert not is_date(text)
