from fastapi import APIRouter, HTTPException, Header, Depends, Request
from app.services.auth_utils import login_required
from app.models.schemas import User, Company
from typing import List
import logging
from pydantic import BaseModel
from app.utils.log_to_s3 import log_to_s3

# Configure logging
logger = logging.getLogger("list_companies")

router = APIRouter()

# Define a clean Company schema for responses
class CompanySchema(BaseModel):
    company_id: str
    name: str
    corporate_identity_number: str
    drhp_file_url: str

@router.get("/list_companies")
@log_to_s3
async def list_companies(
    request: Request,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    logger.info(f"list_companies endpoint called by user: {current_user.email}")
    logger.info(f"Authorization header received, length: {len(authorization)}")
    
    # Log all request headers for debugging (except auth)
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in ['authorization']}
    logger.info(f"Request headers: {safe_headers}")
    
    try:
        logger.info("Attempting to fetch companies from database")
        companies = Company.objects.all()
        logger.info(f"Found {len(companies)} companies in the database")
        
        companies_list = [
            CompanySchema(
                company_id=str(company.id),
                name=company.name,
                corporate_identity_number=company.corporate_identity_number,
                drhp_file_url=company.drhp_file_url
            ).dict()
            for company in companies
        ]
        
        logger.info(f"Successfully processed {len(companies_list)} companies")
        
        return {
            "total_companies": len(companies_list),
            "companies": companies_list
        }

    except Exception as e:
        logger.error(f"Error finding companies data: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))
