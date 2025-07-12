from fastapi import APIRouter, HTTPException, Header, Request
from app.services.auth_utils import login_required
from bson import ObjectId
from datetime import datetime, timedelta
import pandas as pd
from typing import List, Optional
import tempfile
import os
from dotenv import load_dotenv

load_dotenv()
from app.utils.helpers import UploadToBlob

router = APIRouter()

# Import all the endpoint functions from the implementation file
# These would typically be defined in this file directly
from app.api.endpoints.processing_analytics import (
    get_processing_summary,
    get_company_processing_metrics,
    get_processing_time_distribution,
    get_cost_efficiency_metrics,
    get_processing_trends,
    get_user_processing_activity,
    get_company_processing_details
)

# You can re-export the endpoints under this router
router.get("/summary")(get_processing_summary)
router.get("/companies")(get_company_processing_metrics)
router.get("/time_distribution")(get_processing_time_distribution)
router.get("/cost_efficiency")(get_cost_efficiency_metrics)
router.get("/trends")(get_processing_trends)
router.get("/user_activity")(get_user_processing_activity)
router.get("/company_details/{company_id}")(get_company_processing_details)