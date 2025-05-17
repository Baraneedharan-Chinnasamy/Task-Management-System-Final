import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from sqlalchemy import desc
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType, User,TaskTimeLog
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import CreateChecklistRequest
from logger.logger import get_logger
from Checklist.functions import propagate_incomplete_upwards
from datetime import datetime


router = APIRouter()


@router.post("/add_checklist")
def add_checklist(data: CreateChecklistRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    logger = get_logger('create_checklist', 'create_checklist.log')
    logger.info(f"POST /add_checklist called by user_id={Current_user.employee_id}")
    logger.debug(f"Checklist creation request: task_id={data.task_id}, checklist_names={data.checklist_names}")  

    try:
        users = db.query(User).filter().all()
        user_map = {u.employee_id: u.username for u in users}
        task = db.query(Task).filter(Task.task_id == data.task_id, Task.is_delete == False).first()
        if not task:
            logger.warning(f"Task {data.task_id} not found or deleted")
            raise HTTPException(status_code=404, detail="Task not found")

        logger.info(f"Task found: task_id={task.task_id}, type={task.task_type}")
        parent_task_id = None
        target_task = None

        if task.task_type == TaskType.Review:
            time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == task.task_id,TaskTimeLog.end_time == None).order_by(desc(TaskTimeLog.start_time)).first()
            if time is None:
                return {"Start time": "No active time tracking found for this task."}
            
            parent_task = db.query(Task).filter(Task.task_id == task.parent_task_id, Task.is_delete == False).first()
            if not parent_task:
                logger.warning(f"Parent task {task.parent_task_id} for review not found")
                raise HTTPException(status_code=404, detail="Parent task not found")
            parent_task_id = parent_task.task_id
            target_task = parent_task

            parent_task.previous_status = parent_task.status
            parent_task.status = TaskStatus.To_Do
            parent_task.is_reviewed = False
            log_task_field_change(db, task.task_id, "status", parent_task.status, TaskStatus.To_Do, Current_user.employee_id)
            if task.status != TaskStatus.In_ReEdit:
                old_status = task.status
                task.previous_status = task.status
                task.status = TaskStatus.In_ReEdit
                log_task_field_change(db, task.task_id, "status", old_status, task.status, Current_user.employee_id)
                logger.info(f"Review task {task.task_id} status updated to In_ReEdit")
                time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == task.task_id,TaskTimeLog.end_time == None).order_by(desc(TaskTimeLog.start_time)).first()
                if time is not None:
                    time.end_time = datetime.now()
                    db.flush()

        elif task.task_type == TaskType.Normal:
            if task.created_by != Current_user.employee_id and task.assigned_to != Current_user.employee_id:
                logger.warning(f"Unauthorized access for checklist addition on task {task.task_id}")
                raise HTTPException(status_code=403, detail="You don't have permission to add checklists")
            if task.assigned_to == Current_user.employee_id:
                time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == task.task_id,TaskTimeLog.end_time == None).order_by(desc(TaskTimeLog.start_time)).first()
                if task.status == TaskStatus.To_Do and task.previous_status == TaskStatus.To_Do and time is None:
                    return {"Start time": "No active time tracking found for this task."}
                
            parent_task_id = task.task_id
            target_task = task

        created_checklists = []
        for name in data.checklist_names:
            checklist = Checklist(
                checklist_name=name,
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

            if target_task and target_task.task_type == TaskType.Normal and target_task.status in [TaskStatus.Completed, TaskStatus.In_Review]:
            
                propagate_incomplete_upwards(checklist.checklist_id, db, Current_user)

            created_checklists.append({
                "checklist_id": checklist.checklist_id,
                "checklist_name": checklist.checklist_name,
                "checklist_created_by_id": checklist.created_by,
                "checklist_created_by_name": user_map.get(checklist.created_by),
                "is_completed": checklist.is_completed,
            })

        db.commit()
        
        
        task_links = db.query(TaskChecklistLink).filter(TaskChecklistLink.parent_task_id == task.task_id).all()

        subtask_checklist_data = []
        for st_link in task_links:
            st_checklist = db.query(Checklist).filter(Checklist.checklist_id == st_link.checklist_id,Checklist.is_delete == False).first()
            if st_checklist:
                subtask_checklist_data.append(st_checklist)

        st_completed = sum(1 for c in subtask_checklist_data if c.is_completed)
        st_total = len(subtask_checklist_data)
        checklist_progress = f"{st_completed}/{st_total}" if st_total > 0 else "0/0"

        logger.info("All checklists created and task updates committed successfully")
        return {
            "message": "Checklists created successfully",
            "checklists": created_checklists,
            "task_id": task.task_id,
            "task_name": task.task_name,
            "status":task.status,
            "checklist_progress": checklist_progress,
            "group": "Review Checklist" if task.task_type == TaskType.Review else None}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error occurred")
        raise HTTPException(status_code=500, detail="Internal Server Error")
