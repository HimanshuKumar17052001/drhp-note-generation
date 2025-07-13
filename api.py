import os
import sys
import asyncio
import json
import tempfile
import logging
import time
import base64
import shutil
import uuid
import warnings
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
    Depends,
)
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mongoengine import connect, disconnect, DoesNotExist

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["OPENAI_LOG"] = "ERROR"
os.environ["URLLIB3_DISABLE_WARNINGS"] = "1"
os.environ["PYTHONWARNINGS"] = "ignore"

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
    title="DRHP IPO Notes Generation API",
    description="API for processing DRHP documents and generating IPO notes",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Models ---
class CompanyResponse(BaseModel):
    id: str
    name: str
    corporate_identity_number: str
    website_link: Optional[str] = None
    created_at: datetime
    processing_status: str
    has_markdown: bool
    pages_count: int
    checklist_outputs_count: int


class ReportResponse(BaseModel):
    company_id: str
    company_name: str
    markdown: str
    generated_at: datetime


class PDFGenerationRequest(BaseModel):
    markdown_content: str
    company_name: str
    logo_id: Optional[str] = None


class LogoUploadResponse(BaseModel):
    logo_id: str
    filename: str
    path: str


class AssetConfigRequest(BaseModel):
    entity_logo_id: str
    front_header_id: str


# --- Environment and Database Setup ---
def validate_env():
    required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "DRHP_MONGODB_URI"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    logger.info("All required environment variables are set.")


def connect_to_db():
    MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
    DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")

    try:
        disconnect(alias="core")
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise


# --- MongoEngine Models ---
from mongoengine import (
    Document,
    StringField,
    DateTimeField,
    IntField,
    ListField,
    ReferenceField,
    BooleanField,
)


class Company(Document):
    meta = {"db_alias": "core", "collection": "company"}
    name = StringField(required=True)
    corporate_identity_number = StringField(required=True, unique=True)
    website_link = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    processing_status = StringField(default="PENDING")
    has_markdown = BooleanField(default=False)


class Page(Document):
    meta = {"db_alias": "core", "collection": "pages"}
    company_id = ReferenceField(Company, required=True)
    page_number_pdf = IntField(required=True)
    page_number_drhp = IntField()
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
    citations = ListField(IntField())
    commentary = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)


class FinalMarkdown(Document):
    meta = {"db_alias": "core", "collection": "final_markdown"}
    company_id = ReferenceField(Company, required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)
    generated_at = DateTimeField(default=datetime.utcnow)


# --- Utility Functions ---
def get_company_by_id(company_id: str) -> Company:
    """Get company by ID with proper error handling."""
    try:
        from bson import ObjectId

        company = Company.objects.get(id=ObjectId(company_id))
        return company
    except DoesNotExist:
        raise HTTPException(
            status_code=404, detail=f"Company with ID {company_id} not found"
        )
    except Exception as e:
        logger.error(f"Error fetching company {company_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def update_company_status(company_id: str, status: str):
    """Update company processing status."""
    try:
        from bson import ObjectId

        Company.objects(id=ObjectId(company_id)).update_one(
            set__processing_status=status
        )
    except Exception as e:
        logger.error(f"Error updating company status: {e}")


def get_company_stats(company: Company) -> Dict[str, Any]:
    """Get comprehensive company statistics."""
    try:
        pages_count = Page.objects(company_id=company).count()
        checklist_outputs_count = ChecklistOutput.objects(company_id=company).count()
        has_markdown = FinalMarkdown.objects(company_id=company).first() is not None

        return {
            "pages_count": pages_count,
            "checklist_outputs_count": checklist_outputs_count,
            "has_markdown": has_markdown,
        }
    except Exception as e:
        logger.error(f"Error getting company stats: {e}")
        return {"pages_count": 0, "checklist_outputs_count": 0, "has_markdown": False}


def generate_sse_event(data: Dict[str, Any], event_type: str = "update") -> str:
    """Generate Server-Sent Event format."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# --- Background Processing Functions ---
async def process_drhp_pipeline(pdf_path: str, company_id: str):
    """Background task to process DRHP pipeline."""
    try:
        update_company_status(company_id, "PROCESSING")

        # Step 1: Extract company details
        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "extracting_company_details",
                "message": "Extracting company details from PDF...",
            }
        )

        # Process PDF and extract company details
        processor = LocalDRHPProcessor(
            qdrant_url=os.getenv("QDRANT_URL"),
            collection_name=None,
            max_workers=5,
            company_name=None,
        )

        json_path = processor.process_pdf_locally(pdf_path, "TEMP_COMPANY")

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

        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "company_details_extracted",
                "message": f"Company details extracted: {company_details.name}",
            }
        )

        # Step 2: Save pages to MongoDB
        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "saving_pages",
                "message": "Saving pages to database...",
            }
        )

        company = get_company_by_id(company_id)
        saved_pages = []
        failed_pages = []

        page_items = [(k, v) for k, v in pages.items() if k != "_metadata"]
        page_items = [(k, v) for k, v in page_items if k.isdigit()]

        for page_no, page_info in page_items:
            try:
                if Page.objects(
                    company_id=company, page_number_pdf=int(page_no)
                ).first():
                    saved_pages.append(page_no)
                    continue

                page_number_drhp_val = page_info.get("page_number_drhp", None)
                if (
                    page_number_drhp_val is not None
                    and page_number_drhp_val != ""
                    and str(page_number_drhp_val).strip()
                ):
                    try:
                        page_number_drhp_val = int(page_number_drhp_val)
                    except (ValueError, TypeError):
                        page_number_drhp_val = None
                else:
                    page_number_drhp_val = None

                Page(
                    company_id=company,
                    page_number_pdf=int(page_no),
                    page_number_drhp=page_number_drhp_val,
                    page_content=page_info.get("page_content", ""),
                ).save()
                saved_pages.append(page_no)
            except Exception as e:
                logger.error(f"Failed to save page {page_no}: {e}")
                failed_pages.append(page_no)

        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "pages_saved",
                "message": f"Saved {len(saved_pages)} pages, failed: {len(failed_pages)}",
            }
        )

        # Step 3: Upsert to Qdrant
        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "upserting_to_qdrant",
                "message": "Creating embeddings and upserting to vector database...",
            }
        )

        qdrant_collection = (
            f"drhp_notes_{company_details.name.replace(' ', '_').upper()}"
        )
        processor.collection_name = qdrant_collection
        processor.upsert_pages_to_qdrant(
            json_path, company_details.name, str(company.id)
        )

        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "qdrant_upserted",
                "message": f"Embeddings upserted to Qdrant collection: {qdrant_collection}",
            }
        )

        # Step 4: Process checklist
        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "processing_checklist",
                "message": "Processing checklist and generating AI outputs...",
            }
        )

        checklist_path = os.path.join(
            os.path.dirname(__file__),
            "DRHP_crud_backend",
            "Checklists",
            "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
        )

        checklist_name = os.path.basename(checklist_path)
        note_processor = DRHPNoteChecklistProcessor(
            checklist_path, qdrant_collection, str(company.id), checklist_name
        )
        note_processor.process()

        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "checklist_processed",
                "message": "Checklist processing completed",
            }
        )

        # Step 5: Generate markdown
        yield generate_sse_event(
            {
                "status": "PROCESSING",
                "step": "generating_markdown",
                "message": "Generating final markdown report...",
            }
        )

        # Get all checklist outputs for the company
        rows = ChecklistOutput.objects(company_id=company).order_by("row_index")

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

        markdown_content = "".join(md_lines)

        # Save final markdown
        FinalMarkdown.objects(company_id=company).update_one(
            set__company_name=company.name,
            set__markdown=markdown_content,
            set__generated_at=datetime.utcnow(),
            upsert=True,
        )

        # Update company status
        Company.objects(id=company.id).update_one(
            set__processing_status="COMPLETED", set__has_markdown=True
        )

        # Cleanup
        try:
            os.remove(json_path)
        except Exception as e:
            logger.warning(f"Failed to clean up JSON file: {e}")

        yield generate_sse_event(
            {
                "status": "COMPLETED",
                "step": "final",
                "message": "DRHP processing completed successfully",
                "markdown": markdown_content,
            }
        )

    except Exception as e:
        logger.error(f"Pipeline processing error: {e}")
        update_company_status(company_id, "FAILED")
        yield generate_sse_event(
            {
                "status": "FAILED",
                "step": "error",
                "message": f"Processing failed: {str(e)}",
            }
        )


# --- API Endpoints ---


@app.post("/companies/")
async def upload_and_process_drhp(file: UploadFile = File(...)):
    """
    Upload a DRHP PDF and initiate the full processing pipeline.
    Returns a Server-Sent Events stream with real-time status updates.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name

        # Extract company details first
        processor = LocalDRHPProcessor(
            qdrant_url=os.getenv("QDRANT_URL"),
            collection_name=None,
            max_workers=5,
            company_name=None,
        )

        json_path = processor.process_pdf_locally(temp_path, "TEMP_COMPANY")

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

        # Check if company already exists
        existing_company = Company.objects(
            corporate_identity_number=company_details.corporate_identity_number
        ).first()
        if existing_company:
            raise HTTPException(
                status_code=409, detail=f"Company {company_details.name} already exists"
            )

        # Create company record
        company = Company(
            name=company_details.name,
            corporate_identity_number=company_details.corporate_identity_number,
            website_link=getattr(company_details, "website_link", None),
            processing_status="PENDING",
        ).save()

        # Cleanup temporary files
        try:
            os.remove(json_path)
            os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary files: {e}")

        # Start background processing
        async def process_stream():
            async for event in process_drhp_pipeline(temp_path, str(company.id)):
                yield event

        return StreamingResponse(
            process_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    except Exception as e:
        logger.error(f"Error in upload_and_process_drhp: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/companies/", response_model=List[CompanyResponse])
async def get_companies():
    """Get all companies with their processing status."""
    try:
        companies = Company.objects.all().order_by("-created_at")
        response_companies = []

        for company in companies:
            stats = get_company_stats(company)
            response_companies.append(
                CompanyResponse(
                    id=str(company.id),
                    name=company.name,
                    corporate_identity_number=company.corporate_identity_number,
                    website_link=company.website_link,
                    created_at=company.created_at,
                    processing_status=company.processing_status,
                    has_markdown=stats["has_markdown"],
                    pages_count=stats["pages_count"],
                    checklist_outputs_count=stats["checklist_outputs_count"],
                )
            )

        return response_companies

    except Exception as e:
        logger.error(f"Error fetching companies: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete("/companies/{company_id}")
async def delete_company(company_id: str):
    """Delete a company and all its associated data."""
    try:
        company = get_company_by_id(company_id)

        # Delete related data
        Page.objects(company_id=company).delete()
        ChecklistOutput.objects(company_id=company).delete()
        FinalMarkdown.objects(company_id=company).delete()

        # Delete Qdrant collection
        try:
            qdrant_collection = f"drhp_notes_{company.name.replace(' ', '_').upper()}"
            client = QdrantClient(url=os.getenv("QDRANT_URL"))
            if qdrant_collection in [
                c.name for c in client.get_collections().collections
            ]:
                client.delete_collection(collection_name=qdrant_collection)
        except Exception as e:
            logger.warning(f"Failed to delete Qdrant collection: {e}")

        # Delete company
        company.delete()

        return {
            "message": f"Company {company.name} and all associated data deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/companies/{company_id}/report", response_model=ReportResponse)
async def get_company_report(company_id: str):
    """Get the final generated report for a company."""
    try:
        company = get_company_by_id(company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()

        if not markdown_doc:
            raise HTTPException(
                status_code=404, detail="No report found for this company"
            )

        return ReportResponse(
            company_id=str(company.id),
            company_name=company.name,
            markdown=markdown_doc.markdown,
            generated_at=markdown_doc.generated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching company report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/companies/{company_id}/regenerate")
async def regenerate_company_report(company_id: str):
    """Re-run the AI processing steps for an existing company."""
    try:
        company = get_company_by_id(company_id)

        # Delete existing checklist outputs and markdown
        ChecklistOutput.objects(company_id=company).delete()
        FinalMarkdown.objects(company_id=company).delete()

        # Update status
        update_company_status(company_id, "PROCESSING")

        async def regenerate_stream():
            try:
                yield generate_sse_event(
                    {
                        "status": "PROCESSING",
                        "step": "regenerating",
                        "message": "Starting regeneration process...",
                    }
                )

                # Get Qdrant collection name
                qdrant_collection = (
                    f"drhp_notes_{company.name.replace(' ', '_').upper()}"
                )

                # Process checklist
                yield generate_sse_event(
                    {
                        "status": "PROCESSING",
                        "step": "processing_checklist",
                        "message": "Processing checklist and generating AI outputs...",
                    }
                )

                checklist_path = os.path.join(
                    os.path.dirname(__file__),
                    "DRHP_crud_backend",
                    "Checklists",
                    "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
                )

                checklist_name = os.path.basename(checklist_path)
                note_processor = DRHPNoteChecklistProcessor(
                    checklist_path, qdrant_collection, str(company.id), checklist_name
                )
                note_processor.process()

                yield generate_sse_event(
                    {
                        "status": "PROCESSING",
                        "step": "checklist_processed",
                        "message": "Checklist processing completed",
                    }
                )

                # Generate markdown
                yield generate_sse_event(
                    {
                        "status": "PROCESSING",
                        "step": "generating_markdown",
                        "message": "Generating final markdown report...",
                    }
                )

                rows = ChecklistOutput.objects(company_id=company).order_by("row_index")

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

                    md_lines.append(
                        f"{heading_md}\n\n{ai_output}\n\n{commentary_md}\n\n"
                    )

                markdown_content = "".join(md_lines)

                # Save final markdown
                FinalMarkdown.objects(company_id=company).update_one(
                    set__company_name=company.name,
                    set__markdown=markdown_content,
                    set__generated_at=datetime.utcnow(),
                    upsert=True,
                )

                # Update company status
                Company.objects(id=company.id).update_one(
                    set__processing_status="COMPLETED", set__has_markdown=True
                )

                yield generate_sse_event(
                    {
                        "status": "COMPLETED",
                        "step": "final",
                        "message": "Report regeneration completed successfully",
                        "markdown": markdown_content,
                    }
                )

            except Exception as e:
                logger.error(f"Regeneration error: {e}")
                update_company_status(company_id, "FAILED")
                yield generate_sse_event(
                    {
                        "status": "FAILED",
                        "step": "error",
                        "message": f"Regeneration failed: {str(e)}",
                    }
                )

        return StreamingResponse(
            regenerate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in regenerate_company_report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/reports/generate-pdf")
async def generate_pdf_report(request: PDFGenerationRequest):
    """Convert markdown content to PDF with company branding."""
    try:
        # Create output directory
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)

        # Setup Jinja2 environment
        env = Environment(loader=FileSystemLoader("templates"))

        # Convert markdown to HTML
        html_body = markdown.markdown(
            request.markdown_content, extensions=["tables", "fenced_code"]
        )

        # Load images
        def load_image_base64(path):
            try:
                with open(path, "rb") as f:
                    return (
                        f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
                    )
            except Exception as e:
                logger.warning(f"Failed to load image {path}: {e}")
                return None

        axis_logo_data = load_image_base64("assets/axis_logo.png")
        company_logo_data = load_image_base64("assets/Pine Labs_logo.png")  # Default
        front_header_data = load_image_base64("assets/front_header.png")

        # Try to load company-specific logo
        company_logo_path = f"assets/{request.company_name.replace(' ', '_')}_logo.png"
        if os.path.exists(company_logo_path):
            company_logo_data = load_image_base64(company_logo_path)

        # Prepare context
        context = {
            "company_name": request.company_name.upper(),
            "document_date": datetime.today().strftime("%B %Y"),
            "company_logo_data": company_logo_data,
            "axis_logo_data": axis_logo_data,
            "front_header_data": front_header_data,
            "content": html_body,
        }

        # Render HTML
        front_html = env.get_template("front_page.html").render(context)
        content_html = env.get_template("content_page.html").render(context)
        full_html = front_html + content_html

        # Generate PDF filename
        safe_company_name = (
            request.company_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
        )
        pdf_filename = f"{safe_company_name}_IPO_Notes.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)

        # Generate PDF
        html_doc = HTML(string=full_html, base_url=".")
        css_doc = CSS(filename="styles/styles.css")
        html_doc.write_pdf(pdf_path, stylesheets=[css_doc])

        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=pdf_filename,
            headers={"Content-Disposition": f"attachment; filename={pdf_filename}"},
        )

    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")


@app.post("/assets/logos", response_model=LogoUploadResponse)
async def upload_logo(file: UploadFile = File(...)):
    """Upload a logo image."""
    try:
        # Validate file type
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image files are allowed")

        # Create assets directory
        assets_dir = "assets"
        os.makedirs(assets_dir, exist_ok=True)

        # Generate unique filename
        logo_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename)[1]
        filename = f"{logo_id}{file_extension}"
        file_path = os.path.join(assets_dir, filename)

        # Save file
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        return LogoUploadResponse(logo_id=logo_id, filename=filename, path=file_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading logo: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/companies/{company_id}/logo")
async def associate_company_logo(company_id: str, logo_id: str):
    """Associate a logo with a company."""
    try:
        company = get_company_by_id(company_id)
        # In a real implementation, you would store the logo association
        # For now, we'll just return success
        return {"message": f"Logo {logo_id} associated with company {company.name}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error associating logo: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.put("/config/entity-assets")
async def set_entity_assets(request: AssetConfigRequest):
    """Set global entity assets configuration."""
    try:
        # In a real implementation, you would store this configuration
        # For now, we'll just return success
        return {
            "message": "Entity assets configuration updated",
            "entity_logo_id": request.entity_logo_id,
            "front_header_id": request.front_header_id,
        }

    except Exception as e:
        logger.error(f"Error setting entity assets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# --- Health Check Endpoint ---
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
