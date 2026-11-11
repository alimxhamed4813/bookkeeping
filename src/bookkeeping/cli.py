"""Command line entry point: `bookkeeping statement.pdf [-o statement.csv]`.

Exit codes: 0 = CSV written and the totals check out (or there is nothing to check),
1 = no CSV written (missing file, unreadable PDF, no table, OCR unavailable),
2 = CSV written, but the table does not add up. See the warnings.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import pipeline
from .pdf_lines import OcrUnavailableError
from .table import NoTableFoundError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bookkeeping",
        description="Convert the transaction table in a bank or credit card statement PDF into a CSV file.",
    )
    parser.add_argument("pdf", type=Path, help="path to the statement PDF")
    parser.add_argument(
        "-o", "--output", type=Path, help="where to write the CSV (default: next to the PDF, same name, .csv)"
    )
    args = parser.parse_args(argv)

    pdf: Path = args.pdf
    if not pdf.is_file():
        print(f"Error: {pdf}: file not found", file=sys.stderr)
        return 1
    output = args.output or pipeline.default_output_path(pdf)

    try:
        table, result = pipeline.convert(pdf, output)
    except OcrUnavailableError as exc:
        print(f"Error: {pdf.name}: {exc}", file=sys.stderr)
        return 1
    except NoTableFoundError as exc:
        print(f"Error: {pdf.name}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pdfplumber/pdfminer raise many types for damaged or non-PDF files
        print(f"Error: could not read {pdf.name} as a PDF ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    print(f"Wrote {len(table.rows)} rows to {output}")
    if result.reconciles:
        print("Totals check out: every balance on the statement matches the rows.")
    return 2 if result.reconciles is False else 0


if __name__ == "__main__":
    sys.exit(main())
