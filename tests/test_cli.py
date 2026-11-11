"""The command line: `bookkeeping statement.pdf [-o out.csv]`."""

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bookkeeping import pipeline
from bookkeeping.cli import main
from bookkeeping.pdf_lines import OcrUnavailableError
from helpers import Page, chequing_header, chequing_row

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CHEQUING_PDF = EXAMPLES / "Sample Statement 1 - Maple Northern Bank chequing.pdf"


@pytest.fixture
def statement(tmp_path) -> Path:
    pdf = tmp_path / "statement.pdf"
    shutil.copy(CHEQUING_PDF, pdf)
    return pdf


def rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_runs_as_a_command(statement):
    """The real command-line entry point, in a separate process."""
    result = subprocess.run(
        [sys.executable, "-m", "bookkeeping", str(statement)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert (statement.parent / "statement.csv").exists()
    assert "statement.csv" in result.stdout


def test_default_output_is_next_to_the_pdf(statement):
    assert main([str(statement)]) == 0
    out = statement.with_suffix(".csv")
    assert rows(out)[0] == ["Date", "Description", "Withdrawals ($)", "Deposits ($)", "Balance ($)"]
    assert len(rows(out)) == 23  # header + opening + 20 transactions + closing


def test_output_flag_overrides_location_and_creates_folders(statement, tmp_path):
    out = tmp_path / "nested" / "folder" / "result.csv"
    assert main([str(statement), "-o", str(out)]) == 0
    assert out.exists()
    assert not statement.with_suffix(".csv").exists()


def test_reports_rows_written(statement, capsys):
    main([str(statement)])
    assert "22 rows" in capsys.readouterr().out


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.pdf")]) == 1
    assert "not found" in capsys.readouterr().err.lower()
    assert not (tmp_path / "nope.csv").exists()


def test_file_that_is_not_a_pdf(tmp_path, capsys):
    fake = tmp_path / "notes.pdf"
    fake.write_text("this is not a pdf")
    assert main([str(fake)]) == 1
    assert "could not read" in capsys.readouterr().err.lower()
    assert not fake.with_suffix(".csv").exists()


def test_pdf_without_a_table(statement, monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "read_lines", lambda path: (Page().add(("Dear customer,", 54)).lines, False))
    assert main([str(statement)]) == 1
    assert "no transaction table" in capsys.readouterr().err.lower()
    assert not statement.with_suffix(".csv").exists()


def test_scan_without_tesseract_gives_install_hint(statement, monkeypatch, capsys):
    def no_ocr(path):
        raise OcrUnavailableError("needs OCR, but Tesseract was not found")

    monkeypatch.setattr(pipeline, "read_lines", no_ocr)
    assert main([str(statement)]) == 1
    assert "tesseract" in capsys.readouterr().err.lower()


def test_table_that_does_not_add_up_still_writes_csv_but_warns(statement, monkeypatch, capsys):
    page = Page()
    chequing_header(page)
    chequing_row(page, "Jan 01", "Opening balance", balance="1,000.00")
    chequing_row(page, "Jan 02", "DEPOSIT", inn="100.00", balance="1,150.00")
    chequing_row(page, "Jan 03", "FEE", out="5.00", balance="1,120.00")
    chequing_row(page, "Jan 31", "Closing balance", balance="1,120.00")
    monkeypatch.setattr(pipeline, "read_lines", lambda path: (page.lines, False))

    assert main([str(statement)]) == 2
    assert "warning" in capsys.readouterr().err.lower()
    assert len(rows(statement.with_suffix(".csv"))) == 5


def test_requires_a_path(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
