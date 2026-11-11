from __future__ import annotations

import csv
from pathlib import Path

from .pdf_lines import read_lines
from .table import Table, extract_table
from .validate import CheckResult, check_table


def default_output_path(pdf: Path) -> Path:
    """statement.pdf -> statement.csv, in the same folder."""
    return pdf.with_suffix(".csv")


def write_csv(path: Path, table: Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(table.header)
        writer.writerows(table.rows)


def convert(pdf: Path, output: Path) -> tuple[Table, CheckResult]:
    lines, _used_ocr = read_lines(pdf)
    table = extract_table(lines)
    result = check_table(table)
    write_csv(output, table)
    return table, result
