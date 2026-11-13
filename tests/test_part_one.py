"""Part 1: run capture.py on the sample cheques and receipts and compare with tests/expected_outputs/."""

import csv
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "capture.py"
EXPECTED = Path(__file__).resolve().parent / "expected_outputs"
CHEQUES = ROOT / "part_one_examples" / "part_one_cheques"
RECEIPTS = ROOT / "part_one_examples" / "part_one_reciepts"


def read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def run_capture(file_type: str, location: Path, output_dir: Path) -> Path:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), file_type, str(location), "-o", str(output_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 3:  # the script's "a required program is missing" exit code
        pytest.skip(result.stderr.strip())
    assert result.returncode == 0, result.stderr
    return output_dir


@pytest.fixture(scope="module")
def cheque_output(tmp_path_factory) -> Path:
    return run_capture("cheque", CHEQUES, tmp_path_factory.mktemp("cheques"))


@pytest.fixture(scope="module")
def receipt_output(tmp_path_factory) -> Path:
    return run_capture("receipt", RECEIPTS, tmp_path_factory.mktemp("receipts"))


def assert_same_csv(actual: Path, expected: Path) -> None:
    got, want = read_csv(actual), read_csv(expected)
    assert got[0] == want[0], "column headers differ"
    for row_got, row_want in zip(got[1:], want[1:]):
        assert row_got == row_want
    assert len(got) == len(want), f"expected {len(want) - 1} rows, got {len(got) - 1}"


# Handwriting the local model (qwen2.5vl:7b) is known to misread. The expected CSV holds what
# the cheque actually says, so these rows are expected to fail. If one starts passing (a better
# model, say), pytest reports it so the entry can be removed.
KNOWN_MISREADS = {
    "1003": "memo 'Supplies Invoice 4471' is read as 'Supplies hvoie 4471'",
    "1007": "payee 'Ridgeway Printing Inc' is read as 'Ridgeway Painting'",
    "1008": "memo 'PPE Stock' is read as 'PDE Stack'",
}
EXPECTED_CHEQUES = read_csv(EXPECTED / "cheques.csv")


def test_cheque_columns(cheque_output):
    assert read_csv(cheque_output / "cheques.csv")[0] == EXPECTED_CHEQUES[0]
    assert len(read_csv(cheque_output / "cheques.csv")) == len(EXPECTED_CHEQUES)


@pytest.mark.parametrize(
    "expected_row",
    [
        pytest.param(
            row,
            id=f"cheque-{row[0]}",
            marks=[pytest.mark.xfail(reason=KNOWN_MISREADS[row[0]], strict=True)] if row[0] in KNOWN_MISREADS else [],
        )
        for row in EXPECTED_CHEQUES[1:]
    ],
)
def test_cheque(cheque_output, expected_row):
    rows = read_csv(cheque_output / "cheques.csv")[1:]
    assert rows[EXPECTED_CHEQUES.index(expected_row) - 1] == expected_row


def test_cheque_duplicates(cheque_output):
    assert_same_csv(cheque_output / "cheque_duplicates.csv", EXPECTED / "cheque_duplicates.csv")


def test_receipts(receipt_output):
    assert_same_csv(receipt_output / "receipts.csv", EXPECTED / "receipts.csv")


def test_receipt_duplicates(receipt_output):
    assert_same_csv(receipt_output / "receipt_duplicates.csv", EXPECTED / "receipt_duplicates.csv")
