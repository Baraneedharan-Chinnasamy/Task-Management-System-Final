import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType
from Logs.functions import log_checklist_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import UpdateChecklistRequest


router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/update-checklist")
def update_checklist(data: UpdateChecklistRequest, db: Session = Depends(get_db),current_user: str = Depends(get_current_user)):
    try:
        checklist = db.query(Checklist).filter(Checklist.checklist_id == data.checklist_id, Checklist.is_delete == False).first()
        if not checklist:
            raise HTTPException(status_code=404, detail="Checklist not found")
        

        log_checklist_field_change(db, checklist.checklist_id, "checklist_name", checklist.checklist_name, data.checklist_name, current_user.employee_id)
        checklist.checklist_name = data.checklist_name
        
        db.commit()
        
        return {"message": "Checklist updated successfully", "updated_checklist_name": data.checklist_name}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error occurred while Updating Checklist: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")