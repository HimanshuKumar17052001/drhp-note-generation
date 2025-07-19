# import os
# import sys
# import asyncio
# import json
# import tempfile
# import logging
# import time
# import base64
# import shutil
# import uuid
# import warnings
# from datetime import datetime
# from typing import List, Optional, Dict, Any
# from pathlib import Path
# from dotenv import load_dotenv

# from fastapi import (
#     FastAPI,
#     UploadFile,
#     File,
#     HTTPException,
#     Path,
#     BackgroundTasks,
#     Query,
#     Depends,
# )
# from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from mongoengine import connect, disconnect, DoesNotExist

# # Suppress warnings
# warnings.filterwarnings("ignore")
# os.environ["LITELLM_LOG"] = "ERROR"
# os.environ["OPENAI_LOG"] = "ERROR"
# os.environ["URLLIB3_DISABLE_WARNINGS"] = "1"
# os.environ["PYTHONWARNINGS"] = "ignore"

# # Add the backend directory to the Python path to allow imports
# sys.path.append(os.path.join(os.path.dirname(__file__), "DRHP_crud_backend"))

# # Import DRHP pipeline components
# from DRHP_crud_backend.local_drhp_processor_final import LocalDRHPProcessor
# from DRHP_crud_backend.baml_client import b
# from DRHP_crud_backend.DRHP_ai_processing.note_checklist_processor import (
#     DRHPNoteChecklistProcessor,
# )
# from qdrant_client import QdrantClient

# # Import PDF generation components
# import markdown
# from jinja2 import Environment, FileSystemLoader
# from weasyprint import HTML, CSS
# from azure_blob_utils import get_blob_storage

# # Load environment variables
# load_dotenv()

# # Setup logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("DRHP_API")

# # --- FastAPI App Initialization ---
# from contextlib import asynccontextmanager


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     """Lifespan context manager for startup and shutdown events."""
#     # Startup
#     try:
#         validate_env()
#         connect_to_db()
#     except Exception as e:
#         logger.error(f"Startup failed: {e}")
#         raise
#     yield
#     # Shutdown
#     try:
#         disconnect(alias="core")
#     except Exception as e:
#         logger.error(f"Shutdown error: {e}")


# app = FastAPI(
#     title="DRHP IPO Notes Generation API",
#     description="API for processing DRHP documents and generating IPO notes",
#     version="1.0.0",
#     lifespan=lifespan,
# )

# # Add CORS middleware
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


# # --- Pydantic Models ---
# class CompanyResponse(BaseModel):
#     id: str
#     name: str
#     corporate_identity_number: str
#     website_link: Optional[str] = None
#     created_at: datetime
#     processing_status: str
#     has_markdown: bool
#     pages_count: int
#     checklist_outputs_count: int


# class ReportResponse(BaseModel):
#     company_id: str
#     company_name: str
#     markdown: str
#     generated_at: datetime


# class PDFGenerationRequest(BaseModel):
#     markdown_content: str
#     company_name: str
#     logo_id: Optional[str] = None


# class LogoUploadResponse(BaseModel):
#     logo_id: str
#     filename: str
#     path: str


# class AssetConfigRequest(BaseModel):
#     entity_logo_id: str
#     front_header_id: str


# # --- Environment and Database Setup ---
# def validate_env():
#     required_vars = ["OPENAI_API_KEY", "QDRANT_URL", "DRHP_MONGODB_URI"]
#     missing = [v for v in required_vars if not os.getenv(v)]
#     if missing:
#         logger.error(f"Missing required environment variables: {', '.join(missing)}")
#         raise EnvironmentError(
#             f"Missing required environment variables: {', '.join(missing)}"
#         )
#     logger.info("All required environment variables are set.")


# def connect_to_db():
#     MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
#     DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")

#     try:
#         disconnect(alias="core")
#         connect(alias="core", host=MONGODB_URI, db=DB_NAME)
#         logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
#     except Exception as e:
#         logger.error(f"MongoDB connection failed: {e}")
#         raise


# # --- MongoEngine Models ---
# from mongoengine import (
#     Document,
#     StringField,
#     DateTimeField,
#     IntField,
#     ListField,
#     ReferenceField,
#     BooleanField,
# )


# class Company(Document):
#     meta = {"db_alias": "core", "collection": "company"}
#     name = StringField(required=True)
#     corporate_identity_number = StringField(required=True, unique=True)
#     website_link = StringField()
#     created_at = DateTimeField(default=datetime.utcnow)
#     processing_status = StringField(default="PENDING")
#     has_markdown = BooleanField(default=False)


# class Page(Document):
#     meta = {"db_alias": "core", "collection": "pages"}
#     company_id = ReferenceField(Company, required=True)
#     page_number_pdf = IntField(required=True)
#     page_number_drhp = IntField()
#     page_content = StringField()


# class ChecklistOutput(Document):
#     meta = {"db_alias": "core", "collection": "checklist_outputs"}
#     company_id = ReferenceField(Company, required=True)
#     checklist_name = StringField(required=True)
#     row_index = IntField(required=True)
#     topic = StringField()
#     section = StringField()
#     ai_prompt = StringField()
#     ai_output = StringField()
#     citations = ListField(IntField())
#     commentary = StringField()
#     created_at = DateTimeField(default=datetime.utcnow)
#     updated_at = DateTimeField(default=datetime.utcnow)


# class FinalMarkdown(Document):
#     meta = {"db_alias": "core", "collection": "final_markdown"}
#     company_id = ReferenceField(Company, required=True)
#     company_name = StringField(required=True)
#     markdown = StringField(required=True)
#     generated_at = DateTimeField(default=datetime.utcnow)


# # --- Utility Functions ---
# def get_company_by_id(company_id: str) -> Company:
#     """Get company by ID with proper error handling."""
#     try:
#         from bson import ObjectId

#         company = Company.objects.get(id=ObjectId(company_id))
#         return company
#     except DoesNotExist:
#         raise HTTPException(
#             status_code=404, detail=f"Company with ID {company_id} not found"
#         )
#     except Exception as e:
#         logger.error(f"Error fetching company {company_id}: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# def update_company_status(company_id: str, status: str):
#     """Update company processing status."""
#     try:
#         from bson import ObjectId

#         Company.objects(id=ObjectId(company_id)).update_one(
#             set__processing_status=status
#         )
#     except Exception as e:
#         logger.error(f"Error updating company status: {e}")


# def get_company_stats(company: Company) -> Dict[str, Any]:
#     """Get comprehensive company statistics."""
#     try:
#         pages_count = Page.objects(company_id=company).count()
#         checklist_outputs_count = ChecklistOutput.objects(company_id=company).count()
#         has_markdown = FinalMarkdown.objects(company_id=company).first() is not None

#         return {
#             "pages_count": pages_count,
#             "checklist_outputs_count": checklist_outputs_count,
#             "has_markdown": has_markdown,
#         }
#     except Exception as e:
#         logger.error(f"Error getting company stats: {e}")
#         return {"pages_count": 0, "checklist_outputs_count": 0, "has_markdown": False}


# def generate_sse_event(data: Dict[str, Any], event_type: str = "update") -> str:
#     """Generate Server-Sent Event format."""
#     return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# # --- Background Processing Functions ---
# async def process_drhp_pipeline(pdf_path: str, company_id: str):
#     """Background task to process DRHP pipeline."""
#     try:
#         update_company_status(company_id, "PROCESSING")

#         # Step 1: Extract company details
#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "extracting_company_details",
#                 "message": "Extracting company details from PDF...",
#             }
#         )

#         # Process PDF and extract company details
#         processor = LocalDRHPProcessor(
#             qdrant_url=os.getenv("QDRANT_URL"),
#             collection_name=None,
#             max_workers=5,
#             company_name=None,
#         )

#         # Call process_pdf_locally, which now returns the Azure blob name of the temp JSON
#         json_blob_name = processor.process_pdf_locally(pdf_path, "TEMP_COMPANY")

#         # Download the temp JSON blob to a local temp file for further processing
#         with tempfile.NamedTemporaryFile(
#             delete=False, suffix=".json"
#         ) as temp_json_file:
#             blob_storage = get_blob_storage()
#             blob_storage.download_file(json_blob_name, temp_json_file.name)
#             local_json_path = temp_json_file.name

#         with open(local_json_path, "r", encoding="utf-8") as f:
#             data = json.load(f)

#         pdf_name = list(data.keys())[0]
#         pages = data[pdf_name]
#         first_pages_text = "\n".join(
#             [
#                 pages[str(i)].get("page_content", "")
#                 for i in range(1, 11)
#                 if str(i) in pages
#             ]
#         )

#         company_details = b.ExtractCompanyDetails(first_pages_text)

#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "company_details_extracted",
#                 "message": f"Company details extracted: {company_details.name}",
#             }
#         )

#         # Step 2: Save pages to MongoDB
#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "saving_pages",
#                 "message": "Saving pages to database...",
#             }
#         )

#         company = get_company_by_id(company_id)
#         saved_pages = []
#         failed_pages = []

#         page_items = [(k, v) for k, v in pages.items() if k != "_metadata"]
#         page_items = [(k, v) for k, v in page_items if k.isdigit()]

#         for page_no, page_info in page_items:
#             try:
#                 if Page.objects(
#                     company_id=company, page_number_pdf=int(page_no)
#                 ).first():
#                     saved_pages.append(page_no)
#                     continue

#                 page_number_drhp_val = page_info.get("page_number_drhp", None)
#                 if (
#                     page_number_drhp_val is not None
#                     and page_number_drhp_val != ""
#                     and str(page_number_drhp_val).strip()
#                 ):
#                     try:
#                         page_number_drhp_val = int(page_number_drhp_val)
#                     except (ValueError, TypeError):
#                         page_number_drhp_val = None
#                 else:
#                     page_number_drhp_val = None

#                 Page(
#                     company_id=company,
#                     page_number_pdf=int(page_no),
#                     page_number_drhp=page_number_drhp_val,
#                     page_content=page_info.get("page_content", ""),
#                 ).save()
#                 saved_pages.append(page_no)
#             except Exception as e:
#                 logger.error(f"Failed to save page {page_no}: {e}")
#                 failed_pages.append(page_no)

#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "pages_saved",
#                 "message": f"Saved {len(saved_pages)} pages, failed: {len(failed_pages)}",
#             }
#         )

#         # Step 3: Upsert to Qdrant
#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "upserting_to_qdrant",
#                 "message": "Creating embeddings and upserting to vector database...",
#             }
#         )

#         qdrant_collection = (
#             f"drhp_notes_{company_details.name.replace(' ', '_').upper()}"
#         )
#         processor.collection_name = qdrant_collection
#         processor.upsert_pages_to_qdrant(
#             local_json_path, company_details.name, str(company.id)
#         )

#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "qdrant_upserted",
#                 "message": f"Embeddings upserted to Qdrant collection: {qdrant_collection}",
#             }
#         )

#         # Step 4: Process checklist
#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "processing_checklist",
#                 "message": "Processing checklist and generating AI outputs...",
#             }
#         )

#         checklist_path = os.path.join(
#             os.path.dirname(__file__),
#             "DRHP_crud_backend",
#             "Checklists",
#             "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
#         )

#         checklist_name = os.path.basename(checklist_path)
#         note_processor = DRHPNoteChecklistProcessor(
#             checklist_path, qdrant_collection, str(company.id), checklist_name
#         )
#         note_processor.process()

#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "checklist_processed",
#                 "message": "Checklist processing completed",
#             }
#         )

#         # Step 5: Generate markdown
#         yield generate_sse_event(
#             {
#                 "status": "PROCESSING",
#                 "step": "generating_markdown",
#                 "message": "Generating final markdown report...",
#             }
#         )

#         # Get all checklist outputs for the company
#         rows = ChecklistOutput.objects(company_id=company).order_by("row_index")

#         md_lines = []
#         for row in rows:
#             topic = row.topic or ""
#             ai_output = row.ai_output or ""
#             commentary = row.commentary or ""

#             heading_md = f"**{topic}**" if topic else ""
#             commentary_md = (
#                 f'<span style="font-size:10px;"><i>AI Commentary : {commentary}</i></span>'
#                 if commentary
#                 else ""
#             )

#             md_lines.append(f"{heading_md}\n\n{ai_output}\n\n{commentary_md}\n\n")

#         markdown_content = "".join(md_lines)

#         # Save final markdown
#         FinalMarkdown.objects(company_id=company).update_one(
#             set__company_name=company.name,
#             set__markdown=markdown_content,
#             set__generated_at=datetime.utcnow(),
#             upsert=True,
#         )

#         # Update company status
#         Company.objects(id=company.id).update_one(
#             set__processing_status="COMPLETED", set__has_markdown=True
#         )

#         # Cleanup
#         try:
#             os.remove(local_json_path)
#         except Exception as e:
#             logger.warning(f"Failed to clean up JSON file: {e}")

#         yield generate_sse_event(
#             {
#                 "status": "COMPLETED",
#                 "step": "final",
#                 "message": "DRHP processing completed successfully",
#                 "markdown": markdown_content,
#             }
#         )

#     except Exception as e:
#         logger.error(f"Pipeline processing error: {e}")
#         update_company_status(company_id, "FAILED")
#         yield generate_sse_event(
#             {
#                 "status": "FAILED",
#                 "step": "error",
#                 "message": f"Processing failed: {str(e)}",
#             }
#         )


# # --- API Endpoints ---


# @app.post("/process-drhp/")
# async def process_drhp_upload(file: UploadFile = File(...)):
#     """
#     Upload a DRHP PDF and initiate the full processing pipeline.
#     This endpoint matches the HTML interface expectations.
#     """
#     if not file.filename.lower().endswith(".pdf"):
#         raise HTTPException(status_code=400, detail="Only PDF files are allowed")

#     blob_storage = get_blob_storage()
#     blob_url = None
#     blob_name = None
#     try:
#         # Generate a unique blob name for the PDF
#         import uuid

#         unique_id = str(uuid.uuid4())
#         blob_name = f"pdfs/{unique_id}_{file.filename}"
#         # Upload PDF to Azure Blob Storage
#         blob_url = blob_storage.upload_data(file.file, blob_name)
#         logger.info(f"PDF uploaded to Azure Blob Storage: {blob_url}")
#     except Exception as e:
#         logger.error(f"Failed to upload PDF to Azure Blob Storage: {e}")
#         raise HTTPException(
#             status_code=500, detail=f"Failed to upload PDF to Azure Blob Storage: {e}"
#         )

#     try:
#         # Extract company details first
#         processor = LocalDRHPProcessor(
#             qdrant_url=os.getenv("QDRANT_URL"),
#             collection_name=None,
#             max_workers=5,
#             company_name=None,
#         )

#         # Download the PDF from blob storage for processing (if needed)
#         import tempfile

#         with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
#             blob_storage.download_file(blob_name, temp_file.name)
#             temp_path = temp_file.name

#         # Call process_pdf_locally, which now returns the Azure blob name of the temp JSON
#         json_blob_name = processor.process_pdf_locally(temp_path, "TEMP_COMPANY")

#         # Download the temp JSON blob to a local temp file for further processing
#         with tempfile.NamedTemporaryFile(
#             delete=False, suffix=".json"
#         ) as temp_json_file:
#             blob_storage.download_file(json_blob_name, temp_json_file.name)
#             local_json_path = temp_json_file.name

#         with open(local_json_path, "r", encoding="utf-8") as f:
#             data = json.load(f)

#         pdf_name = list(data.keys())[0]
#         pages = data[pdf_name]
#         first_pages_text = "\n".join(
#             [
#                 pages[str(i)].get("page_content", "")
#                 for i in range(1, 11)
#                 if str(i) in pages
#             ]
#         )

#         company_details = b.ExtractCompanyDetails(first_pages_text)

#         # Check if company already exists
#         existing_company = Company.objects(
#             corporate_identity_number=company_details.corporate_identity_number
#         ).first()
#         if existing_company:
#             # Check if markdown already exists
#             existing_markdown = FinalMarkdown.objects(
#                 company_id=existing_company
#             ).first()
#             if existing_markdown:
#                 return {
#                     "company_id": str(existing_company.id),
#                     "message": "Company already exists with markdown",
#                     "existing_markdown": True,
#                     "pdf_blob_url": blob_url,
#                 }
#             else:
#                 return {
#                     "company_id": str(existing_company.id),
#                     "message": "Company already exists but processing is in progress",
#                     "existing_markdown": False,
#                     "pdf_blob_url": blob_url,
#                 }

#         # Create company record, store blob_url
#         company = Company(
#             name=company_details.name,
#             corporate_identity_number=company_details.corporate_identity_number,
#             website_link=getattr(company_details, "website_link", None),
#             processing_status="PENDING",
#         )
#         company.save()
#         logger.info(f"Company created: {company.name} ({company.id})")

#         # Optionally, store the PDF blob URL in the company document (add a field if needed)
#         # company.update(set__pdf_blob_url=blob_url)

#         # Cleanup temporary files
#         try:
#             os.remove(local_json_path)
#             os.remove(temp_path)
#         except Exception as e:
#             logger.warning(f"Failed to clean up temporary files: {e}")

#         return {
#             "company_id": str(company.id),
#             "message": "Company created successfully",
#             "existing_markdown": False,
#             "pdf_blob_url": blob_url,
#         }

#     except Exception as e:
#         logger.error(f"Error in process_drhp_upload: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# @app.post("/companies/")
# async def upload_and_process_drhp(file: UploadFile = File(...)):
#     """
#     Upload a DRHP PDF and initiate the full processing pipeline.
#     Returns a Server-Sent Events stream with real-time status updates.
#     """
#     if not file.filename.lower().endswith(".pdf"):
#         raise HTTPException(status_code=400, detail="Only PDF files are allowed")

#     blob_storage = get_blob_storage()
#     blob_url = None
#     blob_name = None
#     try:
#         # Generate a unique blob name for the PDF
#         import uuid

#         unique_id = str(uuid.uuid4())
#         blob_name = f"pdfs/{unique_id}_{file.filename}"
#         # Upload PDF to Azure Blob Storage
#         blob_url = blob_storage.upload_data(file.file, blob_name)
#         logger.info(f"PDF uploaded to Azure Blob Storage: {blob_url}")
#     except Exception as e:
#         logger.error(f"Failed to upload PDF to Azure Blob Storage: {e}")
#         raise HTTPException(
#             status_code=500, detail=f"Failed to upload PDF to Azure Blob Storage: {e}"
#         )

#     try:
#         # Download the PDF from blob storage for processing (if needed)
#         import tempfile

#         with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
#             blob_storage.download_file(blob_name, temp_file.name)
#             temp_path = temp_file.name

#         # Call process_pdf_locally, which now returns the Azure blob name of the temp JSON
#         processor = LocalDRHPProcessor(
#             qdrant_url=os.getenv("QDRANT_URL"),
#             collection_name=None,
#             max_workers=5,
#             company_name=None,
#         )
#         json_blob_name = processor.process_pdf_locally(temp_path, "TEMP_COMPANY")

#         # Download the temp JSON blob to a local temp file for further processing
#         with tempfile.NamedTemporaryFile(
#             delete=False, suffix=".json"
#         ) as temp_json_file:
#             blob_storage.download_file(json_blob_name, temp_json_file.name)
#             local_json_path = temp_json_file.name

#         with open(local_json_path, "r", encoding="utf-8") as f:
#             data = json.load(f)

#         pdf_name = list(data.keys())[0]
#         pages = data[pdf_name]
#         first_pages_text = "\n".join(
#             [
#                 pages[str(i)].get("page_content", "")
#                 for i in range(1, 11)
#                 if str(i) in pages
#             ]
#         )

#         company_details = b.ExtractCompanyDetails(first_pages_text)

#         # Check if company already exists
#         existing_company = Company.objects(
#             corporate_identity_number=company_details.corporate_identity_number
#         ).first()
#         if existing_company:
#             raise HTTPException(
#                 status_code=409, detail=f"Company {company_details.name} already exists"
#             )

#         # Create company record, store blob_url
#         company = Company(
#             name=company_details.name,
#             corporate_identity_number=company_details.corporate_identity_number,
#             website_link=getattr(company_details, "website_link", None),
#             processing_status="PENDING",
#         )
#         company.save()
#         logger.info(f"Company created: {company.name} ({company.id})")

#         # Optionally, store the PDF blob URL in the company document (add a field if needed)
#         # company.update(set__pdf_blob_url=blob_url)

#         # Cleanup temporary files
#         try:
#             os.remove(local_json_path)
#             os.remove(temp_path)
#         except Exception as e:
#             logger.warning(f"Failed to clean up temporary files: {e}")

#         # Start background processing
#         async def process_stream():
#             async for event in process_drhp_pipeline(temp_path, str(company.id)):
#                 yield event

#         return StreamingResponse(
#             process_stream(),
#             media_type="text/event-stream",
#             headers={
#                 "Cache-Control": "no-cache",
#                 "Connection": "keep-alive",
#                 "Access-Control-Allow-Origin": "*",
#                 "Access-Control-Allow-Headers": "*",
#             },
#         )

#     except Exception as e:
#         logger.error(f"Error in upload_and_process_drhp: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# @app.get("/companies/", response_model=List[CompanyResponse])
# async def get_companies():
#     """Get all companies with their processing status."""
#     try:
#         companies = Company.objects.all().order_by("-created_at")
#         response_companies = []

#         for company in companies:
#             stats = get_company_stats(company)
#             response_companies.append(
#                 CompanyResponse(
#                     id=str(company.id),
#                     name=company.name,
#                     corporate_identity_number=company.corporate_identity_number,
#                     website_link=company.website_link,
#                     created_at=company.created_at,
#                     processing_status=company.processing_status,
#                     has_markdown=stats["has_markdown"],
#                     pages_count=stats["pages_count"],
#                     checklist_outputs_count=stats["checklist_outputs_count"],
#                 )
#             )

#         return response_companies

#     except Exception as e:
#         logger.error(f"Error fetching companies: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/company/{company_id}")
# async def get_company(company_id: str):
#     """Get a specific company by ID."""
#     try:
#         company = get_company_by_id(company_id)
#         stats = get_company_stats(company)

#         return {
#             "id": str(company.id),
#             "name": company.name,
#             "corporate_identity_number": company.corporate_identity_number,
#             "website_link": company.website_link,
#             "created_at": company.created_at,
#             "processing_status": company.processing_status,
#             "has_markdown": stats["has_markdown"],
#             "pages_count": stats["pages_count"],
#             "checklist_outputs_count": stats["checklist_outputs_count"],
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching company: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/company/{company_id}/status")
# async def get_company_processing_status(company_id: str):
#     """Get processing status for a company."""
#     try:
#         company = get_company_by_id(company_id)
#         stats = get_company_stats(company)

#         # Determine overall status
#         if company.processing_status == "COMPLETED":
#             overall_status = "Completed"
#         elif company.processing_status == "PROCESSING":
#             overall_status = "Processing"
#         elif company.processing_status == "FAILED":
#             overall_status = "Failed"
#         else:
#             overall_status = "Pending"

#         return {
#             "company_id": str(company.id),
#             "processing_status": company.processing_status,
#             "pages_done": stats["pages_count"] > 0,
#             "qdrant_done": stats["pages_count"]
#             > 0,  # Assume Qdrant is done if pages exist
#             "checklist_done": stats["checklist_outputs_count"] > 0,
#             "markdown_done": stats["has_markdown"],
#             "overall_status": overall_status,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching company status: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/company/{company_id}/markdown")
# async def get_company_markdown(company_id: str):
#     """Get the markdown content for a company."""
#     try:
#         company = get_company_by_id(company_id)
#         markdown_doc = FinalMarkdown.objects(company_id=company).first()

#         if not markdown_doc:
#             raise HTTPException(
#                 status_code=404, detail="No markdown found for this company"
#             )

#         return {
#             "company_id": str(company.id),
#             "company_name": company.name,
#             "markdown": markdown_doc.markdown,
#             "generated_at": markdown_doc.generated_at,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching company markdown: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/company/{company_id}/report-html")
# async def get_company_report_html(company_id: str):
#     """Get the rendered HTML report for a company using Jinja templates."""
#     try:
#         company = get_company_by_id(company_id)
#         markdown_doc = FinalMarkdown.objects(company_id=company).first()

#         if not markdown_doc:
#             raise HTTPException(
#                 status_code=404, detail="No report found for this company"
#             )

#         # Convert markdown to HTML
#         html_body = markdown.markdown(
#             markdown_doc.markdown, extensions=["tables", "fenced_code"]
#         )

#         # Load images
#         def load_image_base64(path):
#             try:
#                 with open(path, "rb") as f:
#                     return (
#                         f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
#                     )
#             except Exception as e:
#                 logger.warning(f"Failed to load image {path}: {e}")
#                 return None

#         axis_logo_data = load_image_base64("assets/axis_logo.png")
#         company_logo_data = load_image_base64("assets/Pine Labs_logo.png")  # Default
#         front_header_data = load_image_base64("assets/front_header.png")

#         # Try to load company-specific logo
#         company_logo_path = f"assets/{company.name.replace(' ', '_')}_logo.png"
#         if os.path.exists(company_logo_path):
#             company_logo_data = load_image_base64(company_logo_path)

#         # Setup Jinja2 environment
#         env = Environment(loader=FileSystemLoader("templates"))

#         # Prepare context
#         context = {
#             "company_name": company.name.upper(),
#             "document_date": datetime.today().strftime("%B %Y"),
#             "company_logo_data": company_logo_data,
#             "axis_logo_data": axis_logo_data,
#             "front_header_data": front_header_data,
#             "content": html_body,
#         }

#         # Render HTML
#         front_html = env.get_template("front_page.html").render(context)
#         content_html = env.get_template("content_page.html").render(context)
#         full_html = front_html + content_html

#         return {
#             "company_id": str(company.id),
#             "company_name": company.name,
#             "html": full_html,
#             "generated_at": markdown_doc.generated_at,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error generating HTML report: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.delete("/companies/{company_id}")
# async def delete_company(company_id: str):
#     """Delete a company and all its associated data."""
#     try:
#         company = get_company_by_id(company_id)

#         # Delete related data
#         Page.objects(company_id=company).delete()
#         ChecklistOutput.objects(company_id=company).delete()
#         FinalMarkdown.objects(company_id=company).delete()

#         # Delete Qdrant collection
#         try:
#             qdrant_collection = f"drhp_notes_{company.name.replace(' ', '_').upper()}"
#             client = QdrantClient(url=os.getenv("QDRANT_URL"))
#             if qdrant_collection in [
#                 c.name for c in client.get_collections().collections
#             ]:
#                 client.delete_collection(collection_name=qdrant_collection)
#         except Exception as e:
#             logger.warning(f"Failed to delete Qdrant collection: {e}")

#         # Delete company
#         company.delete()

#         return {
#             "message": f"Company {company.name} and all associated data deleted successfully"
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error deleting company: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/companies/{company_id}/report", response_model=ReportResponse)
# async def get_company_report(company_id: str):
#     """Get the final generated report for a company."""
#     try:
#         company = get_company_by_id(company_id)
#         markdown_doc = FinalMarkdown.objects(company_id=company).first()

#         if not markdown_doc:
#             raise HTTPException(
#                 status_code=404, detail="No report found for this company"
#             )

#         return ReportResponse(
#             company_id=str(company.id),
#             company_name=company.name,
#             markdown=markdown_doc.markdown,
#             generated_at=markdown_doc.generated_at,
#         )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching company report: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/companies/{company_id}/markdown")
# async def get_company_markdown_companies(company_id: str):
#     """Get raw markdown content for a company."""
#     try:
#         company = get_company_by_id(company_id)
#         markdown_doc = FinalMarkdown.objects(company_id=company).first()

#         if not markdown_doc:
#             raise HTTPException(
#                 status_code=404, detail="No markdown found for this company"
#             )

#         return {
#             "company_id": str(company.id),
#             "company_name": company.name,
#             "markdown": markdown_doc.markdown,
#             "generated_at": markdown_doc.generated_at,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching company markdown: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.get("/companies/{company_id}/report-html")
# async def get_company_report_html_companies(company_id: str):
#     """
#     Renders markdown content using HTML templates with CSS styling.
#     Returns complete HTML document with embedded CSS for web display.
#     Called by frontend when user selects a company to view the report.
#     """
#     try:
#         logger.info(f"Fetching HTML report for company ID: {company_id}")

#         # Check if company exists
#         try:
#             company = get_company_by_id(company_id)
#             logger.info(f"Company found: {company.name}")
#         except HTTPException as e:
#             logger.error(f"Company not found for ID {company_id}: {e.detail}")
#             raise HTTPException(
#                 status_code=404, detail=f"Company with ID {company_id} not found"
#             )

#         # Check if markdown exists
#         markdown_doc = FinalMarkdown.objects(company_id=company).first()
#         if not markdown_doc:
#             logger.error(
#                 f"No markdown found for company {company.name} (ID: {company_id})"
#             )
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No report found for company {company.name}. The company may not have completed processing yet.",
#             )

#         logger.info(
#             f"Markdown found for company {company.name}, generating HTML report"
#         )

#         # Convert markdown to HTML
#         html_body = markdown.markdown(
#             markdown_doc.markdown, extensions=["tables", "fenced_code"]
#         )

#         # Load images with better error handling
#         def load_image_base64(path):
#             try:
#                 if os.path.exists(path):
#                     with open(path, "rb") as f:
#                         return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
#                 else:
#                     logger.warning(f"Image file not found: {path}")
#                     return None
#             except Exception as e:
#                 logger.warning(f"Failed to load image {path}: {e}")
#                 return None

#         # Load default images
#         axis_logo_data = load_image_base64("assets/axis_logo.png")
#         company_logo_data = load_image_base64("assets/Pine Labs_logo.png")  # Default
#         front_header_data = load_image_base64("assets/front_header.png")

#         # Try to load company-specific logo
#         company_logo_path = f"assets/{company.name.replace(' ', '_')}_logo.png"
#         if os.path.exists(company_logo_path):
#             company_logo_data = load_image_base64(company_logo_path)
#             logger.info(f"Loaded company-specific logo: {company_logo_path}")
#         else:
#             logger.info(
#                 f"Company-specific logo not found: {company_logo_path}, using default"
#             )

#         # Setup Jinja2 environment
#         env = Environment(loader=FileSystemLoader("templates"))

#         # Prepare context
#         context = {
#             "company_name": company.name.upper(),
#             "document_date": datetime.today().strftime("%B %Y"),
#             "company_logo_data": company_logo_data,
#             "axis_logo_data": axis_logo_data,
#             "front_header_data": front_header_data,
#             "content": html_body,
#         }

#         # Render HTML
#         front_html = env.get_template("front_page.html").render(context)
#         content_html = env.get_template("content_page.html").render(context)
#         full_html = front_html + content_html

#         logger.info(f"Successfully generated HTML report for company {company.name}")

#         return {
#             "company_id": str(company.id),
#             "company_name": company.name,
#             "html": full_html,
#             "generated_at": markdown_doc.generated_at,
#         }

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error generating HTML report for company {company_id}: {e}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"Internal server error while generating HTML report: {str(e)}",
#         )


# @app.post("/companies/{company_id}/regenerate")
# async def regenerate_company_report(company_id: str):
#     """Re-run the AI processing steps for an existing company."""
#     try:
#         company = get_company_by_id(company_id)

#         # Delete existing checklist outputs and markdown
#         ChecklistOutput.objects(company_id=company).delete()
#         FinalMarkdown.objects(company_id=company).delete()

#         # Update status
#         update_company_status(company_id, "PROCESSING")

#         async def regenerate_stream():
#             try:
#                 yield generate_sse_event(
#                     {
#                         "status": "PROCESSING",
#                         "step": "regenerating",
#                         "message": "Starting regeneration process...",
#                     }
#                 )

#                 # Get Qdrant collection name
#                 qdrant_collection = (
#                     f"drhp_notes_{company.name.replace(' ', '_').upper()}"
#                 )

#                 # Process checklist
#                 yield generate_sse_event(
#                     {
#                         "status": "PROCESSING",
#                         "step": "processing_checklist",
#                         "message": "Processing checklist and generating AI outputs...",
#                     }
#                 )

#                 checklist_path = os.path.join(
#                     os.path.dirname(__file__),
#                     "DRHP_crud_backend",
#                     "Checklists",
#                     "IPO_Notes_Checklist_AI_Final_prod_updated.xlsx",
#                 )

#                 checklist_name = os.path.basename(checklist_path)
#                 note_processor = DRHPNoteChecklistProcessor(
#                     checklist_path, qdrant_collection, str(company.id), checklist_name
#                 )
#                 note_processor.process()

#                 yield generate_sse_event(
#                     {
#                         "status": "PROCESSING",
#                         "step": "checklist_processed",
#                         "message": "Checklist processing completed",
#                     }
#                 )

#                 # Generate markdown
#                 yield generate_sse_event(
#                     {
#                         "status": "PROCESSING",
#                         "step": "generating_markdown",
#                         "message": "Generating final markdown report...",
#                     }
#                 )

#                 rows = ChecklistOutput.objects(company_id=company).order_by("row_index")

#                 md_lines = []
#                 for row in rows:
#                     topic = row.topic or ""
#                     ai_output = row.ai_output or ""
#                     commentary = row.commentary or ""

#                     heading_md = f"**{topic}**" if topic else ""
#                     commentary_md = (
#                         f'<span style="font-size:10px;"><i>AI Commentary : {commentary}</i></span>'
#                         if commentary
#                         else ""
#                     )

#                     md_lines.append(
#                         f"{heading_md}\n\n{ai_output}\n\n{commentary_md}\n\n"
#                     )

#                 markdown_content = "".join(md_lines)

#                 # Save final markdown
#                 FinalMarkdown.objects(company_id=company).update_one(
#                     set__company_name=company.name,
#                     set__markdown=markdown_content,
#                     set__generated_at=datetime.utcnow(),
#                     upsert=True,
#                 )

#                 # Update company status
#                 Company.objects(id=company.id).update_one(
#                     set__processing_status="COMPLETED", set__has_markdown=True
#                 )

#                 yield generate_sse_event(
#                     {
#                         "status": "COMPLETED",
#                         "step": "final",
#                         "message": "Report regeneration completed successfully",
#                         "markdown": markdown_content,
#                     }
#                 )

#             except Exception as e:
#                 logger.error(f"Regeneration error: {e}")
#                 update_company_status(company_id, "FAILED")
#                 yield generate_sse_event(
#                     {
#                         "status": "FAILED",
#                         "step": "error",
#                         "message": f"Regeneration failed: {str(e)}",
#                     }
#                 )

#         return StreamingResponse(
#             regenerate_stream(),
#             media_type="text/event-stream",
#             headers={
#                 "Cache-Control": "no-cache",
#                 "Connection": "keep-alive",
#                 "Access-Control-Allow-Origin": "*",
#                 "Access-Control-Allow-Headers": "*",
#             },
#         )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error in regenerate_company_report: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.post("/reports/generate-pdf")
# async def generate_pdf_report(request: PDFGenerationRequest):
#     """Convert markdown content to PDF with company branding and upload to Azure Blob Storage."""
#     try:
#         # Create output directory
#         output_dir = "output"
#         os.makedirs(output_dir, exist_ok=True)

#         # Setup Jinja2 environment
#         env = Environment(loader=FileSystemLoader("templates"))

#         # Convert markdown to HTML
#         html_body = markdown.markdown(
#             request.markdown_content, extensions=["tables", "fenced_code"]
#         )

#         # Load images
#         def load_image_base64(path):
#             try:
#                 with open(path, "rb") as f:
#                     return (
#                         f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
#                     )
#             except Exception as e:
#                 logger.warning(f"Failed to load image {path}: {e}")
#                 return None

#         axis_logo_data = load_image_base64("assets/axis_logo.png")
#         company_logo_data = load_image_base64("assets/Pine Labs_logo.png")  # Default
#         front_header_data = load_image_base64("assets/front_header.png")

#         # Try to load company-specific logo
#         company_logo_path = f"assets/{request.company_name.replace(' ', '_')}_logo.png"
#         if os.path.exists(company_logo_path):
#             company_logo_data = load_image_base64(company_logo_path)

#         # Prepare context
#         context = {
#             "company_name": request.company_name.upper(),
#             "document_date": datetime.today().strftime("%B %Y"),
#             "company_logo_data": company_logo_data,
#             "axis_logo_data": axis_logo_data,
#             "front_header_data": front_header_data,
#             "content": html_body,
#         }

#         # Render HTML
#         front_html = env.get_template("front_page.html").render(context)
#         content_html = env.get_template("content_page.html").render(context)
#         full_html = front_html + content_html

#         # Generate PDF filename
#         safe_company_name = (
#             request.company_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
#         )
#         pdf_filename = f"{safe_company_name}_IPO_Notes.pdf"
#         pdf_path = os.path.join(output_dir, pdf_filename)

#         # Generate PDF
#         html_doc = HTML(string=full_html, base_url=".")
#         css_doc = CSS(filename="styles/styles.css")
#         html_doc.write_pdf(pdf_path, stylesheets=[css_doc])

#         logger.info(f"PDF generated: {pdf_path}")

#         # Upload generated PDF to Azure Blob Storage
#         blob_storage = get_blob_storage()
#         blob_name = f"reports/{pdf_filename}"
#         try:
#             blob_url = blob_storage.upload_file(pdf_path, blob_name)
#             logger.info(f"Generated PDF uploaded to Azure Blob Storage: {blob_url}")
#         except Exception as e:
#             logger.error(f"Failed to upload generated PDF to Azure Blob Storage: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Failed to upload generated PDF to Azure Blob Storage: {e}",
#             )

#         return FileResponse(
#             pdf_path,
#             media_type="application/pdf",
#             filename=pdf_filename,
#             headers={"Content-Disposition": f"attachment; filename={pdf_filename}"},
#         )

#     except Exception as e:
#         logger.error(f"Error generating PDF: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")


# @app.post("/generate-report-pdf/")
# async def generate_report_pdf(request: PDFGenerationRequest):
#     """Generate PDF from markdown content (alternative endpoint)."""
#     try:
#         # Create output directory
#         output_dir = "output"
#         os.makedirs(output_dir, exist_ok=True)

#         # Setup Jinja2 environment
#         env = Environment(loader=FileSystemLoader("templates"))

#         # Convert markdown to HTML
#         html_body = markdown.markdown(
#             request.markdown_content, extensions=["tables", "fenced_code"]
#         )

#         # Load images
#         def load_image_base64(path):
#             try:
#                 with open(path, "rb") as f:
#                     return (
#                         f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
#                     )
#             except Exception as e:
#                 logger.warning(f"Failed to load image {path}: {e}")
#                 return None

#         axis_logo_data = load_image_base64("assets/axis_logo.png")
#         company_logo_data = load_image_base64("assets/Pine Labs_logo.png")  # Default
#         front_header_data = load_image_base64("assets/front_header.png")

#         # Try to load company-specific logo
#         company_logo_path = f"assets/{request.company_name.replace(' ', '_')}_logo.png"
#         if os.path.exists(company_logo_path):
#             company_logo_data = load_image_base64(company_logo_path)

#         # Prepare context
#         context = {
#             "company_name": request.company_name.upper(),
#             "document_date": datetime.today().strftime("%B %Y"),
#             "company_logo_data": company_logo_data,
#             "axis_logo_data": axis_logo_data,
#             "front_header_data": front_header_data,
#             "content": html_body,
#         }

#         # Render HTML
#         front_html = env.get_template("front_page.html").render(context)
#         content_html = env.get_template("content_page.html").render(context)
#         full_html = front_html + content_html

#         # Generate PDF filename
#         safe_company_name = (
#             request.company_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
#         )
#         pdf_filename = f"{safe_company_name}_IPO_Notes.pdf"
#         pdf_path = os.path.join(output_dir, pdf_filename)

#         # Generate PDF
#         html_doc = HTML(string=full_html, base_url=".")
#         css_doc = CSS(filename="styles/styles.css")
#         html_doc.write_pdf(pdf_path, stylesheets=[css_doc])

#         return FileResponse(
#             pdf_path,
#             media_type="application/pdf",
#             filename=pdf_filename,
#             headers={"Content-Disposition": f"attachment; filename={pdf_filename}"},
#         )

#     except Exception as e:
#         logger.error(f"Error generating PDF: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")


# @app.post("/assets/logos", response_model=LogoUploadResponse)
# async def upload_logo(file: UploadFile = File(...)):
#     """Upload a logo image to Azure Blob Storage."""
#     try:
#         # Validate file type
#         if not file.content_type.startswith("image/"):
#             raise HTTPException(status_code=400, detail="Only image files are allowed")

#         # Generate unique filename
#         import uuid

#         logo_id = str(uuid.uuid4())
#         file_extension = os.path.splitext(file.filename)[1]
#         filename = f"{logo_id}{file_extension}"
#         blob_name = f"logos/{filename}"

#         # Upload logo to Azure Blob Storage
#         blob_storage = get_blob_storage()
#         try:
#             blob_url = blob_storage.upload_data(file.file, blob_name)
#             logger.info(f"Logo uploaded to Azure Blob Storage: {blob_url}")
#         except Exception as e:
#             logger.error(f"Failed to upload logo to Azure Blob Storage: {e}")
#             raise HTTPException(
#                 status_code=500,
#                 detail=f"Failed to upload logo to Azure Blob Storage: {e}",
#             )

#         return LogoUploadResponse(logo_id=logo_id, filename=filename, path=blob_url)

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error uploading logo: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.put("/companies/{company_id}/logo")
# async def associate_company_logo(company_id: str, logo_id: str):
#     """Associate a logo with a company."""
#     try:
#         company = get_company_by_id(company_id)
#         # In a real implementation, you would store the logo association
#         # For now, we'll just return success
#         return {"message": f"Logo {logo_id} associated with company {company.name}"}

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error associating logo: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.post("/company/{company_id}/cancel-processing")
# async def cancel_company_processing(company_id: str):
#     """Cancel processing for a company."""
#     try:
#         company = get_company_by_id(company_id)

#         # Update status to cancelled
#         Company.objects(id=company.id).update_one(set__processing_status="CANCELLED")

#         return {"message": f"Processing cancelled for company {company.name}"}

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error cancelling company processing: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# @app.put("/config/entity-assets")
# async def set_entity_assets(request: AssetConfigRequest):
#     """Set global entity assets configuration."""
#     try:
#         # In a real implementation, you would store this configuration
#         # For now, we'll just return success
#         return {
#             "message": "Entity assets configuration updated",
#             "entity_logo_id": request.entity_logo_id,
#             "front_header_id": request.front_header_id,
#         }

#     except Exception as e:
#         logger.error(f"Error setting entity assets: {e}")
#         raise HTTPException(status_code=500, detail="Internal server error")


# # --- Health Check Endpoint ---
# @app.get("/health")
# async def health_check():
#     """Health check endpoint."""
#     return {"status": "healthy", "timestamp": datetime.utcnow()}


# @app.get("/debug/companies")
# async def debug_companies():
#     """Debug endpoint to check companies and their markdown status."""
#     try:
#         companies = Company.objects.all()
#         markdown_docs = FinalMarkdown.objects.all()

#         company_data = []
#         for company in companies:
#             markdown_exists = (
#                 FinalMarkdown.objects(company_id=company).first() is not None
#             )
#             company_data.append(
#                 {
#                     "id": str(company.id),
#                     "name": company.name,
#                     "corporate_identity_number": company.corporate_identity_number,
#                     "processing_status": company.processing_status,
#                     "has_markdown": markdown_exists,
#                     "created_at": (
#                         company.created_at.isoformat() if company.created_at else None
#                     ),
#                 }
#             )

#         return {
#             "total_companies": len(company_data),
#             "total_markdown_docs": len(markdown_docs),
#             "companies": company_data,
#         }
#     except Exception as e:
#         logger.error(f"Error in debug endpoint: {e}")
#         raise HTTPException(status_code=500, detail=f"Debug error: {str(e)}")


# def load_image_base64(path):
#     """Load image and convert to base64"""
#     try:
#         if os.path.exists(path):
#             with open(path, "rb") as f:
#                 return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
#         else:
#             logger.warning(f"Image not found: {path}")
#             return ""
#     except Exception as e:
#         logger.warning(f"Failed to load image {path}: {e}")
#         return ""


# def render_template(env, template_name, context):
#     """Render Jinja2 template with context"""
#     return env.get_template(template_name).render(context)


# def get_company_logo_path(company_name: str) -> str:
#     """Return the logo path from assets based on company name (demo mapping)."""
#     name = company_name.strip().lower()
#     if "neilsoft" in name:
#         return "assets/NEILSOFT LIMITED_logo.png"
#     elif "wakefit" in name:
#         return "assets/WAKEFIT INNOVATIONS LIMITED_logo.png"
#     elif "ather" in name:
#         return "assets/ATHER_logo.png"
#     elif "pine labs" in name:
#         return "assets/Pine Labs_logo.png"
#     elif "swiggy" in name:
#         return "assets/SWIGGY LIMITED_logo.png"
#     elif "anthem" in name:
#         return "assets/ANTHEM_logo.png"
#     elif "capillary" in name:
#         return "assets/CAPILLARY TECHNOLOGIES INDIA LIMITED_logo.png"
#     elif "quailty" in name:
#         return "assets/QUALITY POWER_logo.png"
#     else:
#         logger.warning(f"No specific logo found for {company_name}, using default")
#         return ""


# def generate_pdf_from_markdown(markdown_content: str, company_name: str) -> str:
#     """Generate PDF from markdown content"""
#     try:
#         # Setup Jinja2 environment
#         env = Environment(loader=FileSystemLoader("templates"))

#         # Convert Markdown to HTML
#         html_body = markdown.markdown(
#             markdown_content, extensions=["tables", "fenced_code"]
#         )

#         # Load images
#         axis_logo_data = load_image_base64("assets/axis_logo.png")
#         company_logo_path = get_company_logo_path(company_name)
#         company_logo_data = load_image_base64(company_logo_path)
#         front_header_data = load_image_base64("assets/front_header.png")

#         # Prepare dynamic context
#         context = {
#             "company_name": company_name.upper(),
#             "document_date": datetime.today().strftime("%B %Y"),
#             "company_logo_data": company_logo_data,
#             "axis_logo_data": axis_logo_data,
#             "front_header_data": front_header_data,
#             "content": html_body,
#         }

#         # Render full HTML
#         front_html = render_template(env, "front_page.html", context)
#         content_html = render_template(env, "content_page.html", context)
#         full_html = front_html + content_html

#         # Create temporary file for PDF
#         temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
#         temp_path = temp_file.name
#         temp_file.close()

#         # Generate PDF
#         html_doc = HTML(string=full_html, base_url=".")
#         css_doc = CSS(filename="styles/styles.css")
#         html_doc.write_pdf(temp_path, stylesheets=[css_doc])

#         logger.info(f"✅ PDF generated for {company_name}")
#         return temp_path

#     except Exception as e:
#         logger.error(f"❌ Error generating PDF: {e}")
#         raise HTTPException(status_code=500, detail=f"Error generating PDF: {str(e)}")


# @app.get("/report/{company_id}")
# async def get_final_report(company_id: str, format: str = "pdf"):
#     """
#     Get final report for a company by ID

#     Args:
#         company_id: The company ID (ObjectId as string)
#         format: Output format (pdf, html, markdown)

#     Returns:
#         The report in the requested format
#     """
#     try:
#         logger.info(
#             f"Fetching final report for company ID: {company_id}, format: {format}"
#         )

#         # Validate company_id format
#         try:
#             from bson import ObjectId

#             object_id = ObjectId(company_id)
#         except Exception as e:
#             logger.error(f"Invalid company ID format: {company_id}")
#             raise HTTPException(
#                 status_code=400, detail=f"Invalid company ID format: {company_id}"
#             )

#         # Get company and markdown
#         try:
#             company = get_company_by_id(company_id)
#             logger.info(f"Company found: {company.name}")
#         except HTTPException as e:
#             logger.error(f"Company not found for ID {company_id}: {e.detail}")
#             raise HTTPException(
#                 status_code=404, detail=f"Company with ID {company_id} not found"
#             )

#         # Get markdown document
#         markdown_doc = FinalMarkdown.objects(company_id=company).first()
#         if not markdown_doc:
#             logger.error(
#                 f"No markdown found for company {company.name} (ID: {company_id})"
#             )
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No report found for company {company.name}. The company may not have completed processing yet.",
#             )

#         company_name = markdown_doc.company_name or company.name
#         markdown_content = markdown_doc.markdown

#         if not markdown_content:
#             logger.error(f"Empty markdown content for company {company.name}")
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"No markdown content found for company {company.name}",
#             )

#         logger.info(f"✅ Found markdown for company {company_id}: {company_name}")

#         # Return based on requested format
#         if format.lower() == "markdown":
#             return {
#                 "company_id": company_id,
#                 "company_name": company_name,
#                 "content": markdown_content,
#                 "format": "markdown",
#             }

#         elif format.lower() == "html":
#             html_content = markdown.markdown(
#                 markdown_content, extensions=["tables", "fenced_code"]
#             )
#             return {
#                 "company_id": company_id,
#                 "company_name": company_name,
#                 "content": html_content,
#                 "format": "html",
#             }

#         elif format.lower() == "pdf":
#             # Generate PDF
#             pdf_path = generate_pdf_from_markdown(markdown_content, company_name)

#             # Generate safe filename
#             safe_company_name = (
#                 company_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
#             )
#             pdf_filename = f"{safe_company_name}_ipo_notes.pdf"

#             # Return PDF file
#             return FileResponse(
#                 path=pdf_path,
#                 media_type="application/pdf",
#                 filename=pdf_filename,
#                 headers={"Content-Disposition": f"attachment; filename={pdf_filename}"},
#             )

#         else:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Invalid format. Supported formats: pdf, html, markdown",
#             )

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"❌ Error processing request for company {company_id}: {e}")
#         raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run(app, host="0.0.0.0", port=8000)

import os
import sys
import logging
import warnings
import tempfile
import base64
import markdown
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, APIRouter, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from dotenv import load_dotenv
from pydantic import BaseModel
from mongoengine import (
    Document,
    StringField,
    DateTimeField,
    IntField,
    ListField,
    ReferenceField,
    BooleanField,
    DoesNotExist,
    connect, disconnect
)
from bson import ObjectId
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
import pytz

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ["LITELLM_LOG"] = "ERROR"
os.environ["OPENAI_LOG"] = "ERROR"
os.environ["URLLIB3_DISABLE_WARNINGS"] = "1"
os.environ["PYTHONWARNINGS"] = "ignore"

# Load environment variables
load_dotenv()

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Set custom formatter for all handlers
for handler in logging.root.handlers:
    handler.setFormatter(ISTFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

logger = logging.getLogger("DRHP_FastAPI")

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


class CompanyDetail(BaseModel):
    id: str
    name: str
    corporate_identity_number: str
    website_link: Optional[str] = None
    created_at: datetime
    processing_status: str
    has_markdown: bool
    pages_count: int
    checklist_outputs_count: int
    markdown: Optional[str] = None


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


class ProcessingStatusResponse(BaseModel):
    company_id: str
    processing_status: str
    pages_done: bool
    qdrant_done: bool
    checklist_done: bool
    markdown_done: bool
    overall_status: str


class UploadResponse(BaseModel):
    success: bool
    message: str
    filename: Optional[str] = None
    temp_path: Optional[str] = None


class GenerateNotesRequest(BaseModel):
    temp_path: str


class ErrorResponse(BaseModel):
    success: bool
    error: str

# --- MongoEngine Models ---
class Company(Document):
    meta = {"db_alias": "core", "collection": "company"}
    name = StringField(required=True)
    corporate_identity_number = StringField(required=True, unique=True)
    drhp_file_url = StringField()
    website_link = StringField()
    created_at = DateTimeField(default=datetime.utcnow)
    processing_status = StringField(default="PENDING")
    has_markdown = BooleanField(default=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'name': self.name,
            'corporate_identity_number': self.corporate_identity_number,
            'drhp_file_url': self.drhp_file_url,
            'website_link': self.website_link,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processing_status': self.processing_status,
            'has_markdown': self.has_markdown
        }


class Page(Document):
    meta = {"db_alias": "core", "collection": "pages"}
    company_id = ReferenceField(Company, required=True)
    page_number_pdf = IntField(required=True)
    page_number_drhp = IntField()
    page_content = StringField()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'company_id': str(self.company_id.id) if self.company_id else None,
            'page_number_pdf': self.page_number_pdf,
            'page_number_drhp': self.page_number_drhp,
            'page_content': self.page_content
        }


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'company_id': str(self.company_id.id) if self.company_id else None,
            'checklist_name': self.checklist_name,
            'row_index': self.row_index,
            'topic': self.topic,
            'section': self.section,
            'ai_prompt': self.ai_prompt,
            'ai_output': self.ai_output,
            'citations': self.citations,
            'commentary': self.commentary,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class FinalMarkdown(Document):
    meta = {"db_alias": "core", "collection": "final_markdown"}
    company_id = ReferenceField(Company, required=True)
    company_name = StringField(required=True)
    markdown = StringField(required=True)
    generated_at = DateTimeField(default=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'company_id': str(self.company_id.id) if self.company_id else None,
            'company_name': self.company_name,
            'markdown': self.markdown,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }

# --- Utility Functions ---
def validate_env():
    """Validate required environment variables."""
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
    MONGODB_URI = os.getenv("DRHP_MONGODB_URI")
    DB_NAME = os.getenv("DRHP_DB_NAME", "DRHP_NOTES")

    try:
        disconnect(alias="core")
        connect(alias="core", host=MONGODB_URI, db=DB_NAME)
        logger.info(f"Connected to MongoDB at {MONGODB_URI}, DB: {DB_NAME}")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        raise


def disconnect_from_db():
    """Disconnect from MongoDB database."""
    try:
        disconnect(alias="core")
        logger.info("Disconnected from MongoDB")
    except Exception as e:
        logger.error(f"MongoDB disconnection error: {e}")
        raise


def get_company_by_id(company_id: str) -> Company:
    """Get company by ID with proper error handling."""
    try:
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


def load_image_base64(path: str) -> str:
    """Load image and convert to base64 data URL."""
    try:
        # Adjust path to be relative to the current script's directory
        script_dir = os.path.dirname(__file__)
        full_path = os.path.join(script_dir, path)

        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
        else:
            logger.warning(f"Image file not found: {full_path}")
            return ""
    except Exception as e:
        logger.warning(f"Failed to load image {path}: {e}")
        return ""


def get_company_logo_path(company_name: str) -> str:
    """Return the logo path from assets based on company name."""
    name = company_name.strip().lower()
    logo_mappings = {
        "neilsoft": "assets/NEILSOFT LIMITED_logo.png",
        "wakefit": "assets/WAKEFIT INNOVATIONS LIMITED_logo.png",
        "ather": "assets/ATHER_logo.png",
        "pine labs": "assets/Pine Labs_logo.png",
        "swiggy": "assets/SWIGGY LIMITED_logo.png",
        "anthem": "assets/ANTHEM_logo.png",
        "capillary": "assets/CAPILLARY TECHNOLOGIES INDIA LIMITED_logo.png",
        "quality": "assets/QUALITY POWER_logo.png",
    }
    
    for key, path in logo_mappings.items():
        if key in name:
            return path
    
    logger.warning(f"No specific logo found for {company_name}, using default")
    return "assets/Pine Labs_logo.png"  # Default logo


def save_page_safe(company_doc: Company, page_no: str, page_info: Dict[str, Any]):
    """Safely save a page to the database."""
    try:
        # Check for duplicate page
        if Page.objects(company_id=company_doc, page_number_pdf=int(page_no)).first():
            logger.info(
                f"Page {page_no} already exists for company {company_doc.name}, skipping."
            )
            return True

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
        
        return True
    except Exception as e:
        logger.error(f"Failed to save page {page_no}: {e}")
        return False


def generate_markdown_for_company(company_id: str, company_name: str) -> str:
    """Generate markdown content from checklist outputs."""
    try:
        company = get_company_by_id(company_id)
        rows = (
            ChecklistOutput.objects(company_id=company)
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
        
        return "".join(md_lines)
    except Exception as e:
        logger.error(f"Error generating markdown for company {company_id}: {e}")
        raise


def save_final_markdown(company_id: str, company_name: str, markdown: str):
    """Save final markdown to database."""
    try:
        company = get_company_by_id(company_id)
        FinalMarkdown.objects(company_id=company).update_one(
            set__company_name=company_name, 
            set__markdown=markdown,
            set__generated_at=datetime.utcnow(),
            upsert=True
        )
        logger.info(
            f"Saved markdown for {company_name} ({company_id}) to final_markdown collection."
        )
    except Exception as e:
        logger.error(f"Error saving final markdown: {e}")
        raise

# --- FastAPI App Initialization ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup
    try:
        logger.info("Starting DRHP FastAPI application...")
        validate_env()
        connect_to_db()
        logger.info("Application startup completed successfully")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    try:
        logger.info("Shutting down DRHP FastAPI application...")
        disconnect_from_db()
        logger.info("Application shutdown completed successfully")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


# Create FastAPI app
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

# --- API Routers ---
companies_router = APIRouter(prefix="/api", tags=["companies"])
reports_router = APIRouter(prefix="/api", tags=["reports"])

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf'}

def allowed_file(filename: str) -> bool:
    """Check if file has allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Companies Endpoints ---
@companies_router.get("/companies", response_model=List[CompanyResponse])
async def get_companies():
    """Get all companies with their status."""
    try:
        companies = Company.objects.all().order_by("-created_at")
        companies_data = []
        
        for company in companies:
            stats = get_company_stats(company)
            
            # Determine status based on markdown existence
            status = 'Completed' if stats['has_markdown'] else company.processing_status
            
            companies_data.append(CompanyResponse(
                id=str(company.id),
                name=company.name,
                corporate_identity_number=company.corporate_identity_number,
                website_link=company.website_link,
                created_at=company.created_at,
                processing_status=status,
                has_markdown=stats['has_markdown'],
                pages_count=stats['pages_count'],
                checklist_outputs_count=stats['checklist_outputs_count']
            ))
        
        return companies_data
        
    except Exception as e:
        logger.error(f"Error getting companies: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve companies'
        )


@companies_router.get("/companies/{company_id}", response_model=CompanyDetail)
async def get_company_details(company_id: str):
    """Get detailed information about a specific company."""
    try:
        company = get_company_by_id(company_id)
        stats = get_company_stats(company)
        
        # Get markdown if exists
        markdown_doc = FinalMarkdown.objects(company_id=company).first()
        markdown_content = markdown_doc.markdown if markdown_doc else None
        
        return CompanyDetail(
            id=str(company.id),
            name=company.name,
            corporate_identity_number=company.corporate_identity_number,
            website_link=company.website_link,
            created_at=company.created_at,
            processing_status=company.processing_status,
            has_markdown=stats['has_markdown'],
            pages_count=stats['pages_count'],
            checklist_outputs_count=stats['checklist_outputs_count'],
            markdown=markdown_content
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting company details: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to retrieve company details'
        )


@companies_router.post("/upload", response_model=UploadResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """Upload and process a DRHP PDF."""
    try:
        # Check if file is present
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail='No file selected'
            )
        
        if not allowed_file(file.filename):
            raise HTTPException(
                status_code=400,
                detail='Only PDF files are allowed'
            )
        
        # Save file temporarily
        temp_dir = tempfile.mkdtemp()
        temp_path = os.path.join(temp_dir, file.filename)
        
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        return UploadResponse(
            success=True,
            message='File uploaded successfully',
            filename=file.filename,
            temp_path=temp_path
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to upload file'
        )


@companies_router.post("/generate-notes")
async def generate_notes(request: GenerateNotesRequest):
    """Generate IPO notes for uploaded PDF."""
    try:
        temp_path = request.temp_path
        
        if not os.path.exists(temp_path):
            raise HTTPException(
                status_code=404,
                detail='File not found'
            )
        
        # TODO: Integrate with the main processing pipeline
        # This would call the main() function from the original code
        
        return {
            'success': True,
            'message': 'IPO notes generation started',
            'status': 'processing'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating notes: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to generate notes'
        )


@companies_router.post("/companies/{company_id}/regenerate")
async def regenerate_notes(company_id: str):
    """Regenerate IPO notes for an existing company."""
    try:
        company = get_company_by_id(company_id)
        
        # Delete existing checklist outputs and markdown
        ChecklistOutput.objects(company_id=company).delete()
        FinalMarkdown.objects(company_id=company).delete()
        
        # Update status
        update_company_status(company_id, "PROCESSING")
        
        async def regenerate_stream():
            try:
                yield generate_sse_event({
                    'status': 'PROCESSING',
                    'step': 'regenerating',
                    'message': 'Starting regeneration process...'
                })
                
                # TODO: Implement regeneration logic
                # This would call rerun_checklist_for_company() from the original code
                
                yield generate_sse_event({
                    'status': 'COMPLETED',
                    'step': 'final',
                    'message': f'Regeneration completed for {company.name}'
                })
                
            except Exception as e:
                logger.error(f"Regeneration error: {e}")
                update_company_status(company_id, "FAILED")
                yield generate_sse_event({
                    'status': 'FAILED',
                    'step': 'error',
                    'message': f'Regeneration failed: {str(e)}'
                })
        
        return StreamingResponse(
            regenerate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error regenerating notes: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to regenerate notes'
        )


@companies_router.delete("/companies/{company_id}")
async def delete_company(company_id: str):
    """Delete a company and all related data."""
    try:
        company = get_company_by_id(company_id)
        company_name = company.name
        
        # Delete related data
        Page.objects(company_id=company).delete()
        ChecklistOutput.objects(company_id=company).delete()
        FinalMarkdown.objects(company_id=company).delete()
        
        # Delete company
        company.delete()
        
        # TODO: Delete Qdrant collection
        # This would call delete_company_and_related_data() from the original code
        
        return {
            'success': True,
            'message': f'Company {company_name} deleted successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to delete company'
        )


@companies_router.post("/upload-logo")
async def upload_logo(file: UploadFile = File(...), logo_type: str = "company"):
    """Upload company or entity logo."""
    try:
        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail='No file selected'
            )
        
        # Check if file is an image
        allowed_image_extensions = {'png', 'jpg', 'jpeg', 'gif'}
        if not ('.' in file.filename and 
                file.filename.rsplit('.', 1)[1].lower() in allowed_image_extensions):
            raise HTTPException(
                status_code=400,
                detail='Only image files are allowed'
            )
        
        # Save logo file
        # TODO: Save to appropriate location (assets folder or cloud storage)
        
        return {
            'success': True,
            'message': f'{logo_type.title()} logo uploaded successfully',
            'filename': file.filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading logo: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to upload logo'
        )


@companies_router.get("/status/{company_id}", response_model=ProcessingStatusResponse)
async def get_processing_status(company_id: str):
    """Get processing status for a company."""
    try:
        company = get_company_by_id(company_id)
        stats = get_company_stats(company)
        
        # Check various stages of completion
        pages_done = stats['pages_count'] > 0
        checklist_done = stats['checklist_outputs_count'] > 0
        markdown_done = stats['has_markdown']
        
        # Determine overall status
        if markdown_done:
            overall_status = 'Completed'
        elif checklist_done:
            overall_status = 'Generating Markdown'
        elif pages_done:
            overall_status = 'Processing Checklist'
        else:
            overall_status = 'Extracting Content'
        
        return ProcessingStatusResponse(
            company_id=str(company.id),
            processing_status=company.processing_status,
            pages_done=pages_done,
            qdrant_done=pages_done,  # Assume Qdrant is done if pages exist
            checklist_done=checklist_done,
            markdown_done=markdown_done,
            overall_status=overall_status
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail='Failed to get status'
        )

# --- Reports Endpoints ---
@reports_router.get("/companies/{company_id}/report", response_model=ReportResponse)
async def get_company_report(company_id: str):
    """Get the final generated report for a company."""
    try:
        company = get_company_by_id(company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()

        if not markdown_doc:
            raise HTTPException(
                status_code=404, 
                detail="No report found for this company"
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
        raise HTTPException(
            status_code=500, 
            detail="Failed to retrieve company report"
        )


@reports_router.get("/companies/{company_id}/markdown")
async def get_company_markdown(company_id: str):
    """Get raw markdown content for a company."""
    try:
        company = get_company_by_id(company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()

        if not markdown_doc:
            raise HTTPException(
                status_code=404, 
                detail="No markdown found for this company"
            )

        return {
            "company_id": str(company.id),
            "company_name": company.name,
            "markdown": markdown_doc.markdown,
            "generated_at": markdown_doc.generated_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching company markdown: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to retrieve company markdown"
        )


@reports_router.get("/companies/{company_id}/report-html")
async def get_company_report_html(company_id: str):
    """
    Renders markdown content using HTML templates with CSS styling.
    Returns complete HTML document with embedded CSS for web display.
    """
    try:
        logger.info(f"Fetching HTML report for company ID: {company_id}")

        company = get_company_by_id(company_id)
        logger.info(f"Company found: {company.name}")

        # Check if markdown exists
        markdown_doc = FinalMarkdown.objects(company_id=company).first()
        if not markdown_doc:
            logger.error(
                f"No markdown found for company {company.name} (ID: {company_id})"
            )
            raise HTTPException(
                status_code=404,
                detail=f"No report found for company {company.name}. The company may not have completed processing yet.",
            )

        logger.info(
            f"Markdown found for company {company.name}, generating HTML report"
        )

        # Convert markdown to HTML
        html_body = markdown.markdown(
            markdown_doc.markdown, extensions=["tables", "fenced_code"]
        )

        # Load default images
        axis_logo_data = load_image_base64("assets/axis_logo.png")
        company_logo_path = get_company_logo_path(company.name)
        company_logo_data = load_image_base64(company_logo_path)
        front_header_data = load_image_base64("assets/front_header.png")

        if company_logo_data:
            logger.info(f"Loaded company logo: {company_logo_path}")
        else:
            logger.info(f"Company logo not found, using default")

        # Setup Jinja2 environment
        env = Environment(loader=FileSystemLoader("templates"))

        # Prepare context
        context = {
            "company_name": company.name.upper(),
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

        logger.info(f"Successfully generated HTML report for company {company.name}")

        return {
            "company_id": str(company.id),
            "company_name": company.name,
            "html": full_html,
            "generated_at": markdown_doc.generated_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating HTML report for company {company_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error while generating HTML report: {str(e)}",
        )


@reports_router.post("/generate-pdf")
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
        axis_logo_data = load_image_base64("assets/axis_logo.png")
        company_logo_path = get_company_logo_path(request.company_name)
        company_logo_data = load_image_base64(company_logo_path)
        front_header_data = load_image_base64("assets/front_header.png")

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

        logger.info(f"PDF generated: {pdf_path}")

        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=pdf_filename,
            headers={"Content-Disposition": f"attachment; filename={pdf_filename}"},
        )

    except Exception as e:
        logger.error(f"Error generating PDF: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to generate PDF: {str(e)}"
        )


@reports_router.get("/companies/{company_id}/download-pdf")
async def download_company_pdf(company_id: str):
    """Generate and download PDF report for a specific company."""
    try:
        company = get_company_by_id(company_id)
        markdown_doc = FinalMarkdown.objects(company_id=company).first()

        if not markdown_doc:
            raise HTTPException(
                status_code=404,
                detail="No report found for this company"
            )

        # Create PDF generation request
        pdf_request = PDFGenerationRequest(
            markdown_content=markdown_doc.markdown,
            company_name=company.name
        )

        # Generate PDF using the existing endpoint logic
        return await generate_pdf_report(pdf_request)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading company PDF: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to generate PDF report"
        )

# Mount static files (if needed)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "service": "DRHP FastAPI Backend"
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": "DRHP IPO Notes Generation API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Debug endpoint
@app.get("/debug/companies")
async def debug_companies():
    """Debug endpoint to check companies and their markdown status."""
    try:
        companies = Company.objects.all()
        markdown_docs = FinalMarkdown.objects.all()

        company_data = []
        for company in companies:
            markdown_exists = (
                FinalMarkdown.objects(company_id=company).first() is not None
            )
            company_data.append(
                {
                    "id": str(company.id),
                    "name": company.name,
                    "corporate_identity_number": company.corporate_identity_number,
                    "processing_status": company.processing_status,
                    "has_markdown": markdown_exists,
                    "created_at": (
                        company.created_at.isoformat() if company.created_at else None
                    ),
                }
            )

        return {
            "total_companies": len(company_data),
            "total_markdown_docs": len(markdown_docs),
            "companies": company_data,
        }
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Debug error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    
    # Run the application
    uvicorn.run(
        "api:app", # Changed from main:app to api:app
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )


