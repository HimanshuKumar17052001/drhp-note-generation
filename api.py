import os
import sys
import asyncio
import json
import tempfile
import logging
import time
import base64
import shutil
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Path,
    BackgroundTasks,
    Query,
)
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mongoengine import connect, disconnect, DoesNotExist

# Add the backend directory to the Python path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

# Import DRHP pipeline components
from DRHP_crud_backend.local_drhp_processor_final import LocalDRHPProcessor
from DRHP_crud_backend.baml_client import b
from DRHP_crud_backend.DRHP_ai_processing.note_checklist_processor import (
    DRHPNoteChecklistProcessor,
)
from qdrant_client import QdrantClient

# Import PDF generation components
import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DRHP_API")

# --- FastAPI App Initialization ---
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    try:
        validate_env()
        connect_to_db()
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

    yield

    # Shutdown
    try:
        disconnect(alias="core")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


app = FastAPI(
    title="DRHP IPO Notes Generator API",
    description="API to manage and process DRHP documents for IPO note generation.",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
CHECKLIST_PATH = os.path.join(
    os.path.dirname(__file__),
    "DRHP_crud_backend",
    "Checklists",
    "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
)
QDRANT_URL = os.getenv("QDRANT_URL")
MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")


# --- Pydantic Models for API Data Validation ---
class CompanyModel(BaseModel):
    id: str
    name: str
    uin: str
    uploadDate: str
    status: str
    hasMarkdown: bool


class ReportRequest(BaseModel):
    markdown_content: str
    company_name: str
    output_filename: str


class ProcessingStatus(BaseModel):
    status: str
    message: str
    progress: Optional[float] = None
    current_step: Optional[str] = None


class CompanyUpdateRequest(BaseModel):
    name: Optional[str] = None
    website_link: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    filters: Optional[Dict[str, Any]] = None


# --- MongoDB Models ---
from mongoengine import (
    Document,
    StringField,
    DateTimeField,
    IntField,
    ListField,
    ReferenceField,
    ObjectIdField,
)


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
    company_id = StringField(required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)


# --- Utility Functions ---
def validate_env():
    """Validate that all required environment variables are set."""
    required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "DRHP_MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    logger.info("All required environment variables are set.")


def connect_to_db():
    """Connect to MongoDB database."""
    try:
        # Disconnect if already connected with this alias
        disconnect(alias="core")
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
    except Exception as e:
        logger.error(f"MongoDB connection error: {e}")
        raise


def qdrant_collection_exists(collection_name, qdrant_url):
    """Check if a Qdrant collection exists."""
    try:
        client = QdrantClient(url=qdrant_url)
        return collection_name in [c.name for c in client.get_collections().collections]
    except Exception as e:
        logger.error(f"Failed to check Qdrant collections: {e}")
        return False


def get_or_create_company(company_details, pdf_path):
    """Get existing company or create new one."""
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
    """Safely save a page to MongoDB."""
    try:
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
    """Clean up company and pages on error."""
    try:
        Page.objects(company_id=company_doc).delete()
        company_doc.delete()
        logger.info(f"Rolled back company and pages for {company_doc.name}")
    except Exception as e:
        logger.error(f"Failed to clean up after error: {e}")


def checklist_exists(company_id, checklist_name):
    """Check if checklist outputs exist for a company."""
    if not isinstance(company_id, Company):
        raise ValueError("company_id must be a Company instance, not a string.")
    return (
        ChecklistOutput.objects(
            company_id=company_id, checklist_name=checklist_name
        ).first()
        is not None
    )


def markdown_exists(company_id):
    """Check if markdown exists for a company."""
    try:
        company_id_str = str(company_id)
        return FinalMarkdown.objects(company_id=company_id_str).first() is not None
    except Exception:
        return False


def generate_markdown_for_company(company_id, company_name):
    """Generate markdown from checklist outputs."""
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
    """Save final markdown to database."""
    company_id_str = str(
        company_id.id if isinstance(company_id, Company) else company_id
    )
    FinalMarkdown.objects(company_id=company_id_str).update_one(
        set__company_name=company_name, set__markdown=markdown, upsert=True
    )
    logger.info(
        f"Saved markdown for {company_name} ({company_id_str}) to final_markdown collection."
    )


def delete_company_and_related_data(company_doc, qdrant_url):
    """Delete company and all related data from MongoDB and Qdrant."""
    try:
        Page.objects(company_id=company_doc).delete()
        ChecklistOutput.objects(company_id=company_doc).delete()
        FinalMarkdown.objects(company_id=company_doc).delete()
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


# --- PDF Generation Functions ---
def load_image_base64(path):
    """Load image and convert to base64 data URL."""
    try:
        with open(path, "rb") as f:
            return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
    except Exception as e:
        logger.warning(f"Failed to load image {path}: {e}")
        return None


def render_template(env, template_name, context):
    """Render Jinja2 template with given context."""
    return env.get_template(template_name).render(context)


def generate_ipo_notes_pdf(company_name, markdown_content, output_dir="output"):
    """Generate professional IPO Notes PDF using Jinja2 templates and WeasyPrint."""
    try:
        os.makedirs(output_dir, exist_ok=True)

        env = Environment(loader=FileSystemLoader("templates"))
        html_body = markdown.markdown(
            markdown_content, extensions=["tables", "fenced_code"]
        )

        # Load images (with fallbacks)
        axis_logo_data = load_image_base64("assets/axis_logo.png")
        company_logo_data = load_image_base64("assets/Pine Labs_logo.png")
        front_header_data = load_image_base64("assets/front_header.png")

        # Try to load company-specific logo if it exists
        company_logo_path = f"assets/{company_name.replace(' ', '_')}_logo.png"
        if os.path.exists(company_logo_path):
            company_logo_data = load_image_base64(company_logo_path)

        context = {
            "company_name": company_name.upper(),
            "document_date": datetime.today().strftime("%B %Y"),
            "company_logo_data": company_logo_data,
            "axis_logo_data": axis_logo_data,
            "front_header_data": front_header_data,
            "content": html_body,
        }

        front_html = render_template(env, "front_page.html", context)
        content_html = render_template(env, "content_page.html", context)
        full_html = front_html + content_html

        safe_company_name = (
            company_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
        )
        pdf_filename = f"{safe_company_name}_IPO_Notes.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)

        html_doc = HTML(string=full_html, base_url=".")
        css_doc = CSS(filename="styles/styles.css")

        html_doc.write_pdf(pdf_path, stylesheets=[css_doc])

        logger.info(f"✅ PDF generated successfully: {pdf_path}")
        return pdf_path

    except Exception as e:
        logger.error(f"❌ Failed to generate PDF: {e}")
        raise


# --- Pipeline Functions ---
def run_full_pipeline(pdf_path, status_callback=None):
    """Run the full DRHP processing pipeline."""
    try:
        if status_callback:
            status_callback(
                {"status": "started", "message": "Starting DRHP processing..."}
            )

        # Step 1: Extract company details from PDF
        if status_callback:
            status_callback(
                {
                    "status": "processing",
                    "message": "Extracting company details...",
                    "progress": 10,
                }
            )

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
        company_name = company_details.name
        unique_id = company_details.corporate_identity_number

        if not company_name or not unique_id:
            raise Exception("Could not extract company details from PDF")

        # Step 2: Check for existing company
        company_doc = Company.objects(corporate_identity_number=unique_id).first()

        if company_doc:
            if markdown_exists(company_doc):
                if status_callback:
                    status_callback(
                        {
                            "status": "completed",
                            "message": "Company already processed",
                            "progress": 100,
                        }
                    )
                return {"company_id": str(company_doc.id), "status": "already_exists"}

        # Create new company if doesn't exist
        if not company_doc:
            company_doc, _ = get_or_create_company(company_details, pdf_path)

        if status_callback:
            status_callback(
                {
                    "status": "processing",
                    "message": "Saving pages to database...",
                    "progress": 30,
                }
            )

        # Step 3: Save pages to MongoDB
        saved_pages = []
        failed_pages = []
        page_items = [(k, v) for k, v in pages.items() if k != "_metadata"]
        page_items = [(k, v) for k, v in page_items if k.isdigit()]

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

        if failed_pages:
            raise Exception(f"Failed to save pages: {failed_pages}")

        if status_callback:
            status_callback(
                {
                    "status": "processing",
                    "message": "Indexing content for search...",
                    "progress": 50,
                }
            )

        # Step 4: Upsert to Qdrant
        qdrant_collection = f"drhp_notes_{company_name.replace(' ', '_').upper()}"
        processor.collection_name = qdrant_collection
        processor.upsert_pages_to_qdrant(json_path, company_name, str(company_doc.id))

        if status_callback:
            status_callback(
                {
                    "status": "processing",
                    "message": "Processing AI checklist...",
                    "progress": 70,
                }
            )

        # Step 5: Process checklist
        checklist_name = os.path.basename(CHECKLIST_PATH)
        note_processor = DRHPNoteChecklistProcessor(
            CHECKLIST_PATH, qdrant_collection, str(company_doc.id), checklist_name
        )
        note_processor.process()

        if status_callback:
            status_callback(
                {
                    "status": "processing",
                    "message": "Generating final notes...",
                    "progress": 90,
                }
            )

        # Step 6: Generate and save markdown
        markdown = generate_markdown_for_company(company_doc, company_name)
        save_final_markdown(company_doc, company_name, markdown)

        # Step 7: Generate PDF
        try:
            pdf_path = generate_ipo_notes_pdf(company_name, markdown)
            if status_callback:
                status_callback(
                    {
                        "status": "completed",
                        "message": f"PDF generated: {pdf_path}",
                        "progress": 100,
                    }
                )
        except Exception as pdf_error:
            logger.error(f"PDF generation failed: {pdf_error}")
            if status_callback:
                status_callback(
                    {
                        "status": "completed",
                        "message": "Processing completed (PDF generation failed)",
                        "progress": 100,
                    }
                )

        # Cleanup
        try:
            os.remove(json_path)
        except Exception as e:
            logger.warning(f"Failed to clean up JSON file: {e}")

        return {"company_id": str(company_doc.id), "status": "completed"}

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        if status_callback:
            status_callback({"status": "error", "message": str(e)})
        raise


def rerun_pipeline_for_company(company_id, status_callback=None):
    """Re-run pipeline for an existing company."""
    try:
        company_doc = Company.objects.get(id=company_id)

        if status_callback:
            status_callback(
                {"status": "processing", "message": "Deleting existing data..."}
            )

        # Delete existing data
        ChecklistOutput.objects(company_id=company_doc).delete()
        FinalMarkdown.objects(company_id=company_doc).delete()

        if status_callback:
            status_callback(
                {"status": "processing", "message": "Re-processing checklist..."}
            )

        # Re-run checklist
        qdrant_collection = f"drhp_notes_{company_doc.name.replace(' ', '_').upper()}"
        checklist_name = os.path.basename(CHECKLIST_PATH)
        note_processor = DRHPNoteChecklistProcessor(
            CHECKLIST_PATH, qdrant_collection, str(company_doc.id), checklist_name
        )
        note_processor.process()

        if status_callback:
            status_callback(
                {"status": "processing", "message": "Generating new markdown..."}
            )

        # Generate new markdown
        markdown = generate_markdown_for_company(company_doc, company_doc.name)
        save_final_markdown(company_doc, company_doc.name, markdown)

        # Generate new PDF
        try:
            pdf_path = generate_ipo_notes_pdf(company_doc.name, markdown)
            if status_callback:
                status_callback(
                    {
                        "status": "completed",
                        "message": f"Regeneration completed. PDF: {pdf_path}",
                    }
                )
        except Exception as pdf_error:
            logger.error(f"PDF generation failed: {pdf_error}")
            if status_callback:
                status_callback(
                    {
                        "status": "completed",
                        "message": "Regeneration completed (PDF generation failed)",
                    }
                )

        return {"status": "completed"}

    except Exception as e:
        logger.error(f"Regeneration failed: {e}")
        if status_callback:
            status_callback({"status": "error", "message": str(e)})
        raise


def get_all_companies_with_status():
    """Get all companies with their processing status."""
    companies = Company.objects().order_by("-created_at")
    result = []

    for company in companies:
        markdown_done = markdown_exists(company)
        result.append(
            CompanyModel(
                id=str(company.id),
                name=company.name,
                uin=company.corporate_identity_number,
                uploadDate=company.created_at.isoformat(),
                status="completed" if markdown_done else "processing",
                hasMarkdown=markdown_done,
            )
        )

    return result


def get_final_markdown(company_id):
    """Get final markdown for a company."""
    try:
        company_id_str = str(company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company_id_str).first()
        if markdown_doc:
            return markdown_doc.markdown
        return None
    except Exception as e:
        logger.error(f"Error in get_final_markdown: {e}")
        return None


def delete_company_and_all_data(company_id):
    """Delete company and all its data."""
    try:
        company_doc = Company.objects.get(id=company_id)
        delete_company_and_related_data(company_doc, QDRANT_URL)
        return True
    except DoesNotExist:
        return False


# --- API Endpoints ---


@app.get("/", summary="Health Check")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "message": "DRHP IPO Notes Generator API is running"}


@app.post("/companies/", summary="Upload and Process DRHP PDF")
async def upload_and_process_drhp(file: UploadFile = File(...)):
    """Accepts a DRHP PDF, processes it through the full pipeline, and streams real-time status updates."""
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400, detail="Invalid file type. Please upload a PDF."
        )

    # Save the uploaded file to a temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(await file.read())
        temp_pdf_path = tmp.name

    async def event_stream():
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_event_loop()

            future = loop.run_in_executor(
                None, run_full_pipeline, temp_pdf_path, queue.put_nowait
            )

            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=600)
                    if update is None:
                        break
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Processing timed out.'})}\n\n"
                    break

            await future

        except Exception as e:
            error_message = f"An unexpected error occurred: {str(e)}"
            yield f"data: {json.dumps({'status': 'error', 'message': error_message})}\n\n"
        finally:
            # Clean up the temporary file
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/companies/", response_model=List[CompanyModel], summary="List All Companies")
def get_all_companies():
    """Retrieves a list of all companies from the database, along with their processing status."""
    try:
        companies = get_all_companies_with_status()
        return companies
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve companies: {e}"
        )


@app.get(
    "/companies/{company_id}/markdown",
    response_class=JSONResponse,
    summary="Get Company's Final Markdown",
)
def get_company_markdown(
    company_id: str = Path(..., description="The MongoDB ID of the company.")
):
    """Fetches the final generated markdown report for a specific company."""
    try:
        markdown_content = get_final_markdown(company_id)
        if markdown_content is None:
            raise HTTPException(
                status_code=404, detail="Markdown not found for this company."
            )
        return JSONResponse(content={"markdown": markdown_content})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get markdown: {e}")


@app.get(
    "/companies/{company_id}", response_model=CompanyModel, summary="Get Company by ID"
)
def get_company_by_id(company_id: str):
    """Get a specific company by its MongoDB ID."""
    try:
        company = Company.objects.get(id=company_id)
        markdown_done = markdown_exists(company)
        return CompanyModel(
            id=str(company.id),
            name=company.name,
            uin=company.corporate_identity_number,
            uploadDate=company.created_at.isoformat(),
            status="completed" if markdown_done else "processing",
            hasMarkdown=markdown_done,
        )
    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get company: {e}")


@app.post(
    "/companies/{company_id}/regenerate", summary="Regenerate IPO Note for a Company"
)
async def regenerate_company_report(
    company_id: str = Path(..., description="The MongoDB ID of the company.")
):
    """Deletes existing checklist outputs and re-runs the AI processing steps to generate a new IPO note."""

    async def event_stream():
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_event_loop()

            future = loop.run_in_executor(
                None, rerun_pipeline_for_company, company_id, queue.put_nowait
            )

            while True:
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=600)
                    if update is None:
                        break
                    yield f"data: {json.dumps(update)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'status': 'error', 'message': 'Regeneration timed out.'})}\n\n"
                    break

            await future

        except Exception as e:
            error_message = (
                f"An unexpected error occurred during regeneration: {str(e)}"
            )
            yield f"data: {json.dumps({'status': 'error', 'message': error_message})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete(
    "/companies/{company_id}",
    status_code=204,
    summary="Delete a Company and All Its Data",
)
def delete_company(
    company_id: str = Path(..., description="The MongoDB ID of the company.")
):
    """Deletes a company and all its associated data from MongoDB and Qdrant."""
    try:
        success = delete_company_and_all_data(company_id)
        if not success:
            raise HTTPException(status_code=404, detail="Company not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete company: {e}")
    return None


@app.post(
    "/generate-report-pdf/",
    response_class=FileResponse,
    summary="Generate PDF from Markdown",
)
def create_report_pdf(request: ReportRequest):
    """Takes markdown content and other details, and returns a generated PDF file."""
    try:
        pdf_path = generate_ipo_notes_pdf(
            company_name=request.company_name, markdown_content=request.markdown_content
        )

        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=request.output_filename,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate PDF report: {e}"
        )


# --- Additional Endpoints for UI Features ---


@app.get(
    "/companies/{company_id}/status",
    response_model=ProcessingStatus,
    summary="Get Company Processing Status",
)
def get_company_status(company_id: str):
    """Get detailed processing status for a company."""
    try:
        company = Company.objects.get(id=company_id)

        # Check what data exists
        pages_done = Page.objects(company_id=company).first() is not None
        qdrant_collection = f"drhp_notes_{company.name.replace(' ', '_').upper()}"
        qdrant_done = qdrant_collection_exists(qdrant_collection, QDRANT_URL)
        checklist_done = checklist_exists(company, os.path.basename(CHECKLIST_PATH))
        markdown_done = markdown_exists(company)

        # Calculate progress
        total_steps = 4
        completed_steps = sum([pages_done, qdrant_done, checklist_done, markdown_done])
        progress = (completed_steps / total_steps) * 100 if total_steps > 0 else 0

        # Determine current step
        if markdown_done:
            current_step = "completed"
        elif checklist_done:
            current_step = "markdown_generation"
        elif qdrant_done:
            current_step = "checklist_processing"
        elif pages_done:
            current_step = "qdrant_upsert"
        else:
            current_step = "pages_saved"

        return ProcessingStatus(
            status="completed" if markdown_done else "processing",
            message=f"Step: {current_step}",
            progress=progress,
            current_step=current_step,
        )

    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {e}")


@app.put(
    "/companies/{company_id}",
    response_model=CompanyModel,
    summary="Update Company Details",
)
def update_company(company_id: str, update_data: CompanyUpdateRequest):
    """Update company details."""
    try:
        company = Company.objects.get(id=company_id)

        if update_data.name is not None:
            company.name = update_data.name
        if update_data.website_link is not None:
            company.website_link = update_data.website_link

        company.save()

        markdown_done = markdown_exists(company)
        return CompanyModel(
            id=str(company.id),
            name=company.name,
            uin=company.corporate_identity_number,
            uploadDate=company.created_at.isoformat(),
            status="completed" if markdown_done else "processing",
            hasMarkdown=markdown_done,
        )

    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update company: {e}")


@app.post("/companies/bulk-delete", summary="Bulk Delete Companies")
def bulk_delete_companies(company_ids: List[str]):
    """Bulk delete multiple companies."""
    try:
        deleted_count = 0
        failed_deletions = []

        for company_id in company_ids:
            try:
                success = delete_company_and_all_data(company_id)
                if success:
                    deleted_count += 1
                else:
                    failed_deletions.append(
                        {"company_id": company_id, "error": "Company not found"}
                    )
            except Exception as e:
                failed_deletions.append({"company_id": company_id, "error": str(e)})

        return {
            "message": f"Bulk deletion completed",
            "deleted_count": deleted_count,
            "failed_deletions": failed_deletions,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to bulk delete: {e}")


@app.post("/search", summary="Search Companies")
def search_companies(search_request: SearchRequest):
    """Search companies with filters."""
    try:
        query = search_request.query.lower()
        filters = search_request.filters or {}

        companies_query = Company.objects()

        if query:
            companies_query = companies_query.filter(
                name__icontains=query
            ) | companies_query.filter(corporate_identity_number__icontains=query)

        if filters.get("processing_status"):
            # Note: This would need a processing_status field in Company model
            pass

        if filters.get("date_from"):
            companies_query = companies_query.filter(
                created_at__gte=datetime.fromisoformat(filters["date_from"])
            )

        if filters.get("date_to"):
            companies_query = companies_query.filter(
                created_at__lte=datetime.fromisoformat(filters["date_to"])
            )

        companies = companies_query.order_by("-created_at")
        total_count = companies.count()

        if filters.get("limit"):
            companies = companies[: filters["limit"]]

        return {
            "companies": [
                CompanyModel(
                    id=str(company.id),
                    name=company.name,
                    uin=company.corporate_identity_number,
                    uploadDate=company.created_at.isoformat(),
                    status="completed" if markdown_exists(company) else "processing",
                    hasMarkdown=markdown_exists(company),
                )
                for company in companies
            ],
            "total_count": total_count,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search companies: {e}")


@app.post("/upload-company-logo/", summary="Upload Company Logo")
def upload_company_logo(company_id: str, file: UploadFile = File(...)):
    """Upload company logo for a specific company."""
    try:
        company = Company.objects.get(id=company_id)

        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image files are allowed")

        logo_dir = Path(__file__).parent / "static" / "logos"
        logo_dir.mkdir(parents=True, exist_ok=True)

        logo_path = logo_dir / f"{company_id}_logo.png"
        with open(logo_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return {"message": f"Company logo uploaded successfully for {company.name}"}

    except DoesNotExist:
        raise HTTPException(status_code=404, detail="Company not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload logo: {e}")


@app.post("/upload-entity-logo/", summary="Upload Entity Logo")
def upload_entity_logo(file: UploadFile = File(...)):
    """Upload entity/axis logo for global use."""
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image files are allowed")

        logo_dir = Path(__file__).parent / "static" / "logos"
        logo_dir.mkdir(parents=True, exist_ok=True)

        logo_path = logo_dir / "entity_logo.png"
        with open(logo_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        return {"message": "Entity logo uploaded successfully"}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to upload entity logo: {e}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
