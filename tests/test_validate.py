"""Arithmetic checks on an extracted table, and repair of OCR misreads."""

from bookkeeping.table import Table
from bookkeeping.validate import check_table

CHEQUING = ["Date", "Description", "Withdrawals ($)", "Deposits ($)", "Balance ($)"]
CARD = ["TRANS", "POSTED", "ACTIVITY DESCRIPTION", "AMOUNT ($)"]


def chequing(*rows):
    return Table(header=list(CHEQUING), rows=[list(r) for r in rows])


def test_consistent_table_reconciles_without_warnings():
    table = chequing(
        ["Jan 01", "Opening balance", "", "", "1,000.00"],
        ["Jan 02", "DEPOSIT", "", "500.00", "1,500.00"],
        ["Jan 03", "CHEQUE #101", "200.00", "", "1,300.00"],
        ["Jan 31", "Closing balance", "", "", "1,300.00"],
    )
    result = check_table(table)
    assert result.reconciles is True
    assert result.warnings == []


def test_ocr_misread_is_corrected_from_surrounding_balances():
    # Printed 990.00; OCR read 390.00. Balances before and after both say 990.00.
    table = chequing(
        ["2026-08-01", "BALANCE FORWARD", "", "", "7,781.47"],
        ["2026-08-28", "DEPOSIT", "", "390.00", "8,771.47"],
        ["2026-08-31", "SERVICE CHARGE", "14.50", "", "8,756.97"],
        ["", "CLOSING BALANCE", "", "", "8,756.97"],
    )
    result = check_table(table)
    assert table.rows[1][3] == "990.00"
    assert result.reconciles is True
    assert len(result.warnings) == 1
    assert "390.00" in result.warnings[0] and "990.00" in result.warnings[0]


def test_corrected_amount_keeps_thousands_separator():
    table = chequing(
        ["Jan 01", "Opening balance", "", "", "1,000.00"],
        ["Jan 02", "DEPOSIT", "", "7,250.00", "3,250.00"],  # should be 2,250.00
        ["Jan 31", "Closing balance", "", "", "3,250.00"],
    )
    check_table(table)
    assert table.rows[1][3] == "2,250.00"


def test_amount_in_the_wrong_column_is_moved():
    table = chequing(
        ["Jan 01", "Opening balance", "", "", "1,000.00"],
        ["Jan 02", "REFUND", "25.00", "", "1,025.00"],  # balance went up, so it's a deposit
        ["Jan 31", "Closing balance", "", "", "1,025.00"],
    )
    result = check_table(table)
    assert table.rows[1][2:] == ["", "25.00", "1,025.00"]
    assert result.reconciles is True
    assert len(result.warnings) == 1


def test_unexplainable_mismatch_is_reported_and_left_alone():
    table = chequing(
        ["Jan 01", "Opening balance", "", "", "1,000.00"],
        ["Jan 02", "DEPOSIT", "", "100.00", "1,150.00"],
        ["Jan 03", "FEE", "5.00", "", "1,120.00"],
        ["Jan 31", "Closing balance", "", "", "1,120.00"],
    )
    result = check_table(table)
    assert table.rows[1][3] == "100.00"
    assert result.reconciles is False
    assert result.warnings


def test_closing_balance_mismatch_is_reported():
    table = chequing(
        ["Jan 01", "Opening balance", "", "", "1,000.00"],
        ["Jan 02", "DEPOSIT", "", "500.00", "1,500.00"],
        ["Jan 31", "Closing balance", "", "", "1,600.00"],
    )
    result = check_table(table)
    assert result.reconciles is False
    assert any("closing" in w.lower() for w in result.warnings)


def card(*rows):
    return Table(header=list(CARD), rows=[list(r) for r in rows])


def test_card_totals_reconcile_with_credits():
    table = card(
        ["", "", "PREVIOUS STATEMENT BALANCE", "1,000.00"],
        ["SEP 06", "SEP 08", "SUPPLIES", "250.00"],
        ["SEP 09", "SEP 10", "PAYMENT - THANK YOU", "500.00 CR"],
        ["", "", "NEW BALANCE", "750.00"],
    )
    result = check_table(table)
    assert result.reconciles is True
    assert result.warnings == []


def test_card_totals_mismatch_is_reported():
    table = card(
        ["", "", "PREVIOUS STATEMENT BALANCE", "1,000.00"],
        ["SEP 06", "SEP 08", "SUPPLIES", "250.00"],
        ["", "", "NEW BALANCE", "1,300.00"],
    )
    result = check_table(table)
    assert result.reconciles is False
    assert result.warnings


def test_table_without_balances_cannot_be_checked():
    table = Table(header=["Date", "Description", "Amount"], rows=[["Jan 02", "COFFEE", "4.50"]])
    result = check_table(table)
    assert result.reconciles is None
    assert any("could not" in w.lower() for w in result.warnings)
