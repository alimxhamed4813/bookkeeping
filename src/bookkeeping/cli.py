"""Command line entry point: `bookkeeping extract <pdfs or folders> -o output/`."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from .duplicates import mark_duplicates
from .export import STATEMENT_COLUMNS, TRANSACTION_COLUMNS, statement_rows, transaction_rows, write_csv
from .pdf_lines import OcrUnavailableError
from .statements import parse_statement


def collect_pdfs(paths: list[Path]) -> list[Path]:
    pdfs: list[Path] = []
    for p in paths:
        if p.is_dir():
            pdfs.extend(sorted(x for x in p.iterdir() if x.suffix.lower() == ".pdf"))
        else:
            pdfs.append(p)
    return pdfs


def extract(args: argparse.Namespace) -> int:
    pdfs = collect_pdfs(args.inputs)
    if not pdfs:
        print("No PDF files found.", file=sys.stderr)
        return 1

    statements, failed, seen_hashes = [], 0, {}
    for pdf in pdfs:
        if not pdf.exists():
            print(f"✗ {pdf}: file not found", file=sys.stderr)
            failed += 1
            continue
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha in seen_hashes:
            print(f"• {pdf.name}: identical to {seen_hashes[sha]}, skipped as a duplicate file")
            continue
        seen_hashes[sha] = pdf.name
        try:
            statements.append(parse_statement(pdf))
        except OcrUnavailableError as exc:
            print(f"✗ {pdf.name}: {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:  # keep going so one bad file doesn't stop the batch
            print(f"✗ {pdf.name}: could not be read ({exc})", file=sys.stderr)
            failed += 1

    duplicate_findings = mark_duplicates(statements)

    out: Path = args.output
    write_csv(out / "transactions.csv", TRANSACTION_COLUMNS, transaction_rows(statements))
    write_csv(out / "statements.csv", STATEMENT_COLUMNS, statement_rows(statements))

    for s in statements:
        status = {True: "reconciles", False: "DOES NOT RECONCILE", None: "could not reconcile"}[s.reconciles]
        review = sum(t.needs_review for t in s.transactions)
        period = f"{s.period_start} to {s.period_end}" if s.period_start else "period unknown"
        print(
            f"{'✓' if s.reconciles else '!'} {s.source_file}\n"
            f"    {s.institution} {s.account_type.replace('_', ' ')}, {period}{' (OCR)' if s.ocr else ''}\n"
            f"    {len(s.transactions)} transactions, {status} "
            f"(opening {s.opening_balance}, closing {s.closing_balance}), {review} need review"
        )
        for issue in s.issues:
            print(f"    - {issue}")

    if duplicate_findings:
        print("\nDuplicates:")
        for finding in duplicate_findings:
            print(f"  - {finding}")
    else:
        print("\nNo duplicate transactions found.")

    total = sum(len(s.transactions) for s in statements)
    print(f"\nWrote {total} rows to {out / 'transactions.csv'} and a summary to {out / 'statements.csv'}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bookkeeping", description="Turn statement PDFs into clean transaction rows."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="Extract transactions from statement PDFs.")
    ex.add_argument("inputs", nargs="+", type=Path, help="PDF files and/or folders of PDFs")
    ex.add_argument("-o", "--output", type=Path, default=Path("output"), help="Output folder (default: output/)")
    ex.set_defaults(func=extract)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
