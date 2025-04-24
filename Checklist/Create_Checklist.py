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


router = APIRouter()


@router.post("/add_checklist")
def add_checklist(data: CreateChecklistRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    logger = get_logger('create_checklist', 'create_checklist.log')
    logger.info(f"POST /add_checklist called by user_id={Current_user.employee_id}")
    logger.debug(f"Checklist creation request: task_id={data.task_id}, checklist_name='{data.checklist_name}'")

    try:
        # Get task and validate
        task = db.query(Task).filter(
            Task.task_id == data.task_id,
            Task.is_delete == False
        ).first()

        if not task:
            logger.warning(f"Task {data.task_id} not found or already deleted")
            raise HTTPException(status_code=404, detail="Task not found")

        logger.info(f"Target task found: task_id={task.task_id}, task_type={task.task_type}")

        parent_task_id = None
        target_task = None

        # Handle task types
        if task.task_type == TaskType.Review:
            logger.info(f"Checklist to be linked through parent of review task {task.task_id}")
            parent_task = db.query(Task).filter(
                Task.task_id == task.parent_task_id,
                Task.is_delete == False
            ).first()

            if not parent_task:
                logger.warning(f"Parent task {task.parent_task_id} not found for review task {task.task_id}")
                raise HTTPException(status_code=404, detail="Parent task not found")

            parent_task_id = parent_task.task_id
            target_task = parent_task

        elif task.task_type == TaskType.Normal:
            if task.created_by != Current_user.employee_id and task.assigned_to != Current_user.employee_id:
                logger.warning(f"Unauthorized checklist add attempt by user_id={Current_user.employee_id} on task_id={task.task_id}")
                raise HTTPException(status_code=403, detail="You don't have permission to add checklists to this task")

            parent_task_id = task.task_id
            target_task = task

        # Create checklist
        checklist = Checklist(
            checklist_name=data.checklist_name,
            is_completed=False,
            is_delete=False
        )
        db.add(checklist)
        db.flush()
        logger.info(f"Checklist created with ID={checklist.checklist_id} for task_id={data.task_id}")

        # Link checklist to task
        task_checklist_link = TaskChecklistLink(
            parent_task_id=parent_task_id,
            checklist_id=checklist.checklist_id,
            sub_task_id=None
        )
        db.add(task_checklist_link)
        logger.info(f"Checklist {checklist.checklist_id} linked to parent_task_id={parent_task_id}")

        # Handle status changes for the task
        if target_task:
            old_status = target_task.status
            new_status = None

            if target_task.task_type == TaskType.Normal:
                if target_task.status in [TaskStatus.In_Review, TaskStatus.Completed]:
                    new_status = TaskStatus.In_Process
                else:
                    new_status = TaskStatus.To_Do

            elif target_task.task_type == TaskType.Review:
                new_status = TaskStatus.To_Do
                target_task.is_reviewed = False
                db.flush()
                logger.info(f"Review status set to False for task_id={target_task.task_id}")

            if new_status and old_status != new_status:
                target_task.status = new_status
                log_task_field_change(db, target_task.task_id, "status", old_status, new_status, )
                logger.info(f"Task {target_task.task_id} status updated from {old_status} to {new_status}")

        db.commit()
        logger.info(f"Checklist creation and task update committed successfully")

        return {
            "message": "Checklist created successfully",
            "checklist_id": checklist.checklist_id
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while creating checklist")
        raise HTTPException(status_code=500, detail="Internal Server Error")
