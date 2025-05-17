import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_, desc
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType, TaskTimeLog
from Logs.functions import log_task_field_change, log_checklist_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Checklist.inputs import UpdateStatus
from Checklist.functions import update_parent_task_status, propagate_incomplete_upwards
from logger.logger import get_logger


router = APIRouter()



@router.post("/mark_checklist_complete")
def update_Status(data: UpdateStatus, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    logger = get_logger('mark_checklist_complete', 'checklist_status.log')
    logger.info(f"POST /mark_checklist_complete called by user_id={Current_user.employee_id}")
    logger.debug(f"Request data: checklist_id={data.checklist_id}, is_completed={data.is_completed}")

    try:
        
        # Step 1: Fetch checklist
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == data.checklist_id,
            Checklist.is_delete == False
        ).first()

        if not checklist:
            logger.warning(f"Checklist {data.checklist_id} not found or deleted")
            raise HTTPException(status_code=404, detail="Checklist not found")

        logger.info(f"Checklist {data.checklist_id} found, current status: {checklist.is_completed}")

        if checklist.is_completed == data.is_completed:
            logger.info(f"Checklist {data.checklist_id} already {'completed' if data.is_completed else 'incomplete'}")
            

        # Step 2: Validate and fetch parent task
        parent_link = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.checklist_id == data.checklist_id,
            TaskChecklistLink.parent_task_id.isnot(None)
        ).first()

        if not parent_link:
            logger.warning(f"Checklist {data.checklist_id} not linked to any parent task")
            raise HTTPException(status_code=404, detail="Checklist is not linked to any parent task")

        parent_task_id = parent_link.parent_task_id

        parent_task = db.query(Task).filter(
            Task.task_id == parent_task_id,
            or_(
                Task.created_by == Current_user.employee_id,
                Task.assigned_to == Current_user.employee_id
            ),
            Task.is_delete == False
        ).first()

        if data.is_completed:
            time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == parent_task.task_id,TaskTimeLog.end_time == None).order_by(desc(TaskTimeLog.start_time)).first()
            if time is None:
                return {"Start time": "No active time tracking found for this task."}
        if data.is_completed == False:
            time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == parent_task.task_id).order_by(desc(TaskTimeLog.start_time)).first()
            if not time:
                return {"End time": "No active time tracking found for this task."}

        if not parent_task:
            logger.warning(f"User {Current_user.employee_id} has no access to parent task {parent_task_id}")
            raise HTTPException(status_code=403, detail="You don't have permission to update this checklist")

        logger.info(f"Checklist is linked to parent_task_id={parent_task_id}, task_type={parent_task.task_type}")

        # Step 3: Prevent changes if checklist has subtasks
        subtask_exists = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.checklist_id == data.checklist_id,
            TaskChecklistLink.sub_task_id.isnot(None)
        ).first()

        if subtask_exists:
            logger.warning(f"Checklist {data.checklist_id} has subtasks and cannot be directly updated")
            raise HTTPException(
                status_code=400,
                detail="Checklist has sub-tasks and cannot be marked as complete/incomplete directly"
            )

        # Step 4: Log and update checklist
        log_checklist_field_change(
            db,
            checklist.checklist_id,
            "is_completed",
            checklist.is_completed,
            data.is_completed,
            Current_user.employee_id
        )
        checklist.is_completed = data.is_completed
        logger.info(f"Checklist {data.checklist_id} marked as {'completed' if data.is_completed else 'incomplete'}")
         
        
        if parent_task.task_type == TaskType.Normal:
            logger.debug(f"Normal task - Propagating checklist change for parent_task_id={parent_task_id}")
            
            if data.is_completed:
                update_parent_task_status(parent_task_id, db, Current_user)
            else:
                
                propagate_incomplete_upwards(data.checklist_id, db, Current_user)

        elif parent_task.task_type == TaskType.Review:
            logger.debug(f"Review task - Processing checklist change for parent_task_id={parent_task_id}")
            review_checklists = db.query(Checklist).join(
                TaskChecklistLink,
                TaskChecklistLink.checklist_id == Checklist.checklist_id
            ).filter(
                TaskChecklistLink.parent_task_id == parent_task_id,
                Checklist.is_delete == False
            ).all()

            all_complete = all(c.is_completed for c in review_checklists)
            logger.info(f"All review checklists completed: {all_complete}")

            # Child task is the task being reviewed
            child_task = db.query(Task).filter(
                Task.parent_task_id == parent_task_id,
                Task.is_delete == False
            ).first()

            if child_task:
                if data.is_completed and all_complete:
                    parent_task.status = TaskStatus.In_Review
                    old_status = child_task.status
                    if child_task.previous_status != old_status:
                        child_task.previous_status = old_status
                    child_task.status = TaskStatus.To_Do
                    child_task.is_reviewed = False
                    logger.info(f"All review checklists done, setting child_task {child_task.task_id} status to To_Do")
                    log_task_field_change(db, child_task.task_id, "status", old_status, TaskStatus.To_Do, 2)


                elif not data.is_completed:
                    logger.info(f"Checklist marked incomplete, reverting parent_task and child_task statuses")
                    log_task_field_change(db, parent_task.task_id, "status", parent_task.status, parent_task.previous_status, Current_user.employee_id)
                    parent_task.status = "To_Do"
                    db.flush()

                    child_task.status = child_task.previous_status
                    log_task_field_change(db, child_task.task_id, "status", child_task.status, child_task.previous_status, 2)
                    logger.info(f"Child task {child_task.task_id} marked as {child_task.previous_status}")

                    db.flush()

        db.commit()
        # Step 6: Calculate checklist progress for the parent task
        parent_checklist_links = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.parent_task_id == parent_task_id
        ).all()

        parent_checklist_ids = [link.checklist_id for link in parent_checklist_links if link.checklist_id]

        parent_checklists = db.query(Checklist).filter(
            Checklist.checklist_id.in_(parent_checklist_ids),
            Checklist.is_delete == False
        ).all()

        completed_count = sum(1 for c in parent_checklists if c.is_completed)
        total_count = len(parent_checklists)
        parent_checklist_progress = f"{completed_count}/{total_count}" if total_count > 0 else "0/0"
        
        logger.info(f"Checklist status updated and committed successfully")
        # ⏱️ Add ongoing time details for the parent task (if any)
        latest_time_log = db.query(TaskTimeLog).filter(
            TaskTimeLog.task_id == parent_task_id,
            TaskTimeLog.user_id == Current_user.employee_id
        ).order_by(TaskTimeLog.start_time.desc()).first()

        if latest_time_log:
            is_ongoing = latest_time_log.end_time is None
            ongoing_start_time = latest_time_log.start_time.isoformat()
            ongoing_end_time = latest_time_log.end_time.isoformat() if latest_time_log.end_time else None
        else:
            is_ongoing = None
            ongoing_start_time = None
            ongoing_end_time = None
        return {
            "message": f"Checklist marked as {'complete' if data.is_completed else 'incomplete'} successfully",
            "checklist_id": data.checklist_id,
            "parent_task_id": parent_task_id,
            "status": parent_task.status,
            "checklist_progress": parent_checklist_progress,
            "is_ongoing": is_ongoing,
            "ongoing_start_time": ongoing_start_time,
            "ongoing_end_time": ongoing_end_time
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Unexpected error while updating checklist {data.checklist_id}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    




