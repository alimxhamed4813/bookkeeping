"""The running balance is used to verify every amount, and to repair OCR misreads."""

from datetime import date

from helpers import D, chequing_statement, parse


def test_clean_statement_reconciles_without_review():
    s = parse(
        chequing_statement(
            [
                ("Jan 02", "DEPOSIT", None, "500.00", "1,500.00"),
                ("Jan 03", "CHEQUE #101", "200.00", None, "1,300.00"),
            ],
            closing="1,300.00",
        )
    )
    assert [t.amount for t in s.transactions] == [D("500.00"), D("-200.00")]
    assert s.transactions[1].cheque_number == "101"
    assert s.transactions[0].date == date(2026, 1, 2)
    assert s.reconciles is True
    assert s.issues == []
    assert not any(t.needs_review for t in s.transactions)


def test_misread_amount_is_corrected_from_running_balance_and_flagged():
    # The real deposit was 990.00; OCR read it as 390.00. Balances on either side agree with 990.
    s = parse(
        chequing_statement(
            [
                ("Jan 02", "DEPOSIT", None, "390.00", "1,990.00"),
                ("Jan 03", "SERVICE CHARGE", "10.00", None, "1,980.00"),
            ],
            closing="1,980.00",
        )
    )
    deposit = s.transactions[0]
    assert deposit.amount == D("990.00")
    assert deposit.needs_review
    assert "390.00" in deposit.review_notes[0] and "990.00" in deposit.review_notes[0]
    assert s.reconciles is True


def test_amount_in_wrong_column_takes_direction_from_balance():
    s = parse(
        chequing_statement(
            [("Jan 02", "REFUND", "25.00", None, "1,025.00")],  # printed under withdrawals, but balance went up
            closing="1,025.00",
        )
    )
    assert s.transactions[0].amount == D("25.00")
    assert s.transactions[0].needs_review


def test_unexplainable_mismatch_is_flagged_not_hidden():
    s = parse(
        chequing_statement(
            [
                ("Jan 02", "DEPOSIT", None, "100.00", "1,150.00"),  # neither number can be trusted
                ("Jan 03", "FEE", "5.00", None, "1,120.00"),
            ],
            closing="1,120.00",
        )
    )
    assert all(t.needs_review for t in s.transactions)
    assert s.reconciles is False
    assert any("do not reconcile" in issue for issue in s.issues)


def test_missing_closing_balance_is_reported():
    s = parse(chequing_statement([("Jan 02", "DEPOSIT", None, "100.00", "1,100.00")]))
    assert s.reconciles is None
    assert any("No closing balance" in issue for issue in s.issues)
