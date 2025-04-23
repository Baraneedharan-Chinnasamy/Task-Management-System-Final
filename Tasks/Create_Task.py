import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType, ChatRoom
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Tasks.inputs import CreateTask


router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/Create_Task")
def add_checklist_subtask(data: CreateTask, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    """
    Create a new task with associated checklists and optionally link it to an existing checklist.
    Also creates a review task if review is required.
    """
    try:
        # Create the main task
        new_task = Task(
            task_name=data.task_name,
            description=data.description,
            due_date=data.due_date,
            assigned_to=data.assigned_to,
            status=TaskStatus.To_Do,
            created_by=Current_user.employee_id,
            is_review_required=data.is_review_required
        )
        db.add(new_task)
        db.flush()  # Flush to get the task_id
        
        # Create a chat room for this task
        new_chat_room = ChatRoom(task_id=new_task.task_id)
        db.add(new_chat_room)
        
        # Log the status change
        log_task_field_change(db, new_task.task_id,"status", None, "To_Do", Current_user.employee_id)
        
        # Create checklists and link them to the task
        checklists_created = []
        for name in data.checklist_names:
            checklist = Checklist(
                checklist_name=name,
                is_completed=False,
                is_delete=False
            )
            db.add(checklist)
            db.flush()
            checklists_created.append(checklist)
            
            task_checklist_link = TaskChecklistLink(
                parent_task_id=new_task.task_id,
                checklist_id=checklist.checklist_id,
                sub_task_id=None
            )
            db.add(task_checklist_link)
        
        # Create a review task if required
        if data.is_review_required:
            review_task = Task(
                task_name=f"Review - {new_task.task_name}",
                description="Review task",
                status=TaskStatus.To_Do.name,
                assigned_to=Current_user.employee_id,
                created_by=Current_user.employee_id,
                due_date=data.due_date,
                task_type=TaskType.Review,
                parent_task_id=new_task.task_id
            )
            db.add(review_task)
        
        # Handle linking to an existing checklist if specified
        if data.checklist_id is not None:
            # Find the parent task associated with the checklist
            parent_task_relation = db.query(TaskChecklistLink.parent_task_id).filter(
                TaskChecklistLink.checklist_id == data.checklist_id
            ).first()
            
            if not parent_task_relation:
                logger.error(f"Checklist with ID {data.checklist_id} not found")
                raise HTTPException(status_code=404, detail="Checklist not found")
            
            parent_task_id = parent_task_relation[0]
            
            # Validate access to the parent task
            task = db.query(Task).filter(
                Task.task_id == parent_task_id,
                or_(Task.created_by == Current_user.employee_id, Task.assigned_to == Current_user.employee_id),
                Task.is_delete == False
            ).first()
            
            if not task:
                logger.error(f"Task not found or user {Current_user.employee_id} not authorized")
                raise HTTPException(status_code=403, detail="Task not found or you don't have permission")
            
            # Prevent adding subtasks to review tasks
            if task.task_type == TaskType.Review:
                logger.error(f"Cannot add subtask to review task {task.task_id}")
                raise HTTPException(status_code=400, detail="Cannot add subtask to a review task")
            
            # Create the link between the checklist and the new subtask
            task_checklist_link_sub = TaskChecklistLink(
                parent_task_id=None,
                checklist_id=data.checklist_id,
                sub_task_id=new_task.task_id
            )
            db.add(task_checklist_link_sub)
        
        # Commit all changes at once
        db.commit()
        logger.info(f"Task {new_task.task_id} created successfully with {len(checklists_created)} checklists")
        
        return {
            "message": "Task created successfully",
            "task_id": new_task.task_id,
            "checklists_created": len(checklists_created)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error occurred while creating task: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")