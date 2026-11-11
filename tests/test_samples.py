"""End-to-end checks against the three sample statements in examples/."""

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bookkeeping.duplicates import mark_duplicates
from bookkeeping.statements import parse_statement

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CHEQUING = EXAMPLES / "Sample Statement 1 - Maple Northern Bank chequing.pdf"
CREDIT_CARD = EXAMPLES / "Sample Statement 2 - Lakeshore Trust business credit card.pdf"
SCANNED = EXAMPLES / "Sample Statement 3 - Prairie Community Credit Union (scanned).pdf"

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract OCR not installed")


def by_description(statement, text):
    return [t for t in statement.transactions if t.description == text]


@pytest.fixture(scope="module")
def chequing():
    return parse_statement(CHEQUING)


@pytest.fixture(scope="module")
def credit_card():
    return parse_statement(CREDIT_CARD)


@pytest.fixture(scope="module")
def scanned():
    return parse_statement(SCANNED)


class TestChequing:
    def test_header(self, chequing):
        assert chequing.institution == "Maple Northern Bank"
        assert chequing.account_type == "chequing"
        assert chequing.account_holder == "HARBOURVIEW LANDSCAPING LTD."
        assert chequing.account_number == "00000-0000-111"
        assert (chequing.period_start, chequing.period_end) == (date(2025, 12, 15), date(2026, 1, 14))
        assert chequing.ocr is False

    def test_all_rows_found_and_reconciled(self, chequing):
        assert len(chequing.transactions) == 20
        assert chequing.opening_balance == Decimal("4210.66")
        assert chequing.closing_balance == Decimal("9638.46")
        assert chequing.reconciles is True
        assert chequing.issues == []
        assert not any(t.needs_review for t in chequing.transactions)

    def test_dates_span_new_year(self, chequing):
        assert chequing.transactions[0].date == date(2025, 12, 16)
        assert chequing.transactions[-1].date == date(2026, 1, 13)

    def test_signs_and_cheques(self, chequing):
        assert by_description(chequing, "E-TRANSFER RECEIVED - M. OKAFOR")[0].amount == Decimal("1450.00")
        cheque = by_description(chequing, "CHEQUE #1189")[0]
        assert cheque.amount == Decimal("-480.00") and cheque.cheque_number == "1189"
        assert by_description(chequing, "NSF ITEM RETURNED")[0].amount == Decimal("480.00")
        assert by_description(chequing, "INTEREST")[0].amount == Decimal("1.12")


class TestCreditCard:
    def test_header(self, credit_card):
        assert credit_card.institution == "LAKESHORE TRUST"
        assert credit_card.account_type == "credit_card"
        assert credit_card.account_holder == "PINECREST BAKERY INC."
        assert credit_card.account_number == "card ending 0000"

    def test_both_pages_read_and_reconciled(self, credit_card):
        assert len(credit_card.transactions) == 18
        assert {t.page for t in credit_card.transactions} == {1, 2}
        assert credit_card.opening_balance == Decimal("3488.21")
        assert credit_card.closing_balance == Decimal("4976.35")
        assert credit_card.reconciles is True
        assert credit_card.issues == []

    def test_charges_are_money_out_and_credits_money_in(self, credit_card):
        first = credit_card.transactions[0]
        assert first.description == "FLOURWORKS SUPPLY CO"
        assert first.amount == Decimal("-842.60")
        assert (first.date, first.posted_date) == (date(2026, 9, 6), date(2026, 9, 8))
        assert first.details == "MISSISSAUGA ON"
        assert [t.amount for t in by_description(credit_card, "PAYMENT - THANK YOU")] == [
            Decimal("1500.00"),
            Decimal("2000.00"),
        ]
        assert by_description(credit_card, "RETURN - PACKAGING PLUS INC")[0].amount == Decimal("32.50")

    def test_foreign_currency_details(self, credit_card):
        sub = by_description(credit_card, "CLOUD BAKERY POS SUBSCRIPTION")[0]
        assert (sub.foreign_currency, sub.foreign_amount, sub.fx_rate) == ("USD", Decimal("49.99"), Decimal("1.371874"))
        assert sub.amount == Decimal("-68.58")
        assert not sub.needs_review  # 49.99 x 1.371874 rounds to 68.58

    def test_page_furniture_is_not_a_transaction(self, credit_card):
        text = " ".join(f"{t.description} {t.details}" for t in credit_card.transactions)
        assert "Continued" not in text and "SAMPLE" not in text and "Page" not in text


@needs_tesseract
class TestScanned:
    def test_header(self, scanned):
        assert scanned.institution == "PRAIRIE COMMUNITY CREDIT UNION"
        assert scanned.account_holder == "NORTHGATE AUTO REPAIR LTD."
        assert (scanned.period_start, scanned.period_end) == (date(2026, 8, 1), date(2026, 8, 31))
        assert scanned.ocr is True

    def test_all_rows_found_and_reconciled(self, scanned):
        assert len(scanned.transactions) == 16
        assert scanned.opening_balance == Decimal("5302.18")
        assert scanned.closing_balance == Decimal("8756.97")
        assert scanned.reconciles is True
        assert scanned.issues == []

    def test_cheques_and_amounts(self, scanned):
        cheques = {t.cheque_number: t.amount for t in scanned.transactions if t.cheque_number}
        assert cheques == {
            "2041": Decimal("-780.00"),
            "2042": Decimal("-1500.00"),
            "2043": Decimal("-265.00"),
            "2044": Decimal("-94.18"),
        }
        assert by_description(scanned, "HST REMITTANCE")[0].amount == Decimal("-1744.92")


@needs_tesseract
def test_no_duplicates_across_samples(chequing, credit_card, scanned):
    assert mark_duplicates([chequing, credit_card, scanned]) == []
