from fastapi import APIRouter, HTTPException, Header, Request, Depends
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from app.services.auth_utils import login_required
from app.utils.helpers import UploadToBlob
from bson import ObjectId
from math import isnan
import pandas as pd
import tempfile
import os
from dotenv import load_dotenv
from app.models.schemas import User, StandardChecklist
from app.utils.log_to_s3 import log_to_s3
from datetime import datetime
load_dotenv()
router = APIRouter()

@router.get("/standard/checklist")
@log_to_s3
async def get_standard_checklist(
    company_id: str,
    request: Request,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    try:
        if not ObjectId.is_valid(company_id):
            raise HTTPException(status_code=400, detail="Invalid company ID format")

        checklist_items = StandardChecklist.objects(company_id=ObjectId(company_id))

        formatted_items = []
        for item in checklist_items:
            def safe_get(value):
                if isinstance(value, float) and isnan(value):
                    return ''
                return value if value is not None else ''

            formatted_item = {
                "id": str(item.id),
                "heading": safe_get(item.heading),
                "checklist_points": safe_get(item.checklist_points),
                "remarks": safe_get(item.remarks),
                "summary_analysis": safe_get(item.summary_analysis),
                "status": safe_get(item.status),
                "page_number": safe_get(item.page_number)
            }
            formatted_items.append(formatted_item)

        # Create DataFrame
        df = pd.DataFrame(formatted_items)

        # Save to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp_file:
            temp_filename = temp_file.name
            df.to_excel(temp_filename, index=False)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        download_url = f"/standard/checklist/{company_id}/download?timestamp={timestamp}"

        return {
            "total_items": len(formatted_items),
            "company_id": company_id,
            "checklist_items": formatted_items,
            "file_url": download_url
        }

    except Exception as e:
        print(f"Error fetching standard checklist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/standard/checklist/{company_id}/download")
@log_to_s3
async def download_standard_checklist(
    company_id: str,
    timestamp: str,
    background_tasks: BackgroundTasks,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    try:
        checklist_items = StandardChecklist.objects(company_id=ObjectId(company_id))
        formatted_items = []
        for item in checklist_items:
            def safe_get(value):
                if isinstance(value, float) and isnan(value):
                    return ''
                return value if value is not None else ''

            formatted_item = {
                "id": str(item.id),
                "heading": safe_get(item.heading),
                "checklist_points": safe_get(item.checklist_points),
                "remarks": safe_get(item.remarks),
                "summary_analysis": safe_get(item.summary_analysis),
                "status": safe_get(item.status),
                "page_number": safe_get(item.page_number)
            }
            formatted_items.append(formatted_item)

        df = pd.DataFrame(formatted_items)
        
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as temp_file:
            temp_filename = temp_file.name
            df.to_excel(temp_filename, index=False)

        filename = f"standard_checklist_{company_id}_{timestamp}.xlsx"
        
        background_tasks.add_task(os.remove, temp_filename)
        
        return FileResponse(
            path=temp_filename,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        print(f"Error downloading standard checklist: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
