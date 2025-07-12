from fastapi import APIRouter, HTTPException, Header, Request, File, UploadFile, Depends
from app.services.auth_utils import login_required
from app.utils.helpers import UploadToBlob
from app.models.schemas import UploadedDRHP, User
import shutil
import os
import fitz  # PyMuPDF for PDF text extraction
from datetime import datetime
from pydantic import BaseModel
import instructor
import litellm
from litellm import completion
from dotenv import load_dotenv
from app.utils.log_to_s3 import log_to_s3, log_schema_changes
import logging
import boto3
# Configure logging
logger = logging.getLogger(__name__)
load_dotenv()

# Configure LiteLLM
litellm.drop_params = True

# Ensure AWS region is set for Bedrock
bedrock_region = os.environ.get("AWS_REGION_NAME", "ap-south-1")
os.environ["AWS_REGION"] = bedrock_region
logger.info(f"Using AWS region for Bedrock: {bedrock_region}")
bedrock_client = boto3.client('bedrock-runtime', region_name=bedrock_region)
litellm.aws_bedrock_client = bedrock_client
logger.info("Configured boto3 bedrock-runtime client for LiteLLM")
router = APIRouter()

class CompanyDetails(BaseModel):
    company_name: str
    corporate_identity_number: str

def extract_first_page_text(pdf_path: str) -> str:
    try:
        with fitz.open(pdf_path) as doc:
            first_page_text = doc[0].get_text("text")
        return first_page_text.strip()
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        return ""

def get_company_details(first_page_content: str) -> CompanyDetails:
    prompt = f"""
    You are a helpful assistant that extracts company details from the first page of a DRHP.
    The first page of a DRHP contains the following information:
    - Company Name
    - Corporate Identity Number

    Extract this information from the provided text.

    First Page Content:
    {first_page_content}
    """

    llm_client = instructor.from_litellm(completion)
    try:
        response = llm_client.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_model=CompanyDetails
        )
        logger.info(f"LLM extracted company details: {response.company_name}, CIN: {response.corporate_identity_number}")
        return response
    except Exception as e:
        logger.error(f"Error in LLM call: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to extract company details")

@router.post("/upload_drhp")
@log_to_s3
async def upload_drhp(
    request: Request,
    authorization: str = Header(...),
    file: UploadFile = File(...),
    current_user: User = Depends(login_required)
):
    logger.info(f"Upload DRHP request received from user {current_user.id} for file {file.filename}")
    try:
        # Save the uploaded file temporarily
        temp_filename = f"temp_{file.filename}"
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Extract text & metadata
        first_page_content = extract_first_page_text(temp_filename)
        company_details = get_company_details(first_page_content)

        # Check for existing DRHP by CIN
        existing = UploadedDRHP.objects(
            corporate_identity_number=company_details.corporate_identity_number,
            processing_status="PENDING"
        ).first()

        if existing:
            msg = f"Company '{company_details.company_name}' with CIN '{company_details.corporate_identity_number}' already uploaded."
            logger.info(msg)
            os.remove(temp_filename)
            return {"status": "exists", "message": msg}

        # Save the file in the persistent app/drhp_queue folder with the company's CIN as the filename
        drhp_queue_path = os.path.join(os.getcwd(), "app", "drhp_queue")
        os.makedirs(drhp_queue_path, exist_ok=True)  
        saved_file_path = os.path.join(drhp_queue_path, f"{company_details.corporate_identity_number}.pdf")

        # Move the temporary file to the drhp_queue folder
        shutil.move(temp_filename, saved_file_path)

        # Save record via MongoEngine
        new_doc = UploadedDRHP(
            processing_status="PENDING",
            upload_timestamp=datetime.utcnow(),
            uploaded_file_url=saved_file_path,  # Update this to reflect the local path
            company_name=company_details.company_name,
            corporate_identity_number=company_details.corporate_identity_number
        )
        new_doc.save()
        logger.info(f"DRHP successfully saved for {company_details.company_name} with CIN: {company_details.corporate_identity_number}")

        return {
            "message": "File uploaded successfully",
            "uploaded_file_url": saved_file_path,  # Update this to reflect the local path
            "company_name": company_details.company_name,
            "corporate_identity_number": company_details.corporate_identity_number,
            "processing_status": new_doc.processing_status
        }

    except Exception as e:
        logger.error(f"Error uploading DRHP: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
