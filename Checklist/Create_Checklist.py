import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import CreateChecklistRequest


router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/add_checklist")
def add_checklist(data: CreateChecklistRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    """
    Add a new checklist to a task.
    
    - For review tasks: Creates a checklist linked to the parent task
    - For normal tasks: Creates a checklist directly linked to the task
    
    Task status is updated appropriately based on task type.
    """
    try:
        # Get task and validate it exists
        task = db.query(Task).filter(
            Task.task_id == data.task_id,
            Task.is_delete == False
        ).first()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Variable to store the parent task ID for the checklist
        parent_task_id = None
        target_task = None  # Task that may need status update
        
        if task.task_type == TaskType.Review:
            # For review tasks, link checklist to the parent task
            parent_task = db.query(Task).filter(
                Task.task_id == task.parent_task_id,
                Task.is_delete == False
            ).first()
            
            if not parent_task:
                raise HTTPException(status_code=404, detail="Parent task not found")
                
            parent_task_id = parent_task.task_id
            target_task = parent_task
            
        elif task.task_type == TaskType.Normal:
            # For normal tasks, validate permissions
            if task.created_by != Current_user.employee_id and task.assigned_to != Current_user.employee_id:
                raise HTTPException(status_code=403, detail="You don't have permission to add checklists to this task")
                
            parent_task_id = task.task_id
            target_task = task
        
        # Create the checklist
        checklist = Checklist(
            checklist_name=data.checklist_name,
            is_completed=False,
            is_delete=False
        )
        db.add(checklist)
        db.flush()
        
        # Create the task-checklist link
        task_checklist_link = TaskChecklistLink(
            parent_task_id=parent_task_id,
            checklist_id=checklist.checklist_id,
            sub_task_id=None
        )
        db.add(task_checklist_link)
        
        # Update task status if needed
        if target_task:
            old_status = target_task.status
            new_status = None
            
            if target_task.task_type == TaskType.Normal:
                # Normal tasks should go to In_Process when adding checklists
                if target_task.status in [TaskStatus.In_Review, TaskStatus.Completed]:
                    new_status = TaskStatus.In_Process
                else:
                    new_status = TaskStatus.To_Do
            elif target_task.task_type == TaskType.Review:
                # Review tasks should go to To_Do when adding checklists
                new_status = TaskStatus.To_Do

            if target_task.task_type == TaskType.Review:
                target_task.is_reviewed = False
                db.flush()
            
            # Only update and log if status actually changes
            if new_status and old_status != new_status:
                target_task.status = new_status
                log_task_field_change(db, target_task.task_id,"status", old_status, new_status,Current_user.employee_id)
        
        db.commit()
        return {
            "message": "Checklist created successfully",
            "checklist_id": checklist.checklist_id
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error occurred while creating checklist: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")