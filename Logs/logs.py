from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.database import get_db
from models.models import (
    Task, User, TaskUpdateLog, Checklist, ChecklistUpdateLog,
    TaskChecklistLink, TaskType
)
from Currentuser.currentUser import get_current_user

router = APIRouter()

@router.get("/log_summary")
def get_task_log_summary(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    logs = []

    creator = db.query(User).filter(User.employee_id == task.created_by).first()
    assignee = db.query(User).filter(User.employee_id == task.assigned_to).first()

    logs.append(f"Task '{task.task_name}' was created by {creator.username if creator else 'Unknown'} on {task.created_at.strftime('%Y-%m-%d %H:%M:%S')}.")

    if task.due_date:
        logs.append(f"Due date set to {task.due_date.strftime('%Y-%m-%d')}.")

    if assignee:
        logs.append(f"Assigned to {assignee.username} (ID: {assignee.employee_id}).")

    # Checklist creation logs
    checklist_links = db.query(TaskChecklistLink).filter(TaskChecklistLink.parent_task_id == task_id).all()
    checklist_ids = []
    for link in checklist_links:
        checklist = db.query(Checklist).filter(Checklist.checklist_id == link.checklist_id).first()
        if checklist:
            logs.append(f"Checklist '{checklist.checklist_name}' was added on {checklist.created_at.strftime('%Y-%m-%d %H:%M:%S')}.")
            checklist_ids.append(checklist.checklist_id)

    # Subtask logs
    subtask_links = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.checklist_id.in_(checklist_ids),
        TaskChecklistLink.sub_task_id.isnot(None)
    ).all()

    for sub_link in subtask_links:
        sub_task = db.query(Task).filter(Task.task_id == sub_link.sub_task_id).first()
        if sub_task:
            logs.append(f"Subtask '{sub_task.task_name}' was created under checklist ID {sub_link.checklist_id}.")
            if sub_task.description:
                logs.append(f"→ Description: {sub_task.description}")
            if sub_task.due_date:
                logs.append(f"→ Due Date: {sub_task.due_date.strftime('%Y-%m-%d')}")
            logs.append(f"→ Status: {sub_task.status.value}")
            if sub_task.output:
                logs.append(f"→ Output: {sub_task.output}")
            logs.append(f"→ Review Required: {'Yes' if sub_task.is_review_required else 'No'}")

            # Subtask deletion log
            if sub_task.is_delete:
                delete_log = db.query(TaskUpdateLog).filter(
                    TaskUpdateLog.task_id == sub_task.task_id,
                    TaskUpdateLog.field_name == 'is_delete',
                    TaskUpdateLog.new_value == 'True'
                ).order_by(TaskUpdateLog.updated_at.desc()).first()

                if delete_log:
                    deleter = db.query(User).filter(User.employee_id == delete_log.updated_by).first()
                    deleter_name = deleter.username if deleter else "Unknown"
                    logs.append(
                        f"❌ Subtask '{sub_task.task_name}' was marked as deleted by {deleter_name} (ID: {delete_log.updated_by}) on {delete_log.updated_at.strftime('%Y-%m-%d %H:%M:%S')}."
                    )

            # Subtask field updates (output, due_date, assigned_to)
            sub_updates = db.query(TaskUpdateLog).filter(
                TaskUpdateLog.task_id == sub_task.task_id,
                TaskUpdateLog.field_name.in_(["output", "due_date", "assigned_to"])
            ).all()
            for log in sub_updates:
                updater = db.query(User).filter(User.employee_id == log.updated_by).first()
                uname = updater.username if updater else "Unknown"
                logs.append(
                    f"{uname} updated subtask '{sub_task.task_name}' field '{log.field_name}': '{log.old_value}' → '{log.new_value}' on {log.updated_at.strftime('%Y-%m-%d %H:%M:%S')}."
                )

    # Review task section
    if task.is_review_required:
        review_task = db.query(Task).filter(
            Task.parent_task_id == task.task_id,
            Task.task_type == TaskType.Review
        ).first()
        if review_task:
            reviewer = db.query(User).filter(User.employee_id == review_task.assigned_to).first()
            reviewer_info = f"{reviewer.username} (ID: {reviewer.employee_id})" if reviewer else f"User {review_task.assigned_to}"
            logs.append(f"Review required. A review task (ID: {review_task.task_id}) was created and assigned to {reviewer_info}.")

            # Review task field updates
            review_updates = db.query(TaskUpdateLog).filter(
                TaskUpdateLog.task_id == review_task.task_id,
                TaskUpdateLog.field_name.in_(["output", "due_date", "assigned_to"])
            ).all()
            for log in review_updates:
                updater = db.query(User).filter(User.employee_id == log.updated_by).first()
                uname = updater.username if updater else "Unknown"
                logs.append(
                    f"{uname} updated review task '{review_task.task_name}' field '{log.field_name}': '{log.old_value}' → '{log.new_value}' on {log.updated_at.strftime('%Y-%m-%d %H:%M:%S')}."
                )

    # Main task field update logs
    task_updates = db.query(TaskUpdateLog).filter(TaskUpdateLog.task_id == task_id).order_by(TaskUpdateLog.updated_at).all()
    initial_status_logged = False
    for log in task_updates:
        user = db.query(User).filter(User.employee_id == log.updated_by).first()
        username = user.username if user else "Unknown"

        if log.field_name == "status" and log.old_value in [None, "None"] and not initial_status_logged:
            logs.append(f"Status was initially set to '{log.new_value}' by {username} on {log.updated_at.strftime('%Y-%m-%d %H:%M:%S')}.")
            initial_status_logged = True
            continue

        logs.append(
            f"{username} updated task field '{log.field_name}': '{log.old_value}' → '{log.new_value}' on {log.updated_at.strftime('%Y-%m-%d %H:%M:%S')}."
        )

    # Checklist updates
    checklist_updates = db.query(ChecklistUpdateLog).filter(ChecklistUpdateLog.checklist_id.in_(checklist_ids)).order_by(ChecklistUpdateLog.updated_at).all()
    for log in checklist_updates:
        checklist = db.query(Checklist).filter(Checklist.checklist_id == log.checklist_id).first()
        user = db.query(User).filter(User.employee_id == log.updated_by).first()
        checklist_name = checklist.checklist_name if checklist else f"Checklist {log.checklist_id}"
        username = user.username if user else "Unknown"
        logs.append(
            f"{username} changed checklist '{checklist_name}' field '{log.field_name}': '{log.old_value}' → '{log.new_value}' on {log.updated_at.strftime('%Y-%m-%d %H:%M:%S')}."
        )

    return {
        "task_id": task.task_id,
        "task_name": task.task_name,
        "log_summary": logs
    }
