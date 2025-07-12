# drhp_toc_extractor.py (v1.3)
"""
DRHP Table‑of‑Contents extractor with **auto‑healing page mapping** and fully
customisable output path.

--------------------------------------------------------------------------
**NEW IN v1.3**
1. **Output‑path arg restored.**
   ```bash
   python drhp_toc_extractor.py <PDF> "<Company>" <output_dir>
   ```
   ‑ If `<output_dir>` is omitted, the script writes to the current working
     directory.
   ‑ Every artefact still sits inside the folder `"<Company> TOC PDFS"/` so
     nothing collides.
2. **Fail‑safe TOC parsing.**  The regex now tolerates a variety of dot‑leaders
   (……, ····, spaces) and odd Unicode dashes.  If regex fails, a *numeric‑tail*
   heuristic grabs any line that ends with digits.
3. **Verbose diagnostics.**  When parsing finds zero entries the script dumps a
   text snapshot of the TOC page into `toc_debug.txt` so you can inspect what
   OCR actually saw.
--------------------------------------------------------------------------

Install deps once:
```bash
pip install pypdf pdf2image pdfplumber pillow pytesseract openai
```
Run:
```bash
export OPENAI_API_KEY=sk‑...
python drhp_toc_extractor.py DRHP.pdf "Ather Energy" /path/to/output
```
The structure becomes:
```
/path/to/output/
  └─ Ather Energy TOC PDFS/
       ├─ toc.json
       ├─ 01_SECTION_I_GENERAL.pdf
       └─ …
```
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple

import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytesseract

# OpenAI optional (script will fallback to OCR‑only mode if missing)
try:
    import openai
except ImportError:  # pragma: no cover
    openai = None  # type: ignore

# ---------------------------------------------------------------------------
FIRST_N_PAGES = 10
LLM_MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = (
    'You are a document‑analysis assistant. Reply ONLY in JSON: {"toc_page": true} '
    "if the supplied image shows the Table of Contents of a Draft Red Herring "
    'Prospectus, else {"toc_page": false}.'
)


@dataclass
class TocEntry:
    section_title: str
    doc_page: int  # printed page number
    pdf_page: int  # zero‑based index in file


# ---------------------------------------------------------------------------
# Rasterise first N pages


def rasterise_pages(pdf_path: Path, n_pages: int = FIRST_N_PAGES) -> List[Image.Image]:
    return convert_from_path(
        str(pdf_path), first_page=1, last_page=n_pages, fmt="png", dpi=300
    )


# ---------------------------------------------------------------------------
# Detect TOC page


def is_toc_page(img: Image.Image) -> bool:
    """Returns True when image is TOC. Tries LLM vision then OCR keyword."""
    if openai is None or not os.getenv("OPENAI_API_KEY"):
        return "TABLE OF CONTENTS" in pytesseract.image_to_string(img).upper()

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": data_url}}],
        },
    ]
    try:
        r = openai.chat.completions.create(
            model=LLM_MODEL, messages=messages, temperature=0, max_tokens=6
        )
        return bool(json.loads(r.choices[0].message.content).get("toc_page"))
    except Exception as e:
        print(f"[warn] vision‑LLM down: {e}; falling back to OCR", file=sys.stderr)
        return "TABLE OF CONTENTS" in pytesseract.image_to_string(img).upper()


# ---------------------------------------------------------------------------
# OCR the printed page number from page footer


def ocr_bottom_page_number(img: Image.Image) -> int | None:
    w, h = img.size
    footer = img.crop((0, int(h * 0.85), w, h))
    txt = pytesseract.image_to_string(footer)
    nums = re.findall(r"\b(\d{1,4})\b", txt)
    return int(nums[-1]) if nums else None


# ---------------------------------------------------------------------------
# Extract raw text from TOC page (pdfplumber + OCR merge)


def extract_raw_text(pdf_path: Path, page_idx: int, img: Image.Image) -> str:
    with pdfplumber.open(str(pdf_path)) as pdf:
        plumber_text = pdf.pages[page_idx].extract_text(x_tolerance=3) or ""
    return plumber_text + "\n" + pytesseract.image_to_string(img)


# ---------------------------------------------------------------------------
# Parse TOC lines robustly


def parse_toc_lines(raw: str) -> List[Tuple[str, int]]:
    lines = [
        ln.strip()
        for ln in raw.splitlines()
        if ln.strip() and not set(ln) <= {".", "·", " "}
    ]
    entries: List[Tuple[str, int]] = []

    # Primary regex – dot/dash leaders before page #
    dot_pat = re.compile(r"^(?P<title>.+?)\s*[\.·\s‑–—]{2,}\s*(?P<page>\d{1,4})$")
    # Fallback – any line ending in digits
    tail_pat = re.compile(r"^(?P<title>.+?)\s+(?P<page>\d{1,4})$")

    for ln in lines:
        m = dot_pat.match(ln) or tail_pat.match(ln)
        if m:
            title = re.sub(r"\s+", " ", m.group("title").strip(".· ‑–—"))
            try:
                page = int(m.group("page"))
            except ValueError:
                continue
            entries.append((title, page))
    return entries


# ---------------------------------------------------------------------------


def compute_modal_offset(offsets: List[int]) -> int:
    if not offsets:
        return 0
    freq = {}
    for o in offsets:
        freq[o] = freq.get(o, 0) + 1
    maxf = max(freq.values())
    modes = [k for k, v in freq.items() if v == maxf]
    return int(statistics.median(modes))


# ---------------------------------------------------------------------------


def split_pdf(pdf_path: Path, toc: List[TocEntry], out_dir: Path) -> None:
    reader = PdfReader(str(pdf_path))
    for i, entry in enumerate(toc):
        start = entry.pdf_page
        end = toc[i + 1].pdf_page if i + 1 < len(toc) else len(reader.pages)
        if not (0 <= start < len(reader.pages)):
            print(
                f"[skip] {entry.section_title}: pdf index {start} out of range",
                file=sys.stderr,
            )
            continue
        writer = PdfWriter()
        for p in range(start, end):
            writer.add_page(reader.pages[p])
        fname = re.sub(r"[^A-Za-z0-9]+", "_", entry.section_title)[:48]
        out_path = out_dir / f"{i+1:02d}_{fname}.pdf"
        with open(out_path, "wb") as fh:
            writer.write(fh)
        print(f"[saved] {out_path.relative_to(out_dir.parent)} (pdf {start+1}–{end})")


# ---------------------------------------------------------------------------
# Main orchestration


def main(
    pdf_file: str, company: str | None = None, out_base: str | None = None
) -> None:
    pdf_path = Path(pdf_file).expanduser().resolve()
    company_name = company or pdf_path.stem.title()

    base_dir = Path(out_base).expanduser().resolve() if out_base else Path.cwd()
    out_root = base_dir / f"{company_name} TOC PDFS"
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Scanning first {FIRST_N_PAGES} pages…")
    imgs = rasterise_pages(pdf_path)

    toc_pdf_idx = next((i for i, im in enumerate(imgs) if is_toc_page(im)), None)
    if toc_pdf_idx is None:
        print("[error] TOC page not detected", file=sys.stderr)
        sys.exit(1)
    print(f"Found TOC at PDF pg {toc_pdf_idx+1}")

    printed_pg = ocr_bottom_page_number(imgs[toc_pdf_idx])
    if printed_pg is not None:
        base_offset = toc_pdf_idx - printed_pg
        print(f"Printed page # {printed_pg} ⇒ offset {base_offset:+d}")
    else:
        base_offset = None
        print("[warn] Couldn't OCR printed page number on TOC; inferring…")

    raw_text = extract_raw_text(pdf_path, toc_pdf_idx, imgs[toc_pdf_idx])
    pairs = parse_toc_lines(raw_text)
    if not pairs:
        debug = out_root / "toc_debug.txt"
        debug.write_text(raw_text, encoding="utf-8")
        print(
            f"[error] No TOC entries parsed. Raw text dumped to {debug}",
            file=sys.stderr,
        )
        sys.exit(1)

    reader = PdfReader(str(pdf_path))

    offsets = []
    if base_offset is not None:
        offsets.append(base_offset)
    # heuristic guess using first entry (TOC usually precedes first section)
    offsets.append(toc_pdf_idx - pairs[0][1] - 1)

    sane_offsets = [
        off
        for off in offsets
        if all(0 <= p + off < len(reader.pages) for _, p in pairs[:5])
    ]
    offset = sane_offsets[0] if sane_offsets else compute_modal_offset(offsets)
    print(f"Using offset {offset:+d}")

    toc_entries = [TocEntry(t, p, p + offset) for t, p in pairs]

    in_range_offsets = [
        e.pdf_page - e.doc_page
        for e in toc_entries
        if 0 <= e.pdf_page < len(reader.pages)
    ]
    if in_range_offsets:
        best = compute_modal_offset(in_range_offsets)
        if best != offset:
            print(f"[adjust] Corrected offset to {best:+d}")
            for e in toc_entries:
                e.pdf_page = e.doc_page + best

    toc_json = out_root / "toc.json"
    toc_json.write_text(
        json.dumps([asdict(e) for e in toc_entries], indent=2), encoding="utf-8"
    )
    print(f"toc.json saved → {toc_json.relative_to(base_dir)}")

    split_pdf(pdf_path, toc_entries, out_root)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            'Usage: python drhp_toc_extractor.py <PDF> ["Company Name"] [output_dir]',
            file=sys.stderr,
        )
        sys.exit(1)
    pdf_arg = sys.argv[1]
    comp_arg = sys.argv[2] if len(sys.argv) > 2 else None
    out_arg = sys.argv[3] if len(sys.argv) > 3 else None
    main(pdf_arg, comp_arg, out_arg)
