import os
import logging
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
from mongoengine import (
    connect,
    Document,
    StringField,
    DateTimeField,
    ReferenceField,
    IntField,
    DoesNotExist,
    ListField,
)
from local_drhp_processor_final import LocalDRHPProcessor
from baml_client import b
from datetime import datetime, timedelta, timezone
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from qdrant_client import QdrantClient
import pytz
from azure_blob_utils import get_blob_storage


# Setup logging with IST timestamps
class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        ist = pytz.timezone("Asia/Kolkata")
        ct = datetime.fromtimestamp(record.created, tz=ist)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        return s


log_formatter = ISTFormatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler = logging.FileHandler("process_embed_upsert_drhp.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler],
    force=True,
)
logger = logging.getLogger("DRHP_Embed_Upsert")


# MongoEngine Models
class Company(Document):
    meta = {"db_alias": "core", "collection": "company"}
    name = StringField(required=True)
    corporate_identity_number = StringField(required=True, unique=True)
    drhp_file_url = StringField(required=True)
    website_link = StringField()
    created_at = DateTimeField(default=datetime.utcnow)


class Page(Document):
    meta = {"db_alias": "core", "collection": "pages"}
    company_id = ReferenceField(Company, required=True)
    page_number_pdf = IntField(required=True)
    page_number_drhp = IntField()
    page_content = StringField()


def validate_env():
    required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    logger.info("All required environment variables are set.")


def compute_pdf_hash(pdf_path):
    BUF_SIZE = 65536
    sha256 = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()


def get_or_create_company(company_details, pdf_path):
    unique_id = company_details.corporate_identity_number
    try:
        company_doc = Company.objects.get(corporate_identity_number=unique_id)
        logger.info(f"Company already exists in MongoDB: {company_doc.id}")
        return company_doc, False
    except DoesNotExist:
        try:
            company_doc = Company(
                name=company_details.name,
                corporate_identity_number=unique_id,
                drhp_file_url=pdf_path,
                website_link=company_details.website_link,
            ).save()
            logger.info(f"Company details saved to MongoDB: {company_doc.id}")
            return company_doc, True
        except Exception as e:
            logger.error(f"Failed to save company: {e}")
            raise


def save_page_safe(company_doc, page_no, page_info, saved_pages, failed_pages):
    try:
        # Check for duplicate page
        if Page.objects(company_id=company_doc, page_number_pdf=int(page_no)).first():
            logger.info(
                f"Page {page_no} already exists for company {company_doc.name}, skipping."
            )
            saved_pages.append(page_no)
            return
        page_number_drhp_val = page_info.get("page_number_drhp", None)
        # Handle empty strings, None, and other invalid values
        if (
            page_number_drhp_val is not None
            and page_number_drhp_val != ""
            and str(page_number_drhp_val).strip()
        ):
            try:
                page_number_drhp_val = int(page_number_drhp_val)
            except (ValueError, TypeError):
                logger.warning(
                    f"Could not convert page_number_drhp '{page_number_drhp_val}' to int for page {page_no}, setting to None"
                )
                page_number_drhp_val = None
        else:
            page_number_drhp_val = None
        Page(
            company_id=company_doc,
            page_number_pdf=int(page_no),
            page_number_drhp=page_number_drhp_val,
            page_content=page_info.get("page_content", ""),
        ).save()
        saved_pages.append(page_no)
    except Exception as e:
        logger.error(f"Failed to save page {page_no}: {e}")
        failed_pages.append(page_no)


def cleanup_company_and_pages(company_doc):
    try:
        Page.objects(company_id=company_doc).delete()
        company_doc.delete()
        logger.info(f"Rolled back company and pages for {company_doc.name}")
    except Exception as e:
        logger.error(f"Failed to clean up after error: {e}")


def qdrant_collection_exists(collection_name, qdrant_url):
    try:
        client = QdrantClient(url=qdrant_url)
        return collection_name in [c.name for c in client.get_collections().collections]
    except Exception as e:
        logger.error(f"Failed to check Qdrant collections: {e}")
        return False


def main():
    load_dotenv()
    # ---- Configuration (set your values here) ----
    PDF_PATH = r"C:\Users\himan\Downloads\1752053961291.pdf"  # Set your PDF path here
    MAX_WORKERS = 10  # Set your desired number of workers
    CLEANUP_JSON = True  # Set to True to delete extracted JSON after processing

    QDRANT_URL = os.getenv("QDRANT_URL")
    MONGODB_URI = os.getenv("MONGODB_URI")
    DB_NAME = os.getenv("DB_NAME", "DRHP_NOTES")

    # ====== ENV VALIDATION ======
    try:
        validate_env()
    except Exception as e:
        logger.error(f"[ENV VALIDATION ERROR] {e}")
        return

    # ====== MONGODB CONNECTION ======
    try:
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
    except Exception as e:
        logger.error(f"[MONGODB CONNECTION ERROR] {e}")
        return

    # ====== VALIDATION ======
    if not os.path.exists(PDF_PATH):
        logger.error(f"PDF file not found: {PDF_PATH}")
        return
    if MAX_WORKERS < 1 or MAX_WORKERS > 20:
        logger.error("MAX_WORKERS must be between 1 and 20")
        return

    logger.info(f"PDF Path: {PDF_PATH}")
    logger.info(f"Max Workers: {MAX_WORKERS}")
    logger.info(f"Qdrant URL: {QDRANT_URL}")
    logger.info(f"MongoDB URI: {MONGODB_URI}")
    logger.info(f"MongoDB DB Name: {DB_NAME}")

    # ====== Azure Blob Storage integration ======
    blob_storage = get_blob_storage()
    pdf_blob_url = None
    pdf_blob_name = None
    try:
        import uuid

        unique_id = str(uuid.uuid4())
        pdf_filename = os.path.basename(PDF_PATH)
        pdf_blob_name = f"pdfs/{unique_id}_{pdf_filename}"
        pdf_blob_url = blob_storage.upload_file(PDF_PATH, pdf_blob_name)
        logger.info(f"PDF uploaded to Azure Blob Storage: {pdf_blob_url}")
    except Exception as e:
        logger.error(f"Failed to upload input PDF to Azure Blob Storage: {e}")
        return

    # ====== PROCESSING ======
    start_time = time.time()
    try:
        pdf_hash = compute_pdf_hash(PDF_PATH)
        logger.info(f"PDF SHA256 hash: {pdf_hash}")
    except Exception as e:
        logger.error(f"[PDF HASH ERROR] {e}")
        return

    try:
        processor = LocalDRHPProcessor(
            qdrant_url=QDRANT_URL,
            collection_name=None,  # Will set after extracting company details
            max_workers=MAX_WORKERS,
            company_name=None,  # Not needed for processing
        )
    except Exception as e:
        logger.error(f"[PROCESSOR INIT ERROR] {e}")
        return

    # Download the PDF from blob storage for processing (if needed)
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
        blob_storage.download_file(pdf_blob_name, temp_file.name)
        temp_pdf_path = temp_file.name

    # Step 1: Process PDF (extract pages, TOC, etc.)
    try:
        json_path = processor.process_pdf_locally(temp_pdf_path, "TEMP_COMPANY")
        logger.info(f"PDF processed and extracted to: {json_path}")
    except Exception as e:
        logger.error(f"[PDF PROCESSING ERROR] {e}")
        return

    # Step 2: Extract company details using BAML from first 10 pages
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pdf_name = list(data.keys())[0]
        pages = data[pdf_name]
        logger.info(f"Fetched {len(pages)} pages from JSON.")
        # Concatenate first 10 pages for company details extraction
        first_pages_text = "\n".join(
            [
                pages[str(i)].get("page_content", "")
                for i in range(1, 11)
                if str(i) in pages
            ]
        )
        logger.info(
            f"Fetched first 10 pages' content for company extraction. Length: {len(first_pages_text)}"
        )
        company_details = b.ExtractCompanyDetails(first_pages_text)
        logger.info(f"Fetched company details: {company_details}")
        unique_id = company_details.corporate_identity_number
        if (
            not hasattr(company_details, "name")
            or not company_details.name
            or not unique_id
        ):
            logger.error(
                "BAML did not return a valid company name or unique identifier."
            )
            return
        # Check for duplicate in MongoDB
        if Company.objects(corporate_identity_number=unique_id).first():
            logger.info(
                f"Company with unique id {unique_id} already exists. Skipping MongoDB and Qdrant upsert."
            )
            if CLEANUP_JSON:
                try:
                    os.remove(json_path)
                    logger.info(f"Cleaned up extracted JSON: {json_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up JSON file: {e}")
            return
        try:
            company_doc, created = get_or_create_company(company_details, PDF_PATH)
            logger.info(f"Company document created: {company_doc.to_json()}")
        except Exception as e:
            logger.error(f"[COMPANY SAVE ERROR] {e}")
            return
    except Exception as e:
        logger.error(f"[COMPANY EXTRACTION ERROR] {e}")
        return

    # Step 3: Store pages in MongoDB (parallelized, no facts/queries)
    saved_pages = []
    failed_pages = []
    page_items = [(k, v) for k, v in pages.items() if k != "_metadata"]

    def is_int_str(s):
        try:
            int(s)
            return True
        except Exception:
            return False

    page_items = [(k, v) for k, v in page_items if is_int_str(k)]
    logger.info(f"Preparing to save {len(page_items)} pages to MongoDB.")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                save_page_safe, company_doc, k, v, saved_pages, failed_pages
            )
            for k, v in page_items
        ]
        for future in as_completed(futures):
            pass  # All error handling is inside save_page_safe
    logger.info(
        f"Saved {len(saved_pages)} pages, failed to save {len(failed_pages)} pages."
    )
    if failed_pages:
        logger.error(f"Failed pages: {failed_pages}")
        cleanup_company_and_pages(company_doc)
        return

    # Step 4: Upsert to Qdrant (embedding and storage, only if collection does not exist)
    qdrant_collection = f"drhp_notes_{company_details.name.replace(' ', '_')}"
    if qdrant_collection_exists(qdrant_collection, QDRANT_URL):
        logger.info(
            f"Qdrant collection {qdrant_collection} already exists. Skipping upsert."
        )
    else:
        try:
            processor.collection_name = qdrant_collection
            processor.upsert_pages_to_qdrant(
                json_path, company_details.name, str(company_doc.id)
            )
            logger.info(
                f"Embeddings upserted to Qdrant collection: {qdrant_collection}"
            )
        except Exception as e:
            logger.error(f"[QDRANT UPSERT ERROR] {e}")
            cleanup_company_and_pages(company_doc)
            return

    # Step 5: Optionally clean up JSON file
    if CLEANUP_JSON:
        try:
            os.remove(json_path)
            logger.info(f"Cleaned up extracted JSON: {json_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up JSON file: {e}")

    logger.info(
        "DRHP Processing, Extraction, Embedding, and Upsert Completed Successfully!"
    )
    logger.info(f"Company: {company_details.name}, Pages saved: {len(saved_pages)}")
    end_time = time.time()
    elapsed = end_time - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    logger.info(
        f"Total processing, embedding, and upsert time: {minutes} min {seconds} sec"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Script failed: {e}")
