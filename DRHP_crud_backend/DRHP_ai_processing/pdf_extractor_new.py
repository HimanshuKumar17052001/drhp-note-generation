import sys
import os
import logging
import pdfplumber
import fitz  # PyMuPDF
import numpy as np
import cv2
import base64
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("drhp_extractor.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def img_to_bytes(cv2_img):
    success, buf = cv2.imencode(".png", cv2_img)
    if not success:
        raise ValueError("Failed to encode image")
    return buf.tobytes()


def pdf_page_to_cv2_image(pdf_path, page_num, dpi=200):
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(dpi=dpi)
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            (pix.height, pix.width, pix.n)
        )
        if pix.n == 4:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
        else:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        return img_np
    except Exception as e:
        logger.error(f"Error converting PDF page {page_num} to image: {e}")
        raise


def extract_all_pages_local(pdf_path, company_name, dpi=200, max_workers=3):
    logger.info("Starting local page extraction...")
    base_dir = os.path.join(os.getcwd(), company_name)
    images_dir = os.path.join(base_dir, "temp_stripped_bottom_images")
    json_dir = os.path.join(base_dir, "temp_pages_json")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    pages_data = {}

    def process_page(idx):
        page_num = idx + 1
        try:
            # Extract text and tables
            with pdfplumber.open(pdf_path) as pdf:
                page = pdf.pages[idx]
                text = page.extract_text() or ""
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
            # Save bottom strip image
            cv2_img = pdf_page_to_cv2_image(pdf_path, page_num, dpi=dpi)
            img_bytes = img_to_bytes(cv2_img)
            img_path = os.path.join(images_dir, f"page_{page_num}.png")
            with open(img_path, "wb") as imgf:
                imgf.write(img_bytes)
            logger.info(f"Saved image for page {page_num}")
            return str(page_num), {"page_content": text, "image_path": img_path}
        except Exception as e:
            logger.error(f"Error processing page {page_num}: {e}")
            return str(page_num), {"page_content": "", "image_path": ""}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_page, idx) for idx in range(total_pages)]
        for future in as_completed(futures):
            pno, pdata = future.result()
            pages_data[pno] = pdata

    # Save all page data as JSON
    pdf_name = os.path.basename(pdf_path)
    output_json = os.path.join(json_dir, f"{os.path.splitext(pdf_name)[0]}_pages.json")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump({pdf_name: pages_data}, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved all page data to {output_json}")
    return output_json


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract all DRHP pages locally (no DB)"
    )
    parser.add_argument("pdf_path", help="Path to the DRHP PDF file")
    parser.add_argument("company_name", help="Company name (for output folder)")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for image extraction")
    parser.add_argument(
        "--max_workers", type=int, default=3, help="Number of parallel workers"
    )
    args = parser.parse_args()

    extract_all_pages_local(
        pdf_path=args.pdf_path,
        company_name=args.company_name,
        dpi=args.dpi,
        max_workers=args.max_workers,
    )
    print("Extraction complete!")
    print(
        f"Check the output folders: ./{args.company_name}/temp_stripped_bottom_images/ and ./{args.company_name}/temp_pages_json/"
    )
