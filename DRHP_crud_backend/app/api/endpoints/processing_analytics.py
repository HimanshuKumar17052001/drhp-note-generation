from fastapi import APIRouter, HTTPException, Header, Request, Depends
from app.services.auth_utils import login_required
from bson import ObjectId
from datetime import datetime, timedelta
import pandas as pd
from typing import Optional
import os
from dotenv import load_dotenv
from app.utils.helpers import UploadToBlob
from app.models.schemas import User, CostMap
from app.utils.log_to_s3 import log_to_s3
load_dotenv()
router = APIRouter(prefix="/analytics")

@router.get("/summary")
@log_to_s3
async def get_processing_summary(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    """
    Get overall summary of DRHP processing metrics including:
    - Total companies processed
    - Total processing time
    - Average processing time per company
    - Total cost
    - Average cost per company
    - Cost breakdown (input vs output)
    """
    try:
        # Build query using MongoEngine
        filters = {}
        if start_date or end_date:
            date_range = {}
            if start_date:
                date_range['__gte'] = datetime.strptime(start_date, "%Y-%m-%d")
            if end_date:
                date_range['__lte'] = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            filters['created_at'] = date_range  # Assuming you track this

        queryset = CostMap.objects(**filters)
        total_companies = queryset.count()

        if total_companies == 0:
            return {
                "total_companies": 0,
                "total_processing_time": 0,
                "avg_processing_time": 0,
                "total_cost": 0,
                "avg_cost_per_company": 0,
                "total_input_cost": 0,
                "total_output_cost": 0,
                "input_cost_percentage": 0,
                "output_cost_percentage": 0
            }

        total_processing_time = sum(doc.total_processing_time or 0 for doc in queryset)
        total_input_cost = sum(doc.total_input_cost_usd or 0 for doc in queryset)
        total_output_cost = sum(doc.total_output_cost_usd or 0 for doc in queryset)
        total_cost = total_input_cost + total_output_cost

        avg_processing_time = total_processing_time / total_companies
        avg_cost = total_cost / total_companies
        input_cost_pct = (total_input_cost / total_cost) * 100 if total_cost > 0 else 0
        output_cost_pct = (total_output_cost / total_cost) * 100 if total_cost > 0 else 0

        return {
            "total_companies": total_companies,
            "total_processing_time": round(total_processing_time, 2),
            "avg_processing_time": round(avg_processing_time, 2),
            "total_cost": round(total_cost, 4),
            "avg_cost_per_company": round(avg_cost, 4),
            "total_input_cost": round(total_input_cost, 4),
            "total_output_cost": round(total_output_cost, 4),
            "input_cost_percentage": round(input_cost_pct, 2),
            "output_cost_percentage": round(output_cost_pct, 2)
        }

    except Exception as e:
        print(f"Error generating processing summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

