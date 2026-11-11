# riipen-bookkeeping

Turns bank and credit card statement PDFs into clean transaction rows, ready to import
into bookkeeping software (similar to Hubdoc or Dext). It also works on scanned statements, using OCR.

Every statement is checked against its own totals: the opening balance plus all the
transactions must equal the printed closing balance. Rows the tool is not sure about are
flagged for review rather than silently guessed.

This is the **starter task**: the three sample statements in [`examples/`](examples/).

## Setup

You need [uv](https://docs.astral.sh/uv/) and, for scanned PDFs, the free
[Tesseract](https://github.com/tesseract-ocr/tesseract) OCR program:

```bash
brew install tesseract          # macOS
sudo apt install tesseract-ocr  # Ubuntu/Debian
```

Python dependencies (`pdfplumber`, `pytesseract`, `pytest`) are installed by uv on the first run.

## Usage

```bash
uv run bookkeeping extract examples -o output
```

You can pass any mix of PDF files and folders. The command writes two files:

- `output/transactions.csv`: one row per transaction, across all statements.
- `output/statements.csv`: one row per statement, showing its period, balances, whether it reconciles, and any issues.

It also prints a summary:

```
✓ Sample Statement 1 - Maple Northern Bank chequing.pdf
    Maple Northern Bank chequing, 2025-12-15 to 2026-01-14
    20 transactions, reconciles (opening 4210.66, closing 9638.46), 0 need review
✓ Sample Statement 2 - Lakeshore Trust business credit card.pdf
    LAKESHORE TRUST credit card, 2026-09-06 to 2026-10-05
    18 transactions, reconciles (opening 3488.21, closing 4976.35), 0 need review
✓ Sample Statement 3 - Prairie Community Credit Union (scanned).pdf
    PRAIRIE COMMUNITY CREDIT UNION chequing, 2026-08-01 to 2026-08-31 (OCR)
    16 transactions, reconciles (opening 5302.18, closing 8756.97), 0 need review

No duplicate transactions found.
```

The exit code is `1` if any file could not be read, and `0` otherwise.

## Output columns (`transactions.csv`)

| Column | Meaning |
|---|---|
| `row_id` | Stable ID: the first 8 characters of the file's SHA-256 hash, then the row number. |
| `source_file`, `page` | Where the row came from. |
| `institution`, `account_type`, `account_holder`, `account_number` | From the statement header. `account_type` is `chequing`, `credit_card`, `savings` or `unknown`. |
| `date` | Transaction date (ISO). If the statement prints dates without a year ("Dec 16"), the year comes from the statement period, so a Dec–Jan statement gets the right year on each side. |
| `posted_date` | Posting date, when the statement shows one (credit cards). |
| `description` | The transaction line as printed. |
| `details` | Indented lines printed under the transaction, such as the city, "AUTO-PAY" or FX details. |
| `money_out`, `money_in` | Positive amounts, split the way a 4-column bank import expects. |
| `amount` | Signed amount, from the business's point of view: **negative means money out**. On a credit card, a purchase is negative and a payment or refund is positive (the QuickBooks convention for card feeds). |
| `balance` | Running balance printed on that row, if any. |
| `cheque_number` | Taken from `CHEQUE #1187` or `CHQ#2041`. |
| `foreign_currency`, `foreign_amount`, `fx_rate` | Taken from lines like `USD 49.99 @ 1.371874`. The tool checks that the converted amount matches the amount charged. |
| `duplicate_of` | The `row_id` of the row this one repeats (see below). |
| `needs_review`, `review_notes` | `yes` plus the reason, whenever a human should look at the row. |

## How it works

1. **Read the page** ([`pdf_lines.py`](src/bookkeeping/pdf_lines.py)). PDFs with a text
   layer are read directly with `pdfplumber`. Pages without one (scans) are rendered at 300 dpi
   in grayscale and read with Tesseract. Both paths produce the same thing: lines of words, each with its x-position.
2. **Find the table** ([`statements.py`](src/bookkeeping/statements.py)). The header row
   (`Withdrawals / Deposits / Balance`, `DEBIT / CREDIT / BALANCE` or `AMOUNT`) tells the
   tool where each money column sits on the page. Each number is assigned to the nearest column by its right edge.
   No bank-specific templates are needed: all three samples use the same code.
3. **Read rows**. A line that starts with a date is a transaction. An indented line directly
   below it with no amount is a detail line. Opening and closing balance lines are captured. Page
   furniture ("Continued on next page", repeated headers, footers) is skipped. A line that looks
   like a transaction but can't be read is reported as an issue rather than dropped.
4. **Verify**. On statements with a running balance, every row is checked: the previous balance
   plus the amount must equal the printed balance.
   - If the balances on both sides agree, but the amount doesn't, the amount was misread (typically OCR).
     The tool uses the amount implied by the balances and flags the row. In testing, OCR without
     grayscale conversion read `990.00` as `390,00`. This check catches that kind of error.
   - If an amount is in the wrong column (the sign disagrees with the balance), the tool fixes the direction and flags the row.
   - If neither number can be trusted, the row is flagged and the statement is reported as not reconciling.
   - Finally, opening + transactions must equal closing for every statement, including credit cards, which have no running balance.

## Duplicates

[`duplicates.py`](src/bookkeeping/duplicates.py) treats three cases differently:

- **The same file twice**: it's detected by file hash and skipped.
- **The same transaction on two statements for the same account** (overlapping periods, or the
  same statement downloaded twice): the later row gets `duplicate_of` set, so it isn't imported twice.
  Dates may differ by up to 3 days.
- **The same date, amount and description twice on one statement**: this is often real (two
  identical purchases), so the row is only flagged as a *possible* duplicate.
- A cheque number clearing twice is also flagged.

Reversals are not duplicates. On Sample 1, `CHEQUE #1189 −480.00` followed by
`NSF ITEM RETURNED +480.00` are two real rows that cancel out, and both are kept. The same
vendor with different amounts (two `FLOURWORKS SUPPLY CO` charges) is also not a duplicate.
The three samples contain no duplicates.

## Tests

```bash
uv run pytest
```

There are 47 tests:

- Amount and date parsing, including OCR quirks and year inference across New Year.
- The balance checks, using synthetic statements with deliberate misreads.
- Duplicate rules.
- The CLI.
- End-to-end checks of all three samples: every row count, balance and key amount.

The scanned-PDF tests are skipped if Tesseract isn't installed.

## Limitations and next steps

- So far, the tool has only been tested on the three sample layouts. A statement with no table
  header row, or with amounts that aren't right-aligned under their headers, will need the
  column logic extended.
- The tool assumes one account per PDF.
- OCR quality depends on the scan. Misreads are caught when there is a running balance. On
  statements without one, low-confidence OCR amounts are flagged for review instead.
- Part 1 adds cheques (1001–1010) and receipts/bills to the same row format.
