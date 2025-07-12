from fastapi import APIRouter, HTTPException, Header, Request, Depends
from app.services.auth_utils import login_required
from app.core.database import get_mongo_client
import os
from dotenv import load_dotenv
from app.models.schemas import User, UploadedDRHP
from pydantic import BaseModel
from app.utils.log_to_s3 import log_to_s3
load_dotenv()
router = APIRouter()

class ProcessingStatusItem(BaseModel):
    processing_status: str
    upload_timestamp: str  # Or datetime if you handle conversion
    uploaded_file_url: str
    company_name: str
    corporate_identity_number: str
    
    
@router.get("/processing_status")
@log_to_s3
async def get_processing_status(
    request: Request,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    

    try:
        processing_status_docs = UploadedDRHP.objects.only(
            'processing_status',
            'upload_timestamp',
            'uploaded_file_url',
            'company_name',
            'corporate_identity_number'
        ).all()

        processing_status_items = [
            ProcessingStatusItem(
                processing_status=doc.processing_status,
                upload_timestamp=doc.upload_timestamp.isoformat(),
                uploaded_file_url=doc.uploaded_file_url,
                company_name=doc.company_name,
                corporate_identity_number=doc.corporate_identity_number
            ).dict()
            for doc in processing_status_docs
        ]

        return {
            "total_items": len(processing_status_items),
            "processing_status_items": processing_status_items
        }

    except Exception as e:
        print(f"Error fetching processing status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")