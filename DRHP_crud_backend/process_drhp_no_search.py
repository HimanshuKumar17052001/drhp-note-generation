import os
import logging
import time
from pathlib import Path
from dotenv import load_dotenv
from local_drhp_processor_final import LocalDRHPProcessor


def main():
    """
    Script to process, extract, embed, and upsert a DRHP PDF to Qdrant WITHOUT any search or AI answer logic.
    """
    load_dotenv()
    print("🚀 Starting DRHP Processing (No Search)")
    print("=" * 60)

    # ====== CONFIGURATION ======
    PDF_PATH = r"C:\Users\himan\Downloads\1750419007609_820.pdf"  # CHANGE THIS
    COMPANY_NAME = "CAPILLARY TECHNOLOGIES INDIA LIMITED"  # CHANGE THIS
    QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_COLLECTION = f"drhp_notes_{COMPANY_NAME}"  # CHANGE IF NEEDED
    MAX_WORKERS = 20
    FORCE_REPROCESS = False

    # ====== VALIDATION ======
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"PDF file not found: {PDF_PATH}")
    if not COMPANY_NAME or not COMPANY_NAME.strip():
        raise ValueError("Company name cannot be empty")
    if MAX_WORKERS < 1 or MAX_WORKERS > 20:
        raise ValueError("MAX_WORKERS must be between 1 and 20")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable is required")

    print("✅ All inputs validated successfully")
    print(f"📄 PDF Path: {PDF_PATH}")
    print(f"🏢 Company: {COMPANY_NAME}")
    print(f"🔧 Max Workers: {MAX_WORKERS}")
    print(f"🗄️ Qdrant URL: {QDRANT_URL}")
    print(f"📊 Qdrant Collection: {QDRANT_COLLECTION}")
    print("=" * 60)

    # ====== PROCESSING ======
    processor = LocalDRHPProcessor(
        qdrant_url=QDRANT_URL,
        collection_name=QDRANT_COLLECTION,
        max_workers=MAX_WORKERS,
        company_name=COMPANY_NAME,
    )

    # Step 1: Process PDF (extract pages, TOC, etc.)
    json_path = processor.process_pdf_locally(PDF_PATH, COMPANY_NAME)
    print(f"✅ PDF processed and extracted to: {json_path}")

    # Step 2: Upsert to Qdrant (embedding and storage)
    processor.upsert_pages_to_qdrant(json_path, COMPANY_NAME)
    print(f"✅ Embeddings upserted to Qdrant collection: {QDRANT_COLLECTION}")

    print("=" * 60)
    print("🎉 DRHP Processing (No Search) Completed Successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
