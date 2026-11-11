"""End to end: each sample PDF must produce exactly the CSV in tests/expected/."""

import csv
import shutil
from pathlib import Path

import pytest

from bookkeeping.cli import main
from integrity import check_card_totals, check_running_balance, check_structure

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
EXPECTED = Path(__file__).resolve().parent / "expected"

CHEQUING = "Sample Statement 1 - Maple Northern Bank chequing"
CREDIT_CARD = "Sample Statement 2 - Lakeshore Trust business credit card"
SCANNED = "Sample Statement 3 - Prairie Community Credit Union (scanned)"

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract OCR not installed")

SAMPLES = [
    pytest.param(CHEQUING, check_running_balance, id="chequing"),
    pytest.param(CREDIT_CARD, check_card_totals, id="credit-card"),
    pytest.param(SCANNED, check_running_balance, id="scanned", marks=needs_tesseract),
]


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        header, *rows = list(csv.reader(f))
    return header, rows


@pytest.fixture(scope="module")
def outputs(tmp_path_factory) -> dict[str, Path]:
    """Run the CLI once per sample, the way a user would: PDF path as the only argument."""
    workdir = tmp_path_factory.mktemp("statements")
    results = {}
    for stem in (CHEQUING, CREDIT_CARD, SCANNED):
        if stem == SCANNED and shutil.which("tesseract") is None:
            continue
        pdf = workdir / f"{stem}.pdf"
        shutil.copy(EXAMPLES / f"{stem}.pdf", pdf)
        assert main([str(pdf)]) == 0, f"{stem} should convert cleanly"
        results[stem] = workdir / f"{stem}.csv"  # default output: next to the PDF
    return results


@pytest.mark.parametrize("stem, arithmetic_check", SAMPLES)
def test_expected_csv_is_internally_consistent(stem, arithmetic_check):
    """Guards against typos in the hand-written expected files themselves."""
    header, rows = read_csv(EXPECTED / f"{stem}.csv")
    check_structure(header, rows)
    arithmetic_check(header, rows)


@pytest.mark.parametrize("stem, arithmetic_check", SAMPLES)
def test_output_header_is_the_tables_own_columns(outputs, stem, arithmetic_check):
    assert read_csv(outputs[stem])[0] == read_csv(EXPECTED / f"{stem}.csv")[0]


@pytest.mark.parametrize("stem, arithmetic_check", SAMPLES)
def test_output_matches_expected_csv_row_for_row(outputs, stem, arithmetic_check):
    _, actual = read_csv(outputs[stem])
    _, expected = read_csv(EXPECTED / f"{stem}.csv")
    for i, (got, want) in enumerate(zip(actual, expected), start=1):
        assert got == want, f"row {i} differs"
    assert len(actual) == len(expected), f"expected {len(expected)} rows, got {len(actual)}"


@pytest.mark.parametrize("stem, arithmetic_check", SAMPLES)
def test_output_passes_integrity_checks(outputs, stem, arithmetic_check):
    header, rows = read_csv(outputs[stem])
    check_structure(header, rows)
    arithmetic_check(header, rows)


def test_expected_column_layouts():
    """Spells out the three different table layouts the pipeline must handle."""
    assert read_csv(EXPECTED / f"{CHEQUING}.csv")[0] == [
        "Date", "Description", "Withdrawals ($)", "Deposits ($)", "Balance ($)",
    ]
    assert read_csv(EXPECTED / f"{CREDIT_CARD}.csv")[0] == ["TRANS", "POSTED", "ACTIVITY DESCRIPTION", "AMOUNT ($)"]
    assert read_csv(EXPECTED / f"{SCANNED}.csv")[0] == ["DATE", "TRANSACTION", "DEBIT", "CREDIT", "BALANCE"]


def test_credit_card_rows_from_both_pages(outputs):
    _, rows = read_csv(outputs[CREDIT_CARD])
    descriptions = [r[2] for r in rows]
    assert "FLOURWORKS SUPPLY CO MISSISSAUGA ON" in descriptions  # page 1
    assert "OVEN REPAIR SERVICES ETOBICOKE ON" in descriptions  # page 2
    assert descriptions.count("PAYMENT - THANK YOU") == 2


def test_output_is_deterministic(outputs, tmp_path):
    pdf = tmp_path / f"{CHEQUING}.pdf"
    shutil.copy(EXAMPLES / f"{CHEQUING}.pdf", pdf)
    assert main([str(pdf)]) == 0
    assert (tmp_path / f"{CHEQUING}.csv").read_bytes() == outputs[CHEQUING].read_bytes()
