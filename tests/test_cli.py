import csv
import shutil
from pathlib import Path

from bookkeeping.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CHEQUING = EXAMPLES / "Sample Statement 1 - Maple Northern Bank chequing.pdf"
CREDIT_CARD = EXAMPLES / "Sample Statement 2 - Lakeshore Trust business credit card.pdf"


def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_extract_writes_transactions_and_summary(tmp_path):
    assert main(["extract", str(CHEQUING), str(CREDIT_CARD), "-o", str(tmp_path)]) == 0

    rows = read(tmp_path / "transactions.csv")
    assert len(rows) == 38
    fee = next(r for r in rows if r["description"] == "MONTHLY ACCOUNT FEE")
    assert (fee["money_out"], fee["money_in"], fee["amount"]) == ("19.95", "", "-19.95")
    assert len({r["row_id"] for r in rows}) == 38

    summary = read(tmp_path / "statements.csv")
    assert [s["reconciles"] for s in summary] == ["yes", "yes"]


def test_same_file_twice_is_skipped(tmp_path, capsys):
    copy = tmp_path / "copy.pdf"
    shutil.copy(CHEQUING, copy)
    assert main(["extract", str(CHEQUING), str(copy), "-o", str(tmp_path / "out")]) == 0
    assert "identical to" in capsys.readouterr().out
    assert len(read(tmp_path / "out" / "transactions.csv")) == 20


def test_missing_file_returns_error(tmp_path):
    assert main(["extract", str(tmp_path / "nope.pdf"), "-o", str(tmp_path)]) == 1
