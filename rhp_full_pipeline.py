import os
import sys
import logging
import glob
import time
import json
import hashlib
from datetime import datetime
from dotenv import load_dotenv
from mongoengine import (
    connect,
    Document,
    StringField,
    DateTimeField,
    IntField,
    ListField,
    ReferenceField,
    DoesNotExist,
    ObjectIdField,  # <-- add this
)
from pathlib import Path
import pytz

# Add DRHP_crud_backend to sys.path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

from DRHP_crud_backend.local_drhp_processor_final import LocalDRHPProcessor
from DRHP_crud_backend.baml_client import b
from DRHP_crud_backend.DRHP_ai_processing.note_checklist_processor import (
    DRHPNoteChecklistProcessor,
)
from qdrant_client import QdrantClient


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


log_formatter = ISTFormatter(fmt="%(asctime)s - %(levelname)s - %(message)s")
file_handler = logging.FileHandler("drhp_full_pipeline.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logging.basicConfig(
    level=logging.INFO, handlers=[file_handler, console_handler], force=True
)
logger = logging.getLogger("RHP_Full_Pipeline")


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
    page_number_drhp = StringField()
    page_content = StringField()


class ChecklistOutput(Document):
    meta = {"db_alias": "core", "collection": "checklist_outputs"}
    company_id = ReferenceField(Company, required=True)
    checklist_name = StringField(required=True)
    row_index = IntField(required=True)
    topic = StringField()
    section = StringField()
    ai_prompt = StringField()
    ai_output = StringField()
    citations = ListField(StringField())
    commentary = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)


class FinalMarkdown(Document):
    meta = {"db_alias": "core", "collection": "final_markdown"}
    company_id = ReferenceField(Company, required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)


# Utility functions
def validate_env():
    required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "RHP_MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    logger.info("All required environment variables are set.")


def qdrant_collection_exists(collection_name, qdrant_url):
    try:
        client = QdrantClient(url=qdrant_url)
        return collection_name in [c.name for c in client.get_collections().collections]
    except Exception as e:
        logger.error(f"Failed to check Qdrant collections: {e}")
        return False


def get_latest_checklist():
    checklist_dir = os.path.join(
        os.path.dirname(__file__), "DRHP_crud_backend", "Checklists"
    )
    files = glob.glob(os.path.join(checklist_dir, "*.xlsx"))
    if not files:
        raise FileNotFoundError(
            "No checklist Excel files found in Checklists directory."
        )
    latest = max(files, key=os.path.getmtime)
    logger.info(f"Using latest checklist: {latest}")
    return latest


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
                website_link=getattr(company_details, "website_link", None),
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
        Page(
            company_id=company_doc,
            page_number_pdf=int(page_no),
            page_number_drhp=page_info.get("page_number_drhp", ""),
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


def checklist_exists(company_id, checklist_name):
    if not isinstance(company_id, Company):
        raise ValueError("company_id must be a Company instance, not a string.")
    return (
        ChecklistOutput.objects(
            company_id=company_id, checklist_name=checklist_name
        ).first()
        is not None
    )


def markdown_exists(company_id):
    if not isinstance(company_id, Company):
        raise ValueError("company_id must be a Company instance, not a string.")
    return FinalMarkdown.objects(company_id=company_id).first() is not None


def generate_markdown_for_company(company_id, company_name):
    if not isinstance(company_id, Company):
        raise ValueError("company_id must be a Company instance, not a string.")
    rows = (
        ChecklistOutput.objects(company_id=company_id)
        .order_by("row_index")
        .only("topic", "ai_output", "commentary", "row_index")
    )
    md_lines = []
    for row in rows:
        topic = row.topic or ""
        ai_output = row.ai_output or ""
        commentary = row.commentary or ""
        heading_md = f"**{topic}**" if topic else ""
        commentary_md = (
            f'<span style="font-size:10px;"><i>AI Commentary : {commentary}</i></span>'
            if commentary
            else ""
        )
        md_lines.append(f"{heading_md}\n\n{ai_output}\n\n{commentary_md}\n\n")
    markdown = "".join(md_lines)
    return markdown


def save_final_markdown(company_id, company_name, markdown):
    if not isinstance(company_id, Company):
        raise ValueError("company_id must be a Company instance, not a string.")
    FinalMarkdown.objects(company_id=company_id).update_one(
        set__company_name=company_name, set__markdown=markdown, upsert=True
    )
    logger.info(
        f"Saved markdown for {company_name} ({company_id}) to final_markdown collection."
    )


def delete_company_and_related_data(company_doc, qdrant_url):
    """
    Delete company, pages, checklist outputs, and markdown from MongoDB,
    and delete the corresponding Qdrant collection. Keeps MongoDB and Qdrant in sync.
    """
    try:
        # Delete pages
        Page.objects(company_id=company_doc).delete()
        # Delete checklist outputs
        ChecklistOutput.objects(company_id=company_doc).delete()
        # Delete markdown
        FinalMarkdown.objects(company_id=company_doc).delete()
        # Delete company
        company_doc.delete()
        # Delete Qdrant collection
        qdrant_collection = f"drhp_notes_{company_doc.name.replace(' ', '_').upper()}"
        try:
            client = QdrantClient(url=qdrant_url)
            if qdrant_collection in [
                c.name for c in client.get_collections().collections
            ]:
                client.delete_collection(collection_name=qdrant_collection)
                logger.info(f"Deleted Qdrant collection: {qdrant_collection}")
        except Exception as qe:
            logger.error(f"Failed to delete Qdrant collection: {qe}")
        logger.info(f"Deleted company and all related data for {company_doc.name}")
    except Exception as e:
        logger.error(f"Failed to delete company and related data: {e}")


def rerun_checklist_for_company(company_doc, checklist_path, qdrant_url):
    """
    Delete existing checklist outputs for the company and re-run the checklist processor,
    overwriting the outputs. Used for frontend 'Re-run Checklist' option.
    """
    try:
        # Delete existing checklist outputs
        ChecklistOutput.objects(company_id=company_doc).delete()
        logger.info(f"Deleted existing checklist outputs for {company_doc.name}")
        # Re-run checklist processor
        qdrant_collection = f"drhp_notes_{company_doc.name.replace(' ', '_').upper()}"
        checklist_name = os.path.basename(checklist_path)
        note_processor = DRHPNoteChecklistProcessor(
            checklist_path, qdrant_collection, str(company_doc.id), checklist_name
        )
        note_processor.process()
        logger.info(f"Checklist re-run and outputs updated for {company_doc.name}")
    except Exception as e:
        logger.error(f"Failed to re-run checklist for {company_doc.name}: {e}")


# Use checklist from local Checklists directory
CHECKLIST_PATH = os.path.join(
    os.path.dirname(__file__),
    "DRHP_crud_backend",
    "Checklists",
    "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
)


def main(pdf_path):
    load_dotenv()
    try:
        validate_env()
    except Exception as e:
        logger.error(f"[ENV VALIDATION ERROR] {e}")
        sys.exit(1)
    QDRANT_URL = os.getenv("QDRANT_URL")
    MONGODB_URI = os.getenv("MONGODB_URI")
    DB_NAME = os.getenv("DB_NAME", "DRHP_NOTES")
    try:
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
    except Exception as e:
        logger.error(f"[MONGODB CONNECTION ERROR] {e}")
        sys.exit(1)
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        sys.exit(1)
    # Step 1: Extract company details from PDF (first 10 pages)
    try:
        processor = LocalDRHPProcessor(
            qdrant_url=QDRANT_URL,
            collection_name=None,
            max_workers=5,
            company_name=None,
        )
        json_path = processor.process_pdf_locally(pdf_path, "TEMP_COMPANY")
        logger.info(f"PDF processed and extracted to: {json_path}")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pdf_name = list(data.keys())[0]
        pages = data[pdf_name]
        first_pages_text = "\n".join(
            [
                pages[str(i)].get("page_content", "")
                for i in range(1, 11)
                if str(i) in pages
            ]
        )
        company_details = b.ExtractCompanyDetails(first_pages_text)
        logger.info(f"Fetched company details: {company_details}")
        unique_id = company_details.corporate_identity_number
        company_name = company_details.name
        if not company_name or not unique_id:
            logger.error(
                "BAML did not return a valid company name or unique identifier."
            )
            sys.exit(1)
    except Exception as e:
        logger.error(f"[COMPANY EXTRACTION ERROR] {e}")
        sys.exit(1)
    # Step 2: Check for duplicates in MongoDB and Qdrant
    qdrant_collection = f"drhp_notes_{company_name.replace(' ', '_').upper()}"
    company_doc = Company.objects(corporate_identity_number=unique_id).first()
    checklist_path = CHECKLIST_PATH
    checklist_name = os.path.basename(checklist_path)
    checklist_done = (
        checklist_exists(company_doc, checklist_name) if company_doc else False
    )
    markdown_done = markdown_exists(company_doc) if company_doc else False
    qdrant_done = qdrant_collection_exists(qdrant_collection, QDRANT_URL)
    pages_done = (
        company_doc and Page.objects(company_id=company_doc).first() is not None
    )
    # If everything exists, return markdown
    if company_doc and qdrant_done and checklist_done and markdown_done and pages_done:
        logger.info("All data already exists. Returning final markdown.")
        markdown = FinalMarkdown.objects(company_id=company_doc).first().markdown
        print("\n--- Markdown Preview ---\n")
        print(markdown[:])
        return markdown
    # If company does not exist, create it
    if not company_doc:
        company_doc, _ = get_or_create_company(company_details, pdf_path)
    # If pages do not exist, upsert them
    if not pages_done:
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
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(
                    save_page_safe, company_doc, k, v, saved_pages, failed_pages
                )
                for k, v in page_items
            ]
            for future in as_completed(futures):
                pass
        logger.info(
            f"Saved {len(saved_pages)} pages, failed to save {len(failed_pages)} pages."
        )
        if failed_pages:
            logger.error(f"Failed pages: {failed_pages}")
            cleanup_company_and_pages(company_doc)
            sys.exit(1)
    # If Qdrant collection does not exist, upsert
    if not qdrant_done:
        try:
            processor.collection_name = qdrant_collection
            processor.upsert_pages_to_qdrant(
                json_path, company_name, str(company_doc.id)
            )
            logger.info(
                f"Embeddings upserted to Qdrant collection: {qdrant_collection}"
            )
        except Exception as e:
            logger.error(f"[QDRANT UPSERT ERROR] {e}")
            cleanup_company_and_pages(company_doc)
            sys.exit(1)
    # If checklist not done, process checklist
    if not checklist_done:
        try:
            note_processor = DRHPNoteChecklistProcessor(
                checklist_path, qdrant_collection, str(company_doc.id), checklist_name
            )
            note_processor.process()
            logger.info("Checklist processing complete.")
        except Exception as e:
            logger.error(f"[CHECKLIST PROCESSING ERROR] {e}")
            sys.exit(1)
    # Generate and save markdown
    try:
        markdown = generate_markdown_for_company(company_doc, company_name)
        save_final_markdown(company_doc, company_name, markdown)
        logger.info("Final markdown generated and saved.")
        print("\n--- Markdown Preview ---\n")
        print(markdown[:])
        return markdown
    except Exception as e:
        logger.error(f"[MARKDOWN GENERATION ERROR] {e}")
        sys.exit(1)
    finally:
        # Cleanup JSON
        try:
            os.remove(json_path)
            logger.info(f"Cleaned up extracted JSON: {json_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up JSON file: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python drhp_full_pipeline.py <path_to_pdf>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    main(pdf_path)
