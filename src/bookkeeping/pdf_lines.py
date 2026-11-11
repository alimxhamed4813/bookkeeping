from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pdfplumber

from .models import Line, Word

OCR_DPI = 300


class OcrUnavailableError(RuntimeError):
    pass


def read_lines(path: Path) -> tuple[list[Line], bool]:
    """Return every line of the PDF in reading order, and whether OCR was needed."""
    lines: list[Line] = []
    used_ocr = False
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = _text_layer_words(page)
            if not words:
                words = _ocr_words(page)
                used_ocr = True
            lines.extend(_group_into_lines(words, page_number))
    return lines, used_ocr


def _text_layer_words(page) -> list[Word]:
    return [
        Word(text=w["text"], x0=w["x0"], x1=w["x1"], top=w["top"])
        for w in page.extract_words(keep_blank_chars=False, use_text_flow=False)
    ]


def _ocr_words(page) -> list[Word]:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception as exc:  # binary missing or not on PATH
        raise OcrUnavailableError(
            "This PDF page has no text layer and needs OCR, but the Tesseract program "
            "was not found. Install it (macOS: `brew install tesseract`, "
            "Ubuntu: `sudo apt install tesseract-ocr`) and try again."
        ) from exc

    # Grayscale at 300 dpi reads noticeably better than the default RGB render
    # (in testing, RGB turned a "990.00" into "390,00").
    image = page.to_image(resolution=OCR_DPI, antialias=True).original.convert("L")
    scale = page.width / image.width  # pixels -> PDF points
    data = pytesseract.image_to_data(
        image, config="--psm 6", output_type=pytesseract.Output.DICT
    )

    # Tesseract already groups words into lines. Keep its grouping (it copes with
    # the slight skew of a scan) and record it on the word via a synthetic `top`.
    grouped: dict[tuple[int, int, int], list[Word]] = defaultdict(list)
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped[key].append(
            Word(
                text=text,
                x0=data["left"][i] * scale,
                x1=(data["left"][i] + data["width"][i]) * scale,
                top=data["top"][i] * scale,
                confidence=float(data["conf"][i]),
            )
        )
    words: list[Word] = []
    for line_words in grouped.values():
        line_top = min(w.top for w in line_words)
        for w in line_words:
            w.top = line_top  # same top => same line in _group_into_lines
        words.extend(line_words)
    return words


def _group_into_lines(words: list[Word], page_number: int, tolerance: float = 3.0) -> list[Line]:
    """Cluster words whose tops are within `tolerance` points into one line."""
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(lines[-1][0].top - word.top) <= tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [Line(words=sorted(ws, key=lambda w: w.x0), page=page_number) for ws in lines]
