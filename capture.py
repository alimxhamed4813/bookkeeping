#!/usr/bin/env python3
"""Part 1 capture: turn cheques or receipts into clean CSV rows, and spot duplicates.

Usage:
    uv run capture.py cheque  part_one_examples/part_one_cheques  -o output
    uv run capture.py receipt part_one_examples/part_one_reciepts -o output

LOCATION is one file or a folder of files (PDF, PNG, JPG). Two CSVs are written to the
output folder: cheques.csv + cheque_duplicates.csv, or receipts.csv + receipt_duplicates.csv.

How documents are read:
  * Receipts are printed, so they are read with Tesseract OCR.
  * Cheques are handwritten. The printed bank name and address are read with Tesseract.
    The handwriting is read by a local vision model served by Ollama (free, offline).
    The amount is read twice, from the figures box and from the amount written in words,
    and the two readings are compared.

Exit codes: 0 = CSVs written, 1 = bad input, 3 = Tesseract or Ollama is missing.
"""

from __future__ import annotations

import argparse
import base64
import csv
import difflib
import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytesseract
from PIL import Image

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg"}
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("CAPTURE_MODEL", "qwen2.5vl:7b")


class MissingToolError(RuntimeError):
    """A program this script depends on (Tesseract, Ollama, or the model) is not available."""


def warn(message: str) -> None:
    print(f"Warning: {message}", file=sys.stderr)


# ----------------------------------------------------------------------------- files and OCR


def find_documents(location: Path) -> list[Path]:
    if location.is_dir():
        return sorted(p for p in location.iterdir() if p.suffix.lower() in SUPPORTED)
    return [location] if location.suffix.lower() in SUPPORTED else []


def load_image(path: Path) -> Image.Image:
    """Open an image file, or render the first page of a PDF."""
    if path.suffix.lower() == ".pdf":
        with pdfplumber.open(path) as pdf:
            return pdf.pages[0].to_image(resolution=300, antialias=True).original.convert("L")
    return Image.open(path).convert("L")


def ocr_lines(image: Image.Image) -> list[str]:
    """Printed text on the image, one string per non-empty line."""
    if shutil.which("tesseract") is None:
        raise MissingToolError(
            "Tesseract OCR was not found. Install it (macOS: `brew install tesseract`, "
            "Ubuntu: `sudo apt install tesseract-ocr`) and try again."
        )
    text = pytesseract.image_to_string(image, config="--psm 6")
    return [line.strip() for line in text.splitlines() if line.strip()]


def money(text: str) -> Decimal | None:
    """'$1,071.09' -> Decimal('1071.09')."""
    match = re.search(r"\d[\d,]*\.\d{2}", text)
    return Decimal(match.group().replace(",", "")) if match else None


LOOKS_LIKE_DIGIT = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})

# ----------------------------------------------------------------------------- receipts

AMOUNT_AT_END = re.compile(r"^(.*?)\s+\$?\s*(\d[\d,]*\.\d{2})$")
TAX_LINE = re.compile(r"^(HST|GST|PST|QST|VAT|TAX)\b", re.I)


def read_receipt(path: Path) -> dict:
    image = load_image(path)
    # Receipt images are small (480 px wide); enlarging them makes the OCR far more accurate.
    image = image.resize((image.width * 3, image.height * 3), Image.LANCZOS)
    lines = ocr_lines(image)

    row = {
        "receipt_number": "", "vendor": "", "location": "", "date": "", "items": [],
        "subtotal": "", "tax": "", "tax_amount": "", "total": "", "paid_by": "", "note": "",
    }
    header_done = False
    totals_done = False
    heading: list[str] = []
    for line in lines:
        if re.match(r"sample receipt", line.strip("‘'\"“ "), re.I):
            continue
        if not header_done:
            if line.lower().startswith("date"):
                if m := re.search(r"(\d{4}-\d{2}-\d{2})", line):
                    row["date"] = m[1]
                if m := re.search(r"Receipt\s*#\s*(\S+)", line, re.I):
                    # OCR confuses 0/O and 5/S; after the leading letter a receipt number is digits.
                    row["receipt_number"] = m[1][0] + m[1][1:].translate(LOOKS_LIKE_DIGIT)
                header_done = True
            else:
                heading.append(line)
            continue

        amount_match = AMOUNT_AT_END.match(line)
        if amount_match and not totals_done:
            label, amount = amount_match[1].strip(), f"{money(amount_match[2]):.2f}"
            if label.lower() == "subtotal":
                row["subtotal"] = amount
            elif TAX_LINE.match(label):
                row["tax"], row["tax_amount"] = label, amount
            elif label.lower() == "total":
                row["total"] = amount
                totals_done = True
            else:
                row["items"].append((label, amount))
        elif m := re.match(r"paid by:?\s*(.*)", line, re.I):
            row["paid_by"] = m[1].strip()
        elif totals_done and not row["note"]:
            row["note"] = line

    row["vendor"] = heading[0] if heading else ""
    row["location"] = heading[1] if len(heading) > 1 else ""
    check_receipt(path, row)
    return row


def check_receipt(path: Path, row: dict) -> None:
    """The receipt's own arithmetic tells us whether the amounts were read correctly."""
    try:
        items = sum(Decimal(amount) for _, amount in row["items"])
        subtotal, tax, total = Decimal(row["subtotal"]), Decimal(row["tax_amount"]), Decimal(row["total"])
    except ArithmeticError:
        warn(f"{path.name}: could not read the subtotal, tax or total; check this receipt.")
        return
    if items != subtotal:
        warn(f"{path.name}: line items add up to {items}, but the subtotal reads {subtotal}.")
    if subtotal + tax != total:
        warn(f"{path.name}: subtotal {subtotal} + tax {tax} does not equal the total {total}.")


def receipt_table(rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    item_count = max((len(r["items"]) for r in rows), default=0)
    header = ["receipt_number", "vendor", "location", "date"]
    for i in range(1, item_count + 1):
        header += [f"item_{i}", f"item_{i}_amount"]
    header += ["subtotal", "tax", "tax_amount", "total", "paid_by", "note"]
    table = []
    for r in rows:
        cells = [r["receipt_number"], r["vendor"], r["location"], r["date"]]
        for i in range(item_count):
            cells += list(r["items"][i]) if i < len(r["items"]) else ["", ""]
        cells += [r["subtotal"], r["tax"], r["tax_amount"], r["total"], r["paid_by"], r["note"]]
        table.append(cells)
    return header, table


def receipt_duplicates(rows: list[dict]) -> list[list[str]]:
    """A receipt that repeats an earlier one in everything but its receipt number."""
    seen: dict[tuple, str] = {}
    found = []
    for r in rows:
        key = (r["vendor"].upper(), r["date"], r["total"], tuple(r["items"]))
        if key in seen:
            found.append([r["receipt_number"], seen[key], "Same vendor, date, items and total"])
        else:
            seen[key] = r["receipt_number"]
    return found


# ----------------------------------------------------------------------------- cheques

CHEQUE_PROMPT = """This is a scan of a handwritten bank cheque. Transcribe the handwritten fields exactly as written.

- cheque_number: the number handwritten in the top right corner.
- date: the handwriting on the DATE line.
- payee: the name handwritten after "PAY TO THE ORDER OF".
- amount: the figures handwritten in the box after the $ sign.
- amount_in_words: the amount handwritten in words on the line that ends with "DOLLARS", including any cents written at the end of that line.
- memo: the handwriting after "FOR".

Ignore the signature. Use an empty string for a field you cannot read."""

CHEQUE_FIELDS = ["cheque_number", "date", "payee", "amount", "amount_in_words", "memo"]

def ask_vision_model(image: Image.Image, model: str, prompt: str, fields: list[str]) -> dict:
    """Send an image to the local Ollama model and return the named fields it transcribed."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = {
        "model": model,
        "stream": False,
        "format": {
            "type": "object",
            "properties": {name: {"type": "string"} for name in fields},
            "required": fields,
        },
        "options": {"temperature": 0, "seed": 0},  # same image -> same answer
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(buffer.getvalue()).decode()]}],
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MissingToolError(
                f"The Ollama model '{model}' is not installed. Run `ollama pull {model}` and try again."
            ) from exc
        raise
    except urllib.error.URLError as exc:
        raise MissingToolError(
            f"Could not reach Ollama at {OLLAMA_URL}, which is needed to read handwriting. "
            f"Install it from https://ollama.com, start it, and run `ollama pull {model}`."
        ) from exc
    return json.loads(answer["message"]["content"])


def read_cheque(path: Path, model: str) -> dict:
    image = load_image(path)
    bank, address = read_bank_block(image)
    seen = ask_vision_model(image, model, CHEQUE_PROMPT, CHEQUE_FIELDS)

    figures = parse_figures(seen["amount"])
    written = words_to_amount(seen["amount_in_words"])
    amount = settle_amount(path, seen["amount"], figures, written)

    cheque_date = parse_handwritten_date(seen["date"])
    if cheque_date is None:
        warn(f"{path.name}: could not understand the date {seen['date']!r}; left as written.")

    return {
        "cheque_number": re.sub(r"\D", "", seen["cheque_number"]),
        "date": cheque_date.isoformat() if cheque_date else seen["date"].strip(),
        "payee": tidy(seen["payee"]),
        "amount": f"{amount:.2f}" if amount is not None else "",
        # Once the words have been understood, write them out in one consistent style.
        "amount_in_words": amount_to_words(amount) if written is not None else tidy(seen["amount_in_words"]),
        "memo": tidy(seen["memo"]),
        "bank": bank,
        "bank_address": address,
    }


def read_bank_block(image: Image.Image) -> tuple[str, str]:
    """The bank's name and address are printed in the top-left corner of the cheque."""
    width, height = image.size
    lines = ocr_lines(image.crop((0, 0, int(width * 0.55), int(height * 0.38))))
    lines = [line.strip("|[]_ ") for line in lines if re.search(r"[A-Za-z]{3}", line)]
    if not lines:
        return "", ""
    return lines[0], fix_postal_code(", ".join(lines[1:]))


def fix_postal_code(address: str) -> str:
    """Canadian postal codes alternate letter-digit-letter digit-letter-digit; OCR mixes up 0/O and 1/I."""
    match = re.search(r"\b([A-Z0-9]{3}) ?([A-Z0-9]{3})$", address)
    if not match:
        return address
    code = match[1] + match[2]
    to_letter = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"})
    fixed = "".join(
        ch.translate(to_letter) if i % 2 == 0 else ch.translate(LOOKS_LIKE_DIGIT) for i, ch in enumerate(code)
    )
    return f"{address[: match.start()]}{fixed[:3]} {fixed[3:]}"


def tidy(text: str) -> str:
    """Collapse spaces and drop trailing punctuation ('Lakeshore Hardware Ltd.' -> '... Ltd')."""
    return re.sub(r"\s+", " ", text).strip(" .,;:-–—")


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse_handwritten_date(text: str) -> date | None:
    """'Aug 4/2026', 'Aug 6/26', 'Aug 17.26' or 'August 4, 2026' -> date."""
    # The separator before the year is usually '/', '.' or ','. A slash is sometimes read as a '1' ('25 126').
    match = re.search(r"([A-Za-z]{3})[a-z]*\.?\s*(\d{1,2})(?:st|nd|rd|th)?(?:\D{1,3}|\s+[1lI|])(\d{4}|\d{2})\b", text)
    if not match or match[1].lower() not in MONTHS:
        return None
    year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
    try:
        return date(year, MONTHS.index(match[1].lower()) + 1, int(match[2]))
    except ValueError:
        return None


def fix_outlier_years(paths: list[Path], rows: list[dict]) -> None:
    """Correct a year that does not fit the rest of the batch, and say so.

    The model reads the month and day reliably but sometimes misreads a handwritten year
    ('26' as '66' or '20'). Cheques captured together are written close together in time,
    so a date more than a year away from the batch's middle date gets the nearest
    plausible year instead. Every correction is printed as a warning for a human to check.
    """
    dated = []
    for path, row in zip(paths, rows):
        try:
            dated.append((path, row, date.fromisoformat(row["date"])))
        except ValueError:
            continue
    if len(dated) < 3:
        return
    middle = sorted(d for _, _, d in dated)[len(dated) // 2]
    for path, row, read in dated:
        if abs((read - middle).days) <= 366:
            continue
        candidates = []
        for year in (middle.year - 1, middle.year, middle.year + 1):
            try:
                candidates.append(read.replace(year=year))
            except ValueError:  # Feb 29 in a non-leap year
                continue
        best = min(candidates, key=lambda d: abs((d - middle).days))
        warn(
            f"{path.name}: the year was read as {read.year}, which does not fit the other cheques in this "
            f"batch (around {middle:%b %Y}). Used {best.year}; please check."
        )
        row["date"] = best.isoformat()


def parse_figures(text: str) -> Decimal | None:
    """The amount box: '1250-', '$2,075.—', '3,410.75' or '918.66' -> Decimal."""
    cleaned = re.sub(r"[^\d.,]", "", text).strip(".,")
    if not cleaned:
        return None
    if m := re.fullmatch(r"([\d,]+)[.,](\d{2})", cleaned):
        return Decimal(f"{m[1].replace(',', '')}.{m[2]}")
    digits = re.sub(r"\D", "", cleaned)
    return Decimal(digits) if digits else None


UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
NUMBER_WORDS = {w: i for i, w in enumerate(UNITS)} | {w: i * 10 for i, w in enumerate(TENS) if w}
NUMBER_WORDS |= {"hundred": 100, "thousand": 1000, "million": 1_000_000}
FILLER_WORDS = {"and", "dollars", "dollar", "only", "cents", "xx", "x", "no"}


def words_to_amount(text: str) -> Decimal | None:
    """'One thousand two hundred + fifty xx' -> 1250.00; 'Nine hundred eighteen 66/100' -> 918.66.

    Handwriting is messy, so each word is matched to the closest number word. Digits at the
    end of the line are the cents.
    """
    cents = 0
    ending = re.sub(r"[\s.\-–—]*\b(dollars?|cents?)\b[\s.]*$", "", text.strip(), flags=re.I)
    if m := re.search(r"(\d{1,2})\s*(?:/\s*(?:100|xx))?\s*$", ending.strip(" .-–—"), re.I):
        cents = int(m[1])
    total = current = 0
    found_number = False
    last_was_unit = False
    for token in re.findall(r"[a-z]+", text.lower()):
        if token in FILLER_WORDS:
            continue
        close = difflib.get_close_matches(token, NUMBER_WORDS, n=1, cutoff=0.75)
        if not close:
            continue
        value = NUMBER_WORDS[close[0]]
        found_number = True
        if value >= 1000:
            total += (current or 1) * value
            current = 0
        elif value == 100:
            current = (current or 1) * 100
        elif value >= 20:
            # "two forty" is how people say (and sometimes write) two hundred forty.
            if last_was_unit and 1 <= current % 100 <= 9:
                current += (current % 100) * 99
            current += value
        else:
            current += value
        last_was_unit = value < 20
    if not found_number:
        return None
    return Decimal(total + current) + Decimal(cents) / 100


def amount_to_words(amount: Decimal) -> str:
    """1250.00 -> 'One thousand two hundred fifty and 00/100'."""
    dollars, cents = int(amount), int(amount * 100) % 100

    def below_thousand(n: int) -> list[str]:
        words = []
        if n >= 100:
            words += [UNITS[n // 100], "hundred"]
            n %= 100
        if n >= 20:
            words.append(TENS[n // 10] + (f"-{UNITS[n % 10]}" if n % 10 else ""))
        elif n > 0:
            words.append(UNITS[n])
        return words

    words = []
    for scale, name in ((1_000_000, "million"), (1000, "thousand")):
        if dollars >= scale:
            words += below_thousand(dollars // scale) + [name]
            dollars %= scale
    words += below_thousand(dollars)
    text = " ".join(words) or "zero"
    return f"{text[0].upper()}{text[1:]} and {cents:02d}/100"


def settle_amount(path: Path, box_text: str, figures: Decimal | None, written: Decimal | None) -> Decimal | None:
    """Compare the amount read from the figures box with the amount read from the words."""
    if figures is None and written is None:
        warn(f"{path.name}: could not read the amount.")
        return None
    if figures is None or written is None:
        which = "amount in words" if written is None else "figures in the amount box"
        warn(f"{path.name}: could not read the {which}; the amount has no second reading to confirm it.")
        return figures if figures is not None else written
    if figures == written:
        return figures
    # A decimal point is easy to miss in handwriting: '1,746 20' reads as 174620.
    if re.sub(r"\D", "", box_text) == f"{written:.2f}".replace(".", ""):
        return written
    if int(figures) == int(written):
        warn(
            f"{path.name}: the dollars agree, but the cents read {figures % 1 * 100:02.0f} in the figures box "
            f"and {written % 1 * 100:02.0f} in the words. Used the figures; please check."
        )
        return figures
    warn(
        f"{path.name}: the figures read {figures:.2f} but the words read {written:.2f}. "
        f"Used the words (the legal amount on a cheque); please check."
    )
    return written


CHEQUE_COLUMNS = ["cheque_number", "date", "payee", "amount", "amount_in_words", "memo", "bank", "bank_address"]


def cheque_duplicates(rows: list[dict]) -> list[list[str]]:
    """A cheque number that appears twice, or the same payee, date and amount on two cheques."""
    by_number: dict[str, str] = {}
    by_details: dict[tuple, str] = {}
    found = []
    for r in rows:
        number, details = r["cheque_number"], (r["payee"].upper(), r["date"], r["amount"])
        if number and number in by_number:
            found.append([number, by_number[number], "Same cheque number"])
        elif details in by_details:
            found.append([number, by_details[details], "Same payee, date and amount"])
        by_number.setdefault(number, number)
        by_details.setdefault(details, number)
    return found


# ----------------------------------------------------------------------------- command line


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn cheques or receipts into clean CSV rows and spot duplicates.")
    parser.add_argument("type", choices=["cheque", "receipt"], help="what kind of document LOCATION holds")
    parser.add_argument("location", type=Path, help="a file, or a folder of files (PDF, PNG, JPG)")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output"), help="folder for the CSVs (default: output/)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama vision model for cheques (default: {DEFAULT_MODEL})")
    args = parser.parse_args(argv)

    if not args.location.exists():
        print(f"Error: {args.location} does not exist.", file=sys.stderr)
        return 1
    documents = find_documents(args.location)
    if not documents:
        print(f"Error: no PDF, PNG or JPG files found at {args.location}.", file=sys.stderr)
        return 1

    try:
        if args.type == "receipt":
            rows = [read_receipt(path) for path in documents]
            header, table = receipt_table(rows)
            duplicates = receipt_duplicates(rows)
        else:
            rows = []
            for path in documents:
                print(f"Reading {path.name} ...", flush=True)
                rows.append(read_cheque(path, args.model))
            fix_outlier_years(documents, rows)
            header, table = CHEQUE_COLUMNS, [[r[c] for c in CHEQUE_COLUMNS] for r in rows]
            duplicates = cheque_duplicates(rows)
    except MissingToolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    args.output_dir.mkdir(parents=True, exist_ok=True)
    main_csv = args.output_dir / f"{args.type}s.csv"
    duplicates_csv = args.output_dir / f"{args.type}_duplicates.csv"
    write_csv(main_csv, header, table)
    write_csv(duplicates_csv, [f"{args.type}_number", "duplicate_of", "reason"], duplicates)

    print(f"Wrote {len(table)} {args.type}s to {main_csv}")
    if duplicates:
        print(f"Found {len(duplicates)} duplicate(s), listed in {duplicates_csv}:")
        for number, original, reason in duplicates:
            print(f"  {number} duplicates {original}: {reason}")
    else:
        print(f"No duplicates found ({duplicates_csv} is empty).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
