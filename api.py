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
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from bson import ObjectId

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

# MongoDB Configuration
MONGO_URI = os.getenv("DRHP_MONGODB_URI")
DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")
COLLECTION_NAME = "final_markdown"

# MongoDB client
client = None
db = None

# --- FastAPI App Initialization ---
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    try:
        validate_env()
        await startup_db_client()
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    yield
    # Shutdown
    try:
        await shutdown_db_client()
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


async def startup_db_client():
    """Startup MongoDB client"""
    global client, db
    try:
        client = AsyncIOMotorClient(MONGO_URI)
        db = client[DB_NAME]
        # Test the connection
        await client.admin.command("ping")
        logger.info("✅ Connected to MongoDB successfully")
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {e}")
        raise e


async def shutdown_db_client():
    """Shutdown MongoDB client"""
    global client
    if client:
        client.close()
        logger.info("✅ MongoDB connection closed")


# --- Logo Management ---
class LogoManager:
    def __init__(self):
        self.assets_dir = "assets"
        self.company_logo = None
        self.entity_logo = None
        os.makedirs(self.assets_dir, exist_ok=True)

    def load_image_base64(self, path):
        """Load image and convert to base64"""
        try:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return (
                        f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
                    )
            else:
                logger.warning(f"Image not found: {path}")
                return None
        except Exception as e:
            logger.warning(f"Failed to load image {path}: {e}")
            return None

    def set_company_logo(self, logo_path):
        """Set company logo path"""
        self.company_logo = logo_path
        logger.info(f"Company logo set to: {logo_path}")

    def set_entity_logo(self, logo_path):
        """Set entity logo path"""
        self.entity_logo = logo_path
        logger.info(f"Entity logo set to: {logo_path}")

    def get_company_logo_data(self):
        """Get company logo as base64"""
        if self.company_logo:
            return self.load_image_base64(self.company_logo)
        return self.load_image_base64("assets/Pine Labs_logo.png")  # Default

    def get_entity_logo_data(self):
        """Get entity logo as base64"""
        if self.entity_logo:
            return self.load_image_base64(self.entity_logo)
        return self.load_image_base64("assets/axis_logo.png")  # Default


# Initialize logo manager
logo_manager = LogoManager()


# --- Report Generation Functions ---
def generate_html_report(markdown_content: str, company_name: str) -> str:
    """Generate HTML report from markdown content"""
    try:
        # Setup Jinja2 environment
        env = Environment(loader=FileSystemLoader("templates"))

        # Convert markdown to HTML
        html_body = markdown.markdown(
            markdown_content, extensions=["tables", "fenced_code"]
        )

        # Get logo data
        company_logo_data = logo_manager.get_company_logo_data()
        entity_logo_data = logo_manager.get_entity_logo_data()
        front_header_data = logo_manager.load_image_base64("assets/front_header.png")

        # Prepare context
        context = {
            "company_name": company_name.upper(),
            "document_date": datetime.today().strftime("%B %Y"),
            "company_logo_data": company_logo_data,
            "axis_logo_data": entity_logo_data,
            "front_header_data": front_header_data,
            "content": html_body,
        }

        # Render HTML
        front_html = env.get_template("front_page.html").render(context)
        content_html = env.get_template("content_page.html").render(context)
        full_html = front_html + content_html

        logger.info(f"✅ HTML report generated for {company_name}")
        return full_html

    except Exception as e:
        logger.error(f"❌ Error generating HTML report: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error generating HTML report: {str(e)}"
        )


def generate_pdf_report(markdown_content: str, company_name: str) -> str:
    """Generate PDF report from markdown content"""
    try:
        # Generate HTML first
        html_content = generate_html_report(markdown_content, company_name)

        # Create temporary file for PDF
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_path = temp_file.name
        temp_file.close()

        # Generate PDF
        HTML(string=html_content, base_url=".").write_pdf(
            temp_path, stylesheets=[CSS("styles/styles.css")]
        )

        logger.info(f"✅ PDF generated for {company_name}")
        return temp_path

    except Exception as e:
        logger.error(f"❌ Error generating PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating PDF: {str(e)}")


# --- API Endpoints ---


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "DRHP Report Generator API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        await client.admin.command("ping")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}


@app.get("/companies")
async def list_companies():
    """List all companies in the final_markdown collection"""
    try:
        collection = db[COLLECTION_NAME]
        companies = []

        async for doc in collection.find(
            {}, {"company_id": 1, "company_name": 1, "_id": 0}
        ):
            company_id = doc.get("company_id")
            # Always convert ObjectId to string
            if isinstance(company_id, ObjectId):
                company_id = str(company_id)
            companies.append(
                {
                    "company_id": company_id,
                    "company_name": doc.get("company_name"),
                }
            )

        return {"total_companies": len(companies), "companies": companies}

    except Exception as e:
        logger.error(f"❌ Error listing companies: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error listing companies: {str(e)}"
        )


@app.get("/report/{company_id}")
async def get_final_report(company_id: str, format: str = "html"):
    """
    Get final report for a company by ID

    Args:
        company_id: The company ID (ObjectId as string)
        format: Output format (pdf, html, markdown)

    Returns:
        The report in the requested format
    """
    try:
        # Query MongoDB for the company's final markdown
        collection = db[COLLECTION_NAME]

        # Always treat company_id as ObjectId
        try:
            object_id = ObjectId(company_id)
            document = await collection.find_one({"company_id": object_id})
        except Exception:
            document = None

        if not document:
            raise HTTPException(
                status_code=404,
                detail=f"Company with ID {company_id} not found in final_markdown collection",
            )

        company_name = document.get("company_name", f"Company {company_id}")
        markdown_content = document.get("markdown", "")

        if not markdown_content:
            raise HTTPException(
                status_code=404,
                detail=f"No markdown content found for company {company_id}",
            )

        logger.info(f"✅ Found markdown for company {company_id}: {company_name}")

        # Return based on requested format
        if format.lower() == "markdown":
            return {
                "company_id": company_id,
                "company_name": company_name,
                "content": markdown_content,
                "format": "markdown",
            }

        elif format.lower() == "html":
            html_content = generate_html_report(markdown_content, company_name)
            return {
                "company_id": company_id,
                "company_name": company_name,
                "content": html_content,
                "format": "html",
            }

        elif format.lower() == "pdf":
            # Generate PDF
            pdf_path = generate_pdf_report(markdown_content, company_name)

            # Return PDF file
            return FileResponse(
                path=pdf_path,
                media_type="application/pdf",
                filename=f"{company_name}_ipo_notes.pdf",
                background=None,  # This ensures the file is deleted after sending
            )

        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid format. Supported formats: pdf, html, markdown",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing request for company {company_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/upload-logo")
async def upload_logo(
    file: UploadFile = File(...),
    logo_type: str = Query(..., description="Type of logo: 'company' or 'entity'"),
):
    """Upload a logo image"""
    try:
        # Validate file type
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Only image files are allowed")

        # Validate logo type
        if logo_type not in ["company", "entity"]:
            raise HTTPException(
                status_code=400, detail="Logo type must be 'company' or 'entity'"
            )

        # Create assets directory
        assets_dir = "assets"
        os.makedirs(assets_dir, exist_ok=True)

        # Generate unique filename
        logo_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename)[1]
        filename = f"{logo_type}_{logo_id}{file_extension}"
        file_path = os.path.join(assets_dir, filename)

        # Save file
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Set logo in manager
        if logo_type == "company":
            logo_manager.set_company_logo(file_path)
        else:
            logo_manager.set_entity_logo(file_path)

        return {
            "logo_id": logo_id,
            "filename": filename,
            "path": file_path,
            "logo_type": logo_type,
            "message": f"{logo_type.capitalize()} logo uploaded successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading logo: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/debug/companies")
async def debug_companies():
    """Debug endpoint to check companies and their markdown status."""
    try:
        collection = db[COLLECTION_NAME]
        companies = []

        async for doc in collection.find({}):
            company_id = doc.get("company_id")
            if isinstance(company_id, ObjectId):
                company_id = str(company_id)

            companies.append(
                {
                    "id": company_id,
                    "name": doc.get("company_name", "Unknown"),
                    "has_markdown": bool(doc.get("markdown")),
                    "markdown_length": len(doc.get("markdown", "")),
                    "generated_at": doc.get("generated_at"),
                }
            )

        return {"total_companies": len(companies), "companies": companies}
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Debug error: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
