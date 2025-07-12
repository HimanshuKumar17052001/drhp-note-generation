import os
import shutil
import json
import logging

import pdfplumber
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

# import pytesseract

from dotenv import load_dotenv
import cv2
import base64
from concurrent.futures import ProcessPoolExecutor, as_completed

from app.models.schemas import Pages
from multiprocessing import get_context

import subprocess, shutil


import time


load_dotenv()

from baml_client import b
from baml_py import Collector
from baml_py import Image as baml_image_import


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


import os
import cv2
import numpy as np
from baml_py import Image as BamlImage


def strip_to_baml_image(strip_gray: np.ndarray) -> BamlImage:
    """
    Encode a grayscale numpy array as PNG‐bytes and then Base64-encode it
    to create a BAML Image object.
    """
    if strip_gray.size == 0:
        raise ValueError("Strip image is empty; nothing to send to BAML.")

    # Save to a temporary PNG in memory
    success, png_buf = cv2.imencode(".png", strip_gray)
    if not success:
        raise RuntimeError("Could not encode strip to PNG")

    png_bytes = png_buf.tobytes()
    b64_str = base64.b64encode(png_bytes).decode("utf-8")
    return BamlImage.from_base64("image/png", b64_str)


def read_strip_text(img_path: str) -> str:
    """
    OCR for very-short-height, very-wide images that contain a single line of
    text (page numbers, headers, footers, etc.), using BAML’s ExtractPageNumber.

    Steps:
      1. Load the image from disk (as grayscale).
      2. If needed, convert to a 2D numpy array of type uint8.
      3. Turn that numpy array into a BAML Image via strip_to_baml_image().
      4. Call BAML’s ExtractPageNumber on it (via call_baml_llm_on_strip()).
      5. Return the extracted string (e.g. “5” for page 5).
    """

    # 1) Read the image in grayscale
    gray = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"Could not load image at {img_path}")

    # 2) (Optional) If your strip is colored (3‐channel), uncomment and convert:
    # if len(gray.shape) == 3 and gray.shape[2] == 3:
    #     gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    # 3) Encode to BAMLImage and send to BAML
    baml_img = strip_to_baml_image(gray)
    result = b.ExtractPageNumber(baml_img)
    if result.is_page_number:
        return result.page_number
    else:
        return ""

    return page_str


def process_single_page_full(page_num, pdf_path, dpi, threshold, images_dir, page_text):
    """
    Render page → OCR footer → GetFactsFromPages + GetQueriesFromPages (BAML)
    Returns: page_num, ocr_text, facts, queries, token_in, token_out
    """

    ocr_text, facts, queries = "", [], []
    total_in, total_out = 0, 0  # token tallies

    # -------- OCR bottom strip exactly as before --------
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples).convert("L")
        doc.close()

        np_img = np.array(img)
        h, w = np_img.shape
        y_start = y_end = None
        scanning = False
        for y in range(h - 1, -1, -1):
            row = np_img[y, :]
            if not scanning and np.any(row < threshold):
                y_end, scanning = y, True
            elif scanning and np.all(row > threshold):
                y_start = y + 1
                break

        if y_start is not None and y_end is not None and y_end >= y_start:
            # strip = gray[y_start : y_end + 1, :]
            tmp_png = os.path.join(images_dir, f"page_{page_num}.png")
            Image.fromarray(np_img[y_start : y_end + 1, :]).save(tmp_png)
            try:
                ocr_text = read_strip_text(tmp_png)
                print(f"page number: {ocr_text}")
            finally:
                try:
                    os.remove(tmp_png)
                except OSError:
                    pass
    except Exception as e:
        logger.error(f"OCR failure p.{page_num}: {e}")

    # -------- BAML GetFactsFromPages --------
    try:
        c_facts = Collector(name=f"facts-p{page_num}")
        facts = b.GetFactsFromPages(
            page_text, baml_options={"collector": c_facts}
        ).facts
        total_in += c_facts.last.usage.input_tokens or 0
        total_out += c_facts.last.usage.output_tokens or 0
    except Exception as e:
        logger.error(f"BAML facts error p.{page_num}: {e}")

    # -------- BAML GetQueriesFromPages --------
    try:
        c_q = Collector(name=f"queries-p{page_num}")
        queries = b.GetQueriesFromPages(
            page_text, baml_options={"collector": c_q}
        ).Queries
        total_in += c_q.last.usage.input_tokens or 0
        total_out += c_q.last.usage.output_tokens or 0
    except Exception as e:
        logger.error(f"BAML queries error p.{page_num}: {e}")

    return page_num, ocr_text, facts, queries, total_in, total_out


def extract_page_text(pdf_path: str, page_no: int) -> tuple[int, str]:
    """
    Worker function for extracting text+tables from a single page.
    Returns (page_no, combined_text).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_no - 1]  # pdfplumber pages are 0-based internally
            text = page.extract_text() or ""

            # Gather tables if any
            tables = page.extract_tables()
            if tables:
                tables_text = ""
                for table in tables:
                    for row in table:
                        row_text = " | ".join(
                            cell.strip() if cell else "" for cell in row
                        )
                        tables_text += row_text + "\n"
                if tables_text.strip():
                    text += "\n\n[TABLES]\n" + tables_text.strip()

            return page_no, text
    except Exception as e:
        logger.error(f"Failed to extract text from page {page_no}: {e}")
        return page_no, ""


def process_pdf(
    pdf_path, company_name, company, dpi=200, threshold=245, max_workers=10
):
    """
    Processes a PDF to extract per-page text and bottom‐strip page‐number OCR, saving results as JSON.
    This version parallelises STEP 2 across up to `max_workers` processes.

    Args:
        pdf_path (str): Path to the source PDF file.
        company_name (str): Name of the company (used as the top‐level folder for temp data).
        dpi (int, optional): DPI for rendering pages with PyMuPDF. Default is 200.
        threshold (int, optional): Grayscale threshold for detecting dark pixels in the bottom strip. Default is 245.
        max_workers (int, optional): Number of parallel processes to use for OCR. Default is 20.

    Directory structure created under the current working directory:
        <company_name>/
            temp_stripped_bottom_images/      ← temporary folder to hold cropped bottom‐strip images
            temp_pages_json/                  ← folder to hold the final JSON file

    Output:
        A JSON file saved to:
            <company_name>/temp_pages_json/<pdf_filename>_pages.json
    """
    # Initialize token counters
    total_in = 0
    total_out = 0

    logger.info(f"Starting PDF processing for {pdf_path}")

    # Ensure the PDF exists
    if not os.path.isfile(pdf_path):
        logger.error(f"Cannot find PDF at path: {pdf_path!r}")
        raise FileNotFoundError(f"Cannot find PDF at path: {pdf_path!r}")

    pdf_name = os.path.basename(pdf_path)
    logger.info(f"Processing PDF: {pdf_name}")

    # Create base folder
    base_dir = os.path.join(os.getcwd(), company_name)
    os.makedirs(base_dir, exist_ok=True)
    logger.debug(f"Created/verified base directory: {base_dir}")

    # Create a temp directory for cropped bottom‐strip images
    images_dir = os.path.join(base_dir, "temp_stripped_bottom_images")
    os.makedirs(images_dir, exist_ok=True)
    logger.debug(f"Created/verified images directory: {images_dir}")

    # Create a directory for the final JSON
    json_dir = os.path.join(base_dir, "temp_pages_json")
    os.makedirs(json_dir, exist_ok=True)
    logger.debug(f"Created/verified JSON directory: {json_dir}")

    # pages_to_process = range(1, 150)
    logger.info("Starting Step 1: text+table extraction with 20 workers…")
    pages_data: dict[str, dict] = {}
    # We'll submit one task per page_no

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    doc.close()

    with ProcessPoolExecutor(max_workers=20) as text_executor:
        future_to_pageno = {
            text_executor.submit(extract_page_text, pdf_path, pno): pno
            for pno in range(1, total_pages + 1)
            # for pno in range(1, 20)
        }

        for future in as_completed(future_to_pageno):
            pno = future_to_pageno[future]
            try:
                page_no, combined_text = future.result()
            except Exception as e:
                logger.error(f"Exception extracting page {pno}: {e}")
                page_no, combined_text = pno, ""
            # Store the skeleton of pages_data; facts/queries/ocr fields will be filled later
            pages_data[str(page_no)] = {
                "page_content": combined_text,
                "page_number_drhp": "",
                "facts": [],
                "queries": [],
            }
            logger.info(f"Extracted text for page {page_no}")

    logger.info("Completed all text+table extraction. Now sleeping for 3 seconds…")
    time.sleep(3)

    logger.info(f"Total pages to process: {total_pages}")

    # Launch a pool of worker processes
    futures = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as ex:
        futures = {
            ex.submit(
                process_single_page_full,
                pno,
                pdf_path,
                dpi,
                threshold,
                images_dir,
                pages_data[str(pno)]["page_content"],  # pass page text
            ): pno
            for pno in range(1, total_pages + 1)
            # for pno in range(1, 20)
        }

        for fut in as_completed(futures):
            (pno, ocr_text, facts, queries, in_tok, out_tok) = (
                fut.result()
            )  # NEW tuple unpack
            total_in += in_tok
            total_out += out_tok  # accumulate tokens

            # update JSON + Mongo exactly as before …
            pages_data[str(pno)].update(
                {
                    "page_number_drhp": ocr_text,
                    "facts": facts,
                    "queries": queries,
                }
            )
            page_doc = Pages.objects(company=company, page_number_pdf=pno).first()
            page_doc.page_content = pages_data[str(pno)]["page_content"]
            page_doc.page_number_drhp = ocr_text
            page_doc.facts = facts
            page_doc.queries = queries
            page_doc.save(update_qdrant=True)

            logger.info(f"Completed full processing for page {pno}")

    output = {pdf_name: pages_data}
    output_filename = f"{os.path.splitext(pdf_name)[0]}_pages.json"
    output_path = os.path.join(json_dir, output_filename)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    # try:
    #     shutil.rmtree(base_dir)
    #     logger.debug(f"Removed temporary directory: {images_dir}")
    # except OSError as e:
    #     logger.warning(f"Failed to remove temporary directory {images_dir}: {e}")

    # ---------------------------------------------------------------
    # STEP 3: Write final JSON to disk
    # ---------------------------------------------------------------

    logger.info(f"Successfully Processed PDF")
    return total_in, total_out


if __name__ == "__main__":
    process_pdf(
        "DRHPS/ASTONEA_LABS_LTD.pdf",
        "ASTONEA_LABS_LTD",
        dpi=200,
        threshold=245,
        max_workers=25,
    )
