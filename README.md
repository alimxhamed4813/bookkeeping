# riipen-bookkeeping

Converts the transaction table in a bank or credit card statement PDF into a CSV file. It also
works on scanned statements, using OCR.

The CSV is a faithful copy of the statement's table:

- The columns are the table's own column headers.
- Every row the table prints is included, the opening and closing balance rows too.
- Values are written exactly as printed.

Before the file is written, the tool checks that the rows add up to the statement's balances.

This is the **starter task**: the three sample statements in [`examples/`](examples/).

## Setup

You need [uv](https://docs.astral.sh/uv/) and, for scanned PDFs, the free
[Tesseract](https://github.com/tesseract-ocr/tesseract) OCR program:

```bash
brew install tesseract          # macOS
sudo apt install tesseract-ocr  # Ubuntu/Debian
```

uv installs the Python dependencies (`pdfplumber`, `pytesseract`, `pytest`) on the first run.

## Usage

```bash
uv run bookkeeping path/to/statement.pdf
```

This writes `path/to/statement.csv`, next to the PDF. Use `-o` to choose another location:

```bash
uv run bookkeeping path/to/statement.pdf -o output/statement.csv
```

For example:

```bash
uv run bookkeeping "examples/Sample Statement 1 - Maple Northern Bank chequing.pdf"
```

```
Wrote 22 rows to examples/Sample Statement 1 - Maple Northern Bank chequing.csv
Totals check out: every balance on the statement matches the rows.
```

| Exit code | Meaning |
|---|---|
| `0` | The CSV was written and the totals check out (or the statement has no balances to check). |
| `1` | No CSV was written: the file is missing or isn't a readable PDF, no table was found, or OCR is needed but Tesseract isn't installed. |
| `2` | The CSV was written, but the rows don't add up to the statement's balances. The warnings say which rows. |

## What the output looks like

The CSV columns are whatever the statement's table uses. The expected outputs for the three
samples are in [`tests/expected/`](tests/expected/). Their headers and first rows:

**Maple Northern Bank, chequing**
```csv
Date,Description,Withdrawals ($),Deposits ($),Balance ($)
Dec 15,Opening balance,,,"4,210.66"
Dec 16,E-TRANSFER RECEIVED - M. OKAFOR,,"1,450.00","5,660.66"
Dec 16,POS PURCHASE - HOME SUPPLY CENTRE #214,312.47,,"5,348.19"
```

**Lakeshore Trust, business credit card (2 pages)**
```csv
TRANS,POSTED,ACTIVITY DESCRIPTION,AMOUNT ($)
,,PREVIOUS STATEMENT BALANCE,"3,488.21"
SEP 06,SEP 08,FLOURWORKS SUPPLY CO MISSISSAUGA ON,842.60
SEP 09,SEP 10,PAYMENT - THANK YOU,"1,500.00 CR"
SEP 10,SEP 11,CLOUD BAKERY POS SUBSCRIPTION USD 49.99 @ 1.371874,68.58
```

**Prairie Community Credit Union, chequing (scanned)**
```csv
DATE,TRANSACTION,DEBIT,CREDIT,BALANCE
2026-08-01,BALANCE FORWARD,,,"5,302.18"
2026-08-04,DEPOSIT,,"2,450.00","7,752.18"
2026-08-04,CHQ#2041,780.00,,"6,972.18"
```

A few rules apply to every statement:

- **Text is copied as printed.** Dates, amounts and the `CR` marker for credits appear as the
  statement shows them. Amounts with thousands separators are quoted, as CSV requires.
- **Wrapped descriptions are joined.** Some rows have an indented second line, such as a city or
  the foreign-currency detail. That line is added to the end of the row's description.
- **Balance rows are kept.** "Opening balance", "PREVIOUS STATEMENT BALANCE", "BALANCE FORWARD",
  "Closing balance", "NEW BALANCE" and "CLOSING BALANCE" are rows like any other. When the
  statement prints no date for them, the date cell is empty.
- **Page furniture is skipped.** Page headers, "Continued on next page", "Page 2 of 2", the table
  header repeated on page 2, and footers don't become rows.

## How it works

1. **Read the page** ([`pdf_lines.py`](src/bookkeeping/pdf_lines.py)). PDFs with a text layer
   are read directly with `pdfplumber`. Pages without one (scans) are rendered at 300 dpi in
   grayscale and read with Tesseract. Either way, the result is lines of words, each with its position on the page.
2. **Rebuild the table** ([`table.py`](src/bookkeeping/table.py)). The header row is the first
   line that names at least three known columns (Date, Description, Withdrawals, Debit, Credit,
   Balance, Amount, and so on). Header words that are close together form one column name,
   e.g. `Withdrawals ($)`. Words below the header are placed into columns by their position:
   - Amounts are right-aligned, so each amount goes to the money column whose header ends nearest to where the amount ends.
   - Text is left-aligned, so it goes to the column it starts under.

   This means no bank-specific templates are needed: all three samples use the same code.
3. **Check the totals** ([`validate.py`](src/bookkeeping/validate.py)).
   - On running-balance statements, every row must satisfy: previous balance − money out + money in = printed balance.
   - On credit cards: previous balance + charges − credits = new balance.
   - If a row's amount disagrees with its balance, but the balances on both sides of it agree with
     each other, the amount was misread (typically by OCR). The tool corrects the cell and prints a
     warning asking you to check that row. An amount in the wrong column is moved to the right one.
     Anything that can't be explained is reported, and the exit code is 2.
4. **Write the CSV** ([`pipeline.py`](src/bookkeeping/pipeline.py)) and print a summary ([`cli.py`](src/bookkeeping/cli.py)).

## Tests

```bash
uv run pytest
```

There are 79 tests:

- **Expected output** ([`tests/test_sample_statements.py`](tests/test_sample_statements.py)).
  Each sample PDF is run through the CLI, the same way a user would run it. The output must
  match the hand-written CSV in [`tests/expected/`](tests/expected/) exactly: the header, every
  row and the row count.
- **Integrity** ([`tests/integrity.py`](tests/integrity.py)). An independent checker that doesn't
  use the pipeline's code. It verifies the arithmetic (every running balance, and the card totals)
  and the structure (cell counts, date formats, no page furniture, no repeated header). It runs
  on the real output, and on the expected CSVs too, to catch typos in the expected files.
- **Table rebuilding** ([`tests/test_table.py`](tests/test_table.py)). Synthetic pages cover
  header grouping, column placement, wrapped descriptions, `CR` markers, amounts inside
  descriptions, multi-page tables, and skipping page furniture.
- **Validation** ([`tests/test_validate.py`](tests/test_validate.py)). Covers OCR misread
  correction, an amount in the wrong column, unexplainable mismatches, a wrong closing balance,
  card totals, and tables with no balances.
- **CLI** ([`tests/test_cli.py`](tests/test_cli.py)). Runs as a real subprocess. Covers the
  default output location, `-o`, missing and non-PDF files, a PDF with no table, missing
  Tesseract, and the exit codes.
- **Parsing** ([`tests/test_parsing.py`](tests/test_parsing.py)). Amount and date recognition, including OCR quirks.
