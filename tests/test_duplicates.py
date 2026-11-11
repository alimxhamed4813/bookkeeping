from bookkeeping.duplicates import mark_duplicates

from helpers import chequing_statement, parse


def test_overlapping_statements_mark_later_copy_as_duplicate():
    january = parse(
        chequing_statement(
            [
                ("Jan 02", "DEPOSIT", None, "100.00", "1,100.00"),
                ("Jan 30", "POS FUEL STOP 33", "50.00", None, "1,050.00"),
            ],
            closing="1,050.00",
        ),
        name="jan.pdf",
        sha="a" * 64,
    )
    # A second download covering an overlapping period repeats the Jan 30 row.
    overlap = parse(
        chequing_statement(
            [("Jan 30", "POS FUEL STOP 33", "50.00", None, "1,050.00")],
            opening="1,100.00",
            closing="1,050.00",
        ),
        name="overlap.pdf",
        sha="b" * 64,
    )
    findings = mark_duplicates([january, overlap])

    assert overlap.transactions[0].duplicate_of == january.transactions[1].row_id
    assert overlap.transactions[0].needs_review
    assert january.transactions[1].duplicate_of is None
    assert len(findings) == 1


def test_same_purchase_twice_on_one_statement_is_only_flagged():
    s = parse(
        chequing_statement(
            [
                ("Jan 02", "COFFEE SHOP", "4.50", None, "995.50"),
                ("Jan 02", "COFFEE SHOP", "4.50", None, "991.00"),
            ],
            closing="991.00",
        )
    )
    mark_duplicates([s])
    first, second = s.transactions
    assert second.duplicate_of is None  # not removed: could be two real coffees
    assert "Possible duplicate" in second.review_notes[0]
    assert not first.needs_review


def test_nsf_reversal_is_not_a_duplicate():
    s = parse(
        chequing_statement(
            [
                ("Jan 08", "CHEQUE #1189", "480.00", None, "520.00"),
                ("Jan 09", "NSF ITEM RETURNED", None, "480.00", "1,000.00"),
            ],
            closing="1,000.00",
        )
    )
    assert mark_duplicates([s]) == []
    assert not any(t.needs_review for t in s.transactions)


def test_same_cheque_number_clearing_twice_is_flagged():
    s = parse(
        chequing_statement(
            [
                ("Jan 05", "CHEQUE #1001", "300.00", None, "700.00"),
                ("Jan 20", "CHEQUE #1001", "300.00", None, "400.00"),
            ],
            closing="400.00",
        )
    )
    findings = mark_duplicates([s])
    assert any("Cheque #1001" in f for f in findings)
    assert s.transactions[1].needs_review


def test_different_amounts_at_same_vendor_are_not_duplicates():
    s = parse(
        chequing_statement(
            [
                ("Jan 05", "FLOURWORKS SUPPLY CO", "842.60", None, "157.40"),
                ("Jan 06", "FLOURWORKS SUPPLY CO", "98.15", None, "59.25"),
            ],
            closing="59.25",
        )
    )
    assert mark_duplicates([s]) == []
