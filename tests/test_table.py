"""Turning positioned words into table rows, using synthetic pages."""

import pytest

from bookkeeping.table import NoTableFoundError, extract_table
from helpers import BAL_R, DESC_X, Page, chequing_header, chequing_row


def simple_page() -> Page:
    page = Page()
    page.add(("Test Bank", 54)).add(("Statement period: Jan 1, 2026 to Jan 31, 2026", 300))
    chequing_header(page)
    chequing_row(page, "Jan 01", "Opening balance", balance="1,000.00")
    chequing_row(page, "Jan 02", "DEPOSIT", inn="500.00", balance="1,500.00")
    chequing_row(page, "Jan 03", "CHEQUE #101", out="200.00", balance="1,300.00")
    chequing_row(page, "Jan 31", "Closing balance", balance="1,300.00")
    return page


def test_header_words_are_grouped_into_column_names():
    table = extract_table(simple_page().lines)
    assert table.header == ["Date", "Description", "Withdrawals ($)", "Deposits ($)", "Balance ($)"]


def test_lines_above_the_header_are_not_rows():
    rows = extract_table(simple_page().lines).rows
    assert rows[0] == ["Jan 01", "Opening balance", "", "", "1,000.00"]


def test_amounts_land_in_the_column_they_sit_under():
    rows = extract_table(simple_page().lines).rows
    assert rows[1] == ["Jan 02", "DEPOSIT", "", "500.00", "1,500.00"]
    assert rows[2] == ["Jan 03", "CHEQUE #101", "200.00", "", "1,300.00"]
    assert len(rows) == 4


def test_no_header_raises():
    page = Page().add(("Just a letter", 54)).add(("Nothing tabular here 12.00", 54))
    with pytest.raises(NoTableFoundError):
        extract_table(page.lines)


def card_page() -> Page:
    page = Page()
    page.add(("TRANS", 54), ("POSTED", 104), ("ACTIVITY DESCRIPTION", 155), ("AMOUNT ($)", 508))
    page.add(("PREVIOUS STATEMENT BALANCE", 155), ("3,488.21", "right", 558))
    page.add(("SEP 06", 54), ("SEP 08", 104), ("FLOURWORKS SUPPLY CO", 155), ("842.60", "right", 558), gap=13)
    page.add(("MISSISSAUGA ON", 166), gap=15)
    page.add(("SEP 09", 54), ("SEP 10", 104), ("PAYMENT - THANK YOU", 155), ("1,500.00 CR", "right", 558))
    page.add(("SEP 10", 54), ("SEP 11", 104), ("CLOUD BAKERY POS SUBSCRIPTION", 155), ("68.58", "right", 558), gap=13)
    page.add(("USD 49.99 @ 1.371874", 166), gap=40)
    page.add(("Continued on next page", 155), gap=60)
    page.add(("SAMPLE STATEMENT - FICTIONAL BANK", 80))
    return page


def test_two_date_columns_and_wrapped_description():
    rows = extract_table(card_page().lines).rows
    assert rows[1] == ["SEP 06", "SEP 08", "FLOURWORKS SUPPLY CO MISSISSAUGA ON", "842.60"]


def test_balance_row_without_a_date_is_kept():
    rows = extract_table(card_page().lines).rows
    assert rows[0] == ["", "", "PREVIOUS STATEMENT BALANCE", "3,488.21"]


def test_credit_marker_stays_with_its_amount():
    rows = extract_table(card_page().lines).rows
    assert rows[2] == ["SEP 09", "SEP 10", "PAYMENT - THANK YOU", "1,500.00 CR"]


def test_amount_inside_a_description_is_not_moved_to_a_money_column():
    rows = extract_table(card_page().lines).rows
    assert rows[3] == ["SEP 10", "SEP 11", "CLOUD BAKERY POS SUBSCRIPTION USD 49.99 @ 1.371874", "68.58"]


def test_page_furniture_is_skipped():
    rows = extract_table(card_page().lines).rows
    assert len(rows) == 4
    assert not any("Continued" in cell or "SAMPLE" in cell for row in rows for cell in row)


def test_table_continues_onto_next_page_with_repeated_header():
    page1 = Page(page=1)
    chequing_header(page1)
    chequing_row(page1, "Jan 01", "Opening balance", balance="1,000.00")
    chequing_row(page1, "Jan 02", "DEPOSIT", inn="10.00", balance="1,010.00")
    page2 = Page(page=2)
    page2.add(("Test Bank", 54)).add(("TEST CO LTD. Statement period: Jan 1, 2026 to Jan 31, 2026", 54))
    page2.add(("Page 2 of 2", 500))
    chequing_header(page2)
    chequing_row(page2, "Jan 05", "FEE", out="5.00", balance="1,005.00")

    table = extract_table(page1.lines + page2.lines)
    assert [r[1] for r in table.rows] == ["Opening balance", "DEPOSIT", "FEE"]


def test_text_under_a_row_on_the_next_page_is_not_appended():
    page1 = Page(page=1)
    chequing_header(page1)
    chequing_row(page1, "Jan 02", "DEPOSIT", inn="10.00", balance="1,010.00")
    page2 = Page(page=2, top=20.0)
    page2.add(("SOMETHING ELSE", DESC_X))
    rows = extract_table(page1.lines + page2.lines).rows
    assert rows == [["Jan 02", "DEPOSIT", "", "10.00", "1,010.00"]]


def test_closing_balance_row_without_date():
    page = Page()
    chequing_header(page)
    chequing_row(page, "Jan 01", "BALANCE FORWARD", balance="1,000.00")
    chequing_row(page, "", "CLOSING BALANCE", balance="1,000.00")
    assert extract_table(page.lines).rows[-1] == ["", "CLOSING BALANCE", "", "", "1,000.00"]


def test_number_far_from_any_money_column_stays_in_description():
    page = Page()
    chequing_header(page)
    page.add(("Jan 02", 54), ("REFUND OF 12.00 FEE", DESC_X), ("12.00", "right", 479), ("1,012.00", "right", BAL_R))
    assert extract_table(page.lines).rows[0] == ["Jan 02", "REFUND OF 12.00 FEE", "", "12.00", "1,012.00"]
