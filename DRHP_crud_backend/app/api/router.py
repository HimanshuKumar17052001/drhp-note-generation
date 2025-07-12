from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import (
    list_companies,
    sebi_checklist,
    bse_checklist,
    standard_checklist,
    company_details,
    auth,
    questionnaire,
    litigations,
    chat,
    processing_status,
    upload_drhp_to_blob,
    change_checlist_status,
    processing_analytics
)
import os
from dotenv import load_dotenv
load_dotenv()

app = FastAPI()

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# api_router = APIRouter(prefix="/api")
api_router = APIRouter()

# Auth endpoints
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"]
)

# Company related endpoints
api_router.include_router(
    list_companies.router,
    prefix="/list/companies",
    tags=["Companies"]
)

api_router.include_router(
    company_details.router,
    prefix="/details",
    tags=["Company Details"]
)

# Checklist endpoints
api_router.include_router(
    sebi_checklist.router,
    prefix="/sebi/checklist",
    tags=["SEBI Checklist"]
)

api_router.include_router(
    bse_checklist.router,
    prefix="/bse/checklist",
    tags=["BSE Checklist"]
)

api_router.include_router(
    standard_checklist.router,
    prefix="/standard_questions_checklist/checklist",
    tags=["Standard Questions Checklist"]
)

# Other endpoints
api_router.include_router(
    questionnaire.router,
    prefix="/questionnaire",
    tags=["Questionnaire"]
)

api_router.include_router(
    litigations.router,
    prefix="/litigations",
    tags=["Litigations"]
)

api_router.include_router(
    processing_status.router,
    prefix="/processing_status",
    tags=["Processing Status"]
)

api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["Chat"]
)

api_router.include_router(
    upload_drhp_to_blob.router,
    prefix="/upload_drhp",
    tags=["Upload DRHP"]
)

api_router.include_router(
    change_checlist_status.router,
    prefix="/toggle_checklist_status",
    tags=["Change Checklist Status"]
)

api_router.include_router(
    processing_analytics.router,
    prefix="/analytics",
    tags=["give the analytics"]
)
app.include_router(api_router)
