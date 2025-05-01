import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import CreateChecklistRequest
from logger.logger import get_logger
from Checklist.functions import propagate_incomplete_upwards


router = APIRouter()


@router.post("/add_checklist")
def add_checklist(data: CreateChecklistRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    logger = get_logger('create_checklist', 'create_checklist.log')
    logger.info(f"POST /add_checklist called by user_id={Current_user.employee_id}")
    logger.debug(f"Checklist creation request: task_id={data.task_id}, checklist_name='{data.checklist_name}'")  

    try:
        task = db.query(Task).filter(Task.task_id == data.task_id, Task.is_delete == False).first()
        if not task:
            logger.warning(f"Task {data.task_id} not found or deleted")
            raise HTTPException(status_code=404, detail="Task not found")

        logger.info(f"Task found: task_id={task.task_id}, type={task.task_type}")
        parent_task_id = None
        target_task = None

        if task.task_type == TaskType.Review:
            parent_task = db.query(Task).filter(Task.task_id == task.parent_task_id, Task.is_delete == False).first()
            if not parent_task:
                logger.warning(f"Parent task {task.parent_task_id} for review not found")
                raise HTTPException(status_code=404, detail="Parent task not found")
            parent_task_id = parent_task.task_id
            target_task = parent_task

            
            parent_task.previous_status = parent_task.status
            parent_task.status = TaskStatus.To_Do
            log_task_field_change(db, task.task_id, "status", parent_task.status, TaskStatus.To_Do, Current_user.employee_id)
            old_status = task.status
            task.previous_status = task.status
            task.status = TaskStatus.In_ReEdit
            log_task_field_change(db, task.task_id, "status", old_status, task.status, Current_user.employee_id)
            logger.info(f"Review task {task.task_id} status updated to In_ReEdit")

        elif task.task_type == TaskType.Normal:
            if task.created_by != Current_user.employee_id and task.assigned_to != Current_user.employee_id:
                logger.warning(f"Unauthorized access for checklist addition on task {task.task_id}")
                raise HTTPException(status_code=403, detail="You don't have permission to add checklists")
            parent_task_id = task.task_id
            target_task = task

        checklist = Checklist(
            checklist_name=data.checklist_name,
            is_completed=False,
            is_delete=False,
            created_by=Current_user.employee_id
        )
        db.add(checklist)
        db.flush()
        logger.info(f"Checklist created with ID={checklist.checklist_id}")

        task_checklist_link = TaskChecklistLink(
        parent_task_id=parent_task_id,
            checklist_id=checklist.checklist_id,
            sub_task_id=None
        )
        db.add(task_checklist_link)
        db.flush()
        logger.info(f"Checklist linked to task_id={parent_task_id}")

        if target_task:
           
            if target_task.task_type == TaskType.Normal and (target_task.status == TaskStatus.Completed or target_task.status == TaskStatus.In_Review):
                propagate_incomplete_upwards(checklist.checklist_id, db,Current_user)

        db.commit()
        logger.info("Checklist creation and task updates committed successfully")
        return {
            "message": "Checklist created successfully",
            "checklist_id": checklist.checklist_id
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error occurred")
        raise HTTPException(status_code=500, detail="Internal Server Error")
