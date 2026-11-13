# riipen-bookkeeping

Turns bookkeeping documents into clean CSV rows, the way tools like Hubdoc and Dext do.

| Part | What it covers | Command |
|---|---|---|
| [Starter task](#starter-task-bank-and-credit-card-statements) | Bank and credit card statement PDFs, including scans | `uv run bookkeeping statement.pdf` |
| [Part 1](#part-1-cheques-and-receipts) | Handwritten cheques and printed receipts, with duplicate detection | `uv run capture.py cheque FOLDER` |

To run every test in the project:

```bash
uv run pytest
```

## Starter task: bank and credit card statements

Converts the transaction table in a bank or credit card statement PDF into a CSV file. It also
works on scanned statements, using OCR.

The CSV is a faithful copy of the statement's table:

- The columns are the table's own column headers.
- Every row the table prints is included, the opening and closing balance rows too.
- Values are written exactly as printed.

Before the file is written, the tool checks that the rows add up to the statement's balances.

The sample statements are in [`examples/`](examples/).

### Setup

You need [uv](https://docs.astral.sh/uv/) and, for scanned PDFs, the free
[Tesseract](https://github.com/tesseract-ocr/tesseract) OCR program:

```bash
brew install tesseract          # macOS
sudo apt install tesseract-ocr  # Ubuntu/Debian
```

uv installs the Python dependencies (`pdfplumber`, `pytesseract`, `pytest`) on the first run.

### Usage

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

### What the output looks like

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

### How it works

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

### Tests

```bash
uv run pytest --ignore=tests/test_part_one.py
```

The starter task has 79 tests:

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

## Part 1: cheques and receipts

[`capture.py`](capture.py) reads a folder of cheques or receipts, writes one clean row per
document to a CSV, and lists any duplicates in a second CSV.

### Dependencies

| Dependency | Needed for | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Running the script; it installs the Python packages (`pdfplumber`, `pytesseract`, `pillow`) on the first run | See the uv site |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Reading printed text: receipts, and the bank name and address on cheques | `brew install tesseract` (macOS) or `sudo apt install tesseract-ocr` (Ubuntu) |
| [Ollama](https://ollama.com) with the `qwen2.5vl:7b` model (6 GB) | Reading the handwriting on cheques. Free, and runs on your own computer. Not needed for receipts | Install Ollama, then run the command below |

```bash
ollama pull qwen2.5vl:7b
```

### How to run

```bash
uv run capture.py cheque part_one_examples/part_one_cheques -o output
```

```bash
uv run capture.py receipt part_one_examples/part_one_reciepts -o output
```

The arguments are:

1. **File type**: `cheque` or `receipt`.
2. **Location**: one file, or a folder of files (PDF, PNG or JPG).
3. **`-o` / `--output-dir`** (optional): the folder for the CSVs. The default is `output/`.

Cheques take about 6 seconds each on an Apple M2; receipts are near-instant.

### What it writes

| File type | Rows | Duplicates |
|---|---|---|
| `cheque` | `cheques.csv` | `cheque_duplicates.csv` |
| `receipt` | `receipts.csv` | `receipt_duplicates.csv` |

**`cheques.csv`** has one row per cheque:

```csv
cheque_number,date,payee,amount,amount_in_words,memo,bank,bank_address
1001,2026-08-04,Northside Aggregates Inc,1250.00,One thousand two hundred fifty and 00/100,Gravel delivery Jul 28,Maple Northern Bank,"100 Maple Avenue, Anytown, ON L0L 0L1"
```

**`receipts.csv`** has one row per receipt. Each line item gets a pair of columns:

```csv
receipt_number,vendor,location,date,item_1,item_1_amount,item_2,item_2_amount,subtotal,tax,tax_amount,total,paid_by,note
R01,FLOURWORKS SUPPLY CO,"Mississauga, ON",2026-09-06,Bread flour 25kg,447.40,Yeast and bakery sundries,298.26,745.66,HST 13%,96.94,842.60,Visa ending 0000 (approved),
```

Values are cleaned up: dates are written as `YYYY-MM-DD` and amounts as plain numbers such as
`1250.00`. Names and memos are kept as written, without trailing punctuation. An unpaid invoice has
an empty `paid_by` and its wording in `note` (for example, `INVOICE - amount due in 30 days`).

**The duplicates files** have one row per duplicate, naming the earlier document it repeats:

```csv
receipt_number,duplicate_of,reason
R02,R01,"Same vendor, date, items and total"
R15,R06,"Same vendor, date, items and total"
```

- A receipt is a duplicate when its vendor, date, line items and total all match an earlier receipt.
- A cheque is a duplicate when its cheque number, or its payee, date and amount, match an earlier cheque.
- The sample cheques contain no duplicates, so `cheque_duplicates.csv` has only its header row.

### Checks the script makes

The script prints a warning whenever one of these checks fails or changes a value:

- **Receipts**: the line items must add up to the subtotal, and subtotal + tax must equal the total.
- **Cheque amounts**: the amount is read twice, from the figures box and from the amount in words.
  If the two disagree, the script says so.
- **Cheque years**: the model sometimes misreads a handwritten year (for example, `26` as `20`). A
  date more than a year away from the rest of the batch is given the nearest plausible year. On the
  samples, this corrects cheques 1002 and 1008.

### Tests

```bash
uv run pytest tests/test_part_one.py
```

The tests run `capture.py` on the sample folders and compare its CSVs with the hand-written ones in
[`tests/expected_outputs/`](tests/expected_outputs/). They are skipped if Tesseract or Ollama is missing.

- **Receipts**: all 16 rows and both duplicate pairs match.
- **Cheques**: 7 of the 10 rows match exactly. The other 3 each have one handwritten field the
  model misreads. The expected CSV holds the correct text, so those rows are marked as known failures:

| Cheque | Field | Written | Read as |
|---|---|---|---|
| 1003 | memo | Supplies Invoice 4471 | Supplies hvoie 4471 |
| 1007 | payee | Ridgeway Printing Inc | Ridgeway Painting |
| 1008 | memo | PPE Stock | PDE Stack |

Dates, amounts, cheque numbers and bank details are correct on all 10 cheques.
