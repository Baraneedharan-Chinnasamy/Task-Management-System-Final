import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType
from Logs.functions import log_task_field_change, log_checklist_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import UpdateStatus
from Checklist.functions import update_parent_task_status, propagate_incomplete_upwards


router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/mark_checklist_complete")
def update_Status(data: UpdateStatus, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    """
    Update the completion status of a checklist and propagate changes appropriately.
    
    This function handles status updates for checklists linked to both normal and review tasks.
    When a checklist is marked as complete/incomplete, the function performs necessary updates
    to parent tasks and related entities.
    """
    try:
        # Find the checklist and validate it exists
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == data.checklist_id,
            Checklist.is_delete == False
        ).first()
        
        if not checklist:
            raise HTTPException(status_code=404, detail="Checklist not found")
            
        # Check if the checklist already has the requested status
        if checklist.is_completed == data.is_completed:
            return {"message": f"Checklist was already {'completed' if data.is_completed else 'incomplete'}"}
        
        # Find the parent task of the checklist
        parent_link = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.checklist_id == data.checklist_id,
            TaskChecklistLink.parent_task_id.isnot(None)
        ).first()
        
        if not parent_link:
            raise HTTPException(status_code=404, detail="Checklist is not linked to any parent task")
        
        parent_task_id = parent_link.parent_task_id
        
        # Verify the user has permission to update this checklist
        parent_task = db.query(Task).filter(
            Task.task_id == parent_task_id,
            or_(Task.created_by == Current_user.employee_id, Task.assigned_to == Current_user.employee_id),
            Task.is_delete == False
        ).first()
        
        if not parent_task:
            raise HTTPException(status_code=403, detail="You don't have permission to update this checklist")
        
        # Check if the checklist has any sub-tasks (common for both task types)
        subtask_exists = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.checklist_id == data.checklist_id,
            TaskChecklistLink.sub_task_id.isnot(None)
        ).first()
        
        if subtask_exists:
            raise HTTPException(
                status_code=400, 
                detail="Checklist has sub-tasks and cannot be marked as complete/incomplete directly"
            )
        
        # Update the checklist status
        log_checklist_field_change(db,checklist.checklist_id,"is_completed",checklist.is_completed,data.is_completed,Current_user.employee_id
)
        checklist.is_completed = data.is_completed
       
        
        
        # Handle status propagation based on task type
        if parent_task.task_type == TaskType.Normal:
            if data.is_completed:
                # When marking complete, check if all checklists are complete to update parent task
                parent_task_links = db.query(TaskChecklistLink).filter(
                    TaskChecklistLink.parent_task_id == parent_task_id
                ).all()
                
                # Get all checklist IDs for this parent task
                checklist_ids = [link.checklist_id for link in parent_task_links]
                
                # Check completion status of all checklists
                update_parent_task_status(parent_task_id, db,Current_user)
            else:
                # When marking incomplete, always propagate up the incompleteness
                propagate_incomplete_upwards(data.checklist_id, db,Current_user)
        
        elif parent_task.task_type == TaskType.Review:
            # Get all checklists for this review task
            review_checklists = db.query(Checklist).join(
                TaskChecklistLink, 
                TaskChecklistLink.checklist_id == Checklist.checklist_id
            ).filter(
                TaskChecklistLink.parent_task_id == parent_task_id,
                Checklist.is_delete == False
            ).all()
            
            all_complete = all(c.is_completed for c in review_checklists)
            
            # Find the child task (the task being reviewed)
            child_task = db.query(Task).filter(
                Task.parent_task_id == parent_task_id,
                Task.is_delete == False
            ).first()
            
            if child_task:
                if data.is_completed and all_complete:
                    # All review checklists complete -> set child task to To_Do
                    old_status = child_task.status
                    child_task.status = TaskStatus.To_Do
                    log_task_field_change(db, child_task.task_id,"status", old_status, TaskStatus.To_Do, Current_user.employee_id)
                    
                    # Copy output from review task to child task
                    log_task_field_change(db, child_task.task_id,"output", child_task.output, parent_task.output, Current_user.employee_id)
                    child_task.output = parent_task.output

                elif not data.is_completed:
                    if parent_task.is_reviewed == True:
                        parent_task.is_reviewed = False
                        log_task_field_change(db, parent_task.task_id,"status", parent_task.status, TaskStatus.To_Do, Current_user.employee_id)
                        parent_task.status = TaskStatus.To_Do
                        db.flush()
                        log_task_field_change(db, parent_task.task_id,"is_reviewed", True, False, Current_user.employee_id)
                           

                    old_status = child_task.status
                    child_task.status = TaskStatus.Completed
                    log_task_field_change(db, child_task.task_id,"status", old_status, TaskStatus.Completed, Current_user.employee_id)
                    
                    # Clear output from child task
                    child_task.output = None
                    db.flush()
                
        
        db.commit()
        return {
            "message": f"Checklist marked as {'complete' if data.is_completed else 'incomplete'} successfully",
            "checklist_id": data.checklist_id
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error occurred while updating checklist status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")