from fastapi import APIRouter, HTTPException, Header, Request
from app.services.auth_utils import login_required
from bson import ObjectId
import os
from dotenv import load_dotenv
from app.utils.log_to_s3 import log_to_s3
from app.models.schemas import SebiChecklist, BseChecklist, StandardChecklist

load_dotenv()
router = APIRouter()

# Define available status transitions
TOGGLE_STATUS_MAP = {
    "FLAGGED": "NOT FLAGGED",
    "NOT FLAGGED": "FLAGGED"
}

# Mapping checklist types to their respective MongoDB collections
CHECKLIST_COLLECTIONS = {
    "sebi": SebiChecklist,
    "bse": BseChecklist,
    "standard": StandardChecklist
}

@router.post("/toggle_checklist_status")
@log_to_s3
async def toggle_checklist_status(
    checklist_id: str,
    checklist_type: str,
    request: Request,
    authorization: str = Header(...)
):
    current_user = await login_required(request)


    # Validate checklist type
    if checklist_type.lower() not in CHECKLIST_COLLECTIONS:
        raise HTTPException(status_code=400, detail="Invalid checklist type. Choose from 'sebi', 'bse', or 'standard'.")

    collection_model = CHECKLIST_COLLECTIONS[checklist_type.lower()]

    # Fetch the checklist item
    checklist_item = collection_model.objects(id=ObjectId(checklist_id)).first()
    if not checklist_item:
        raise HTTPException(status_code=404, detail="Checklist item not found.")

    # Toggle the status
    current_status = checklist_item.status  # Access the property directly
    new_status = TOGGLE_STATUS_MAP.get(current_status, "FLAGGED")

    # Update the checklist item
    checklist_item.update(set__status = new_status)
    #checklist_item.save()

    return {"message": "Checklist status updated successfully.", "new_status": new_status}
