# OCR Setup

OCR is **optional** and **off by default**. The extraction layer works fully
without it: PDFs with a text layer, DOCX, TXT/Markdown/CSV, and source-code
files are all extracted without OCR. OCR is only needed for:

- images (PNG, JPEG, WEBP) — screenshots, photos of invoices/receipts
- **scanned PDFs** (pages with no text layer, only embedded images)

When OCR is needed but unavailable, the module reports this honestly: it
raises `OCRNotAvailableError` (for image files) or emits a
`scanned_page_no_ocr` warning (for scanned PDF pages). It **never** pretends
OCR succeeded or returns fabricated text.

## 1. Architecture

```
image bytes ──▶ Pillow (open, EXIF transpose, downscale) ──▶ pytesseract ──▶ Tesseract binary
```

- `pytesseract` (Python wrapper) is installed via the `ocr` extra.
- The **Tesseract binary** must be installed separately — it is a native
  program, not a pip package. `pytesseract` shells out to it.
- The module imports `pytesseract` **lazily** (only when OCR is actually
  requested), so a machine without it can still run the rest of the pipeline.

## 2. Install the Tesseract binary

### Windows

1. Download the installer from UB-Mannheim:
   `https://github.com/UB-Mannheim/tesseract/wiki`
2. Install (default: `C:\Program Files\Tesseract-OCR\tesseract.exe`).
3. Ensure it is on `PATH`, or set `PROOFBRIDGE_TESSERACT_CMD` explicitly.

### macOS

```bash
brew install tesseract
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install tesseract-ocr
```

Additional languages: install e.g. `tesseract-ocr-deu` (German) and set
`PROOFBRIDGE_OCR_LANGUAGE=deu` (may be a comma-separated list).

Verify the installation:

```bash
tesseract --version
```

## 3. Install the Python wrapper

```bash
pip install -e "./ai_module[ocr]"
```

This adds `pytesseract` to the environment. The base install
(`pip install -e "./ai_module"`) intentionally does **not** include it.

## 4. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PROOFBRIDGE_OCR_ENABLED` | `false` | master switch — when false, images/scanned PDFs are handled with honest unavailability reporting |
| `PROOFBRIDGE_TESSERACT_CMD` | `""` | explicit path to the tesseract binary; empty = rely on `PATH` |
| `PROOFBRIDGE_OCR_LANGUAGE` | `eng` | language(s) passed to tesseract (`eng`, `deu`, `eng+deu`, ...) |
| `PROOFBRIDGE_MAX_IMAGE_PIXELS` | `25000000` | images larger than this (W×H) are downscaled before OCR with an `image_downscaled` warning |

## 5. Behavior contract

- `is_ocr_available(settings=None) -> tuple[bool, str | None]` checks the
  binary without raising; the second element explains why OCR is unavailable
  (missing binary, missing `pytesseract`, ...).
- **Image file** + OCR unavailable → `OCRNotAvailableError` with installation
  guidance in the message.
- **Scanned PDF page** + OCR unavailable → extraction continues; the page is
  left with empty text and a `scanned_page_no_ocr` warning carrying the
  reason. One bad page never crashes the whole document.
- OCR errors on a specific image (corrupt data, tesseract failure) raise
  `DocumentExtractionError` with the error **type** only — never file content.
- Empty OCR output (blank image, no text found) is not an error: the result
  carries a `no_text_recognized` warning.

## 6. Image preprocessing (automatic)

Before OCR, images are:

1. Opened with Pillow; EXIF orientation is applied (`exif_transpose`) so
   phone photos are rotated upright where the metadata allows.
2. Checked against `max_image_pixels`; oversized images are downscaled
   (LANCZOS resampling) with an `image_downscaled` warning.
3. Converted to RGB if needed.

Corrupt or unidentifiable image bytes raise `DocumentExtractionError`
(never a raw Pillow exception).

## 7. Verification

```python
from proofbridge_ai.services.ocr_service import is_ocr_available

available, reason = is_ocr_available()
print(available, reason)  # (True, None) when everything is set up
```

Then run the test suite: the OCR-dependent tests auto-skip when Tesseract is
not installed, so the suite stays green on machines with and without OCR.
