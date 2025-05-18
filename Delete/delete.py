import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_, update
from models.models import Task, Checklist, TaskChecklistLink, TaskUpdateLog, ChecklistUpdateLog
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Delete.inputs import DeleteItemsRequest
from Delete.functions import get_related_tasks_checklists_logic
from Logs.functions import log_checklist_field_change,log_task_field_change
from logger.logger import get_logger
from datetime import datetime
from Tasks.functions import update_parent_task_status

router = APIRouter()

@router.post("/delete")
def delete_related_items(
    delete_request: DeleteItemsRequest,
    db: Session = Depends(get_db),
    Current_user: int = Depends(get_current_user)
):
    logger = get_logger('delete', 'delete.log')
    logger.info(f"DELETE requested by user_id={Current_user.employee_id}")
    
    task_id = delete_request.task_id
    checklist_id = delete_request.checklist_id

    # Permission validation
    if task_id:
        task = db.query(Task).filter(Task.task_id == task_id, Task.created_by == Current_user.employee_id).first()
        if not task:
            logger.warning(f"Task deletion denied. Task {task_id} not found or not owned by user {Current_user.employee_id}")
            raise HTTPException(status_code=403, detail="Task not found or not owned by you.")
    elif checklist_id:
        parent_task_link = db.query(TaskChecklistLink).filter(TaskChecklistLink.checklist_id == checklist_id).first()
        if not parent_task_link:
            logger.warning(f"Checklist deletion failed. Checklist {checklist_id} not linked to any parent task.")
            raise HTTPException(status_code=404, detail="Checklist is not linked to any parent task.")
        checklist = db.query(Checklist).filter(Checklist.checklist_id == checklist_id , Checklist.created_by == Current_user.employee_id ).first()
        parent_task = db.query(Task).filter(Task.task_id == parent_task_link.parent_task_id,Task.is_delete == False).first()
        if parent_task.created_by != Current_user.employee_id and checklist.created_by != Current_user.employee_id:
            # Enter this block only if BOTH are not created by the current user
            logger.warning(f"Checklist deletion denied. Checklist {checklist_id} is  not owned by user {Current_user.employee_id}")
            raise HTTPException(status_code=403, detail="You don't have permission to delete this checklist.")

    result = get_related_tasks_checklists_logic(db, task_id, checklist_id)
    tasks_to_delete = result.get("tasks", [])
    checklists_to_delete = result.get("checklists",[])

    if not tasks_to_delete and not checklists_to_delete:
        logger.info("No related tasks or checklists found for deletion.")
        raise HTTPException(status_code=404, detail="No related tasks or checklists found.")

    logger.debug(f"Tasks to delete: {tasks_to_delete}")
    logger.debug(f"Checklists to delete: {checklists_to_delete}")

    # Bulk mark tasks as deleted
    if tasks_to_delete:
        db.execute(
            update(Task)
            .where(Task.task_id.in_(tasks_to_delete))
            .values(is_delete=True)
        )
        logs = [{
            "task_id": t_id,
            "field_name": "is_delete",
            "old_value": "False",
            "new_value": "True",
            "updated_by": Current_user.employee_id,
            "updated_at": datetime.now()
        } for t_id in tasks_to_delete]
        db.bulk_insert_mappings(TaskUpdateLog, logs)
        logger.info(f"Marked tasks as deleted: {tasks_to_delete}")

    # Bulk mark checklists as deleted
    if checklists_to_delete:
        db.execute(
            update(Checklist)
            .where(Checklist.checklist_id.in_(checklists_to_delete))
            .values(is_delete=True)
        )
        logs = [{
            "checklist_id": c_id,
            "field_name": "is_delete",
            "old_value": "False",
            "new_value": "True",
            "updated_by": Current_user.employee_id,
            "updated_at": datetime.now()
        } for c_id in checklists_to_delete]
        
        db.bulk_insert_mappings(ChecklistUpdateLog, logs)
        
    db.flush()
    if delete_request.task_id:
        link = db.query(TaskChecklistLink.checklist_id).filter(
            TaskChecklistLink.sub_task_id == delete_request.task_id).first()
        if link:
            update_parent_task_status(link.checklist_id,db,Current_user)

    if delete_request.checklist_id:
        update_parent_task_status(delete_request.checklist_id, db, Current_user)
        db.flush()
            
        logger.info(f"Marked checklists as deleted: {checklists_to_delete}")
    
        parent_task_checklists = db.query(TaskChecklistLink).filter(
                TaskChecklistLink.parent_task_id.isnot(None),
                TaskChecklistLink.checklist_id==delete_request.checklist_id,
            ).first()

        parent_task = db.query(Task).filter(
            Task.task_id == parent_task_checklists.parent_task_id,
            Task.is_delete == False
        ).first()

        parent_task_checklists = db.query(TaskChecklistLink).filter(
                TaskChecklistLink.parent_task_id == parent_task.task_id,
                TaskChecklistLink.checklist_id.isnot(None)).all()

        checklist_ids = [link.checklist_id for link in parent_task_checklists]
        checklists = db.query(Checklist).filter(Checklist.checklist_id.in_(checklist_ids),Checklist.is_delete == False).all()

        completed = sum(1 for c in checklists if c.is_completed)
        total = len(checklists)
        checklist_progress = f"{completed}/{total}" if total > 0 else "0/0"

    db.commit()
    logger.info("Deletion process completed successfully.")
    parent_task = None  # ✅ Ensure variable is always defined
    checklist_progress = None
    return {
        "message": "Related tasks and checklists marked as deleted",
        "tasks": list(tasks_to_delete),
        "checklists": list(checklists_to_delete),
        "parent_task_id": parent_task.task_id if parent_task else None,
        "parent_checklist_progress": checklist_progress if parent_task else None,
        "parent_task_status": parent_task.status if parent_task else None
        }
