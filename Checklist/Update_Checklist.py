import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType
from Logs.functions import log_checklist_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import UpdateChecklistRequest
from logger.logger import get_logger


router = APIRouter()



@router.post("/update_checklist")
def update_checklist(data: UpdateChecklistRequest, db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    logger = get_logger("update_checklist", "update_checklist.log")
    logger.info(f"POST /update_checklist called by user_id={current_user.employee_id}")
    logger.debug(f"Checklist update request received: checklist_id={data.checklist_id}, new_name='{data.checklist_name}'")

    try:
        # Step 1: Fetch checklist
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == data.checklist_id,
            Checklist.is_delete == False
        ).first()

        if not checklist:
            logger.warning(f"Checklist {data.checklist_id} not found or already deleted")
            raise HTTPException(status_code=404, detail="Checklist not found")

        # Step 2: Log and update the name
        log_checklist_field_change(
            db,
            checklist.checklist_id,
            "checklist_name",
            checklist.checklist_name,
            data.checklist_name,
            current_user.employee_id
        )
        logger.info(f"Checklist {checklist.checklist_id} name updated from '{checklist.checklist_name}' to '{data.checklist_name}'")
        checklist.checklist_name = data.checklist_name

        db.commit()
        logger.info(f"Checklist {checklist.checklist_id} update committed to DB")

        return {
            "message": "Checklist updated successfully",
            "updated_checklist_name": data.checklist_name
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Unexpected error while updating checklist_id={data.checklist_id}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
