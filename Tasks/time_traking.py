from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from models.models import TaskTimeLog, Task
from database.database import get_db
from Currentuser.currentUser import get_current_user

router = APIRouter()


@router.post("/start_timer")
def start_task_timer(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: int = Depends(get_current_user)
):
    # Check if task exists
    task = db.query(Task).filter(Task.task_id == task_id, Task.is_delete == False).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Check for an existing open session
    existing_log = db.query(TaskTimeLog).filter(
        TaskTimeLog.task_id == task_id,
        TaskTimeLog.end_time == None
    ).first()

    if existing_log:
        raise HTTPException(status_code=400, detail="Time tracking already in progress for this task")

    # Create a new log entry
    time_log = TaskTimeLog(
        task_id=task_id,
        user_id=current_user.employee_id,
        start_time=datetime.now(),
        end_time=None,
        is_paused=False
    )

    db.add(time_log)
    
    db.commit()
    db.refresh(time_log)

    return {
        "message": "Time tracking started",
        "log_id": time_log.id,
        "task_id": time_log.task_id,
        "user_id": time_log.user_id,
        "start_time": time_log.start_time
    }
