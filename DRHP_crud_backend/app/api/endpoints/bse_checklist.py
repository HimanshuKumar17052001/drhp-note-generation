from fastapi import APIRouter, HTTPException, Header, Request, Depends
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from app.services.auth_utils import login_required
from app.utils.helpers import UploadToBlob
from bson import ObjectId
import pandas as pd
import tempfile
import os
from dotenv import load_dotenv
from app.models.schemas import BseChecklist, User
from app.utils.log_to_s3 import log_to_s3
from datetime import datetime
load_dotenv()

router = APIRouter()

@router.get("/bse/checklist")
@log_to_s3
async def get_bse_checklist(
    company_id: str,
    request: Request,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    try:
        if not ObjectId.is_valid(company_id):
            raise HTTPException(status_code=400, detail="Invalid company ID format")

        # Use MongoEngine instead of raw pymongo
        checklist_items = BseChecklist.objects(company_id=ObjectId(company_id))

        formatted_items = []
        for item in checklist_items:
            formatted_items.append({
                "id": str(item.id),
                "regulation_mentioned": "BSE Eligibility Criteria",  # Hardcoded as requested
                "particulars": item.particulars,
                "summary_analysis": item.summary_analysis,
                "status": item.status,
                "page_number": item.page_number or ""
            })

        # Create DataFrame
        df = pd.DataFrame(formatted_items)

        # Save to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp_file:
            temp_filename = temp_file.name
            df.to_excel(temp_filename, index=False)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_url = f"/bse/checklist/{company_id}/download?timestamp={timestamp}"

        return {
            "total_items": len(formatted_items),
            "company_id": company_id,
            "checklist_items": formatted_items,
            "file_url": download_url
        }

    except Exception as e:
        print(f"Error fetching BSE checklist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/bse/checklist/{company_id}/download")
@log_to_s3
async def download_bse_checklist(
    company_id: str,
    timestamp: str,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    try:
        checklist_items = BseChecklist.objects(company_id=ObjectId(company_id))
        formatted_items = []
        for item in checklist_items:
            formatted_items.append({
                "id": str(item.id),
                "regulation_mentioned": "BSE Eligibility Criteria",
                "particulars": item.particulars,
                "summary_analysis": item.summary_analysis,
                "status": item.status,
                "page_number": item.page_number or ""
            })

        df = pd.DataFrame(formatted_items)
        
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp_file:
            temp_filename = temp_file.name
            df.to_excel(temp_filename, index=False)

        filename = f"bse_checklist_{company_id}_{timestamp}.xlsx"
        
        background_tasks.add_task(os.remove, temp_filename)
        
        return FileResponse(
            path=temp_filename,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        print(f"Error downloading BSE checklist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
