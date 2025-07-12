from fastapi import APIRouter, HTTPException, Header, Request, Depends
from app.services.auth_utils import login_required
from bson import ObjectId
import os
from dotenv import load_dotenv
from app.models.schemas import User, Company
from app.utils.log_to_s3 import log_to_s3
load_dotenv()
router = APIRouter()

@router.get("/details")
@log_to_s3
async def get_company_details(
    company_id: str,
    request: Request,
    authorization: str = Header(...),
    current_user: User = Depends(login_required)
):
    
    try:
        if not ObjectId.is_valid(company_id):
            raise HTTPException(status_code=400, detail="Invalid company ID format")

        # 🧠 Use MongoEngine to query by ID
        company = Company.objects(id=ObjectId(company_id)).first()
        
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
            
        return {
            "id": str(company.id),
            "name": company.name,
            "corporate_identity_number": company.corporate_identity_number,
            "drhp_file_url": company.drhp_file_url
        }

    except ValidationError as ve:
        print(f"Validation error: {ve}")
        raise HTTPException(status_code=400, detail="Invalid company ID")
    except Exception as e:
        print(f"Error fetching company details: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")