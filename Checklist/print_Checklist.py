from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import or_, update, asc, desc
from models.models import Task, Checklist, TaskChecklistLink
from database.database import get_db
from Checklist.inputs import checklist_sub

router = APIRouter()

@router.post("/Print_Checklist")
def get_checklists_by_task(
    payload: checklist_sub,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1)
):
    offset = (page - 1) * limit

    # Get total count before pagination
    total = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.parent_task_id == payload.task_id
    ).count()
    total_pages = (total + limit - 1) // limit  # Ceiling division

    # Paginate checklist links
    links = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.parent_task_id == payload.task_id
    ).offset(offset).limit(limit).all()

    checklist_data = []

    for link in links:
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == link.checklist_id,
            Checklist.is_delete == False
        ).first()

        if not checklist:
            continue

        # Fetch subtasks
        subtasks = []
        checklist_links = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.checklist_id == checklist.checklist_id
        ).all()

        for task in checklist_links:
            if task.sub_task_id is None:
                continue

            task_obj = db.query(Task).filter(
                Task.task_id == task.sub_task_id,
                Task.is_delete == False
            ).first()

            if not task_obj:
                continue

            subtasks.append({
                "task_id": task_obj.task_id,
                "task_name": task_obj.task_name,
                "description": task_obj.description,
                "status": task_obj.status,
                "assigned_to": task_obj.assigned_to,
                "due_date": task_obj.due_date,
                "created_by": task_obj.created_by,
                "created_at": task_obj.created_at,
                "updated_at": task_obj.updated_at,
                "task_type": task_obj.task_type,
                "is_review_required": task_obj.is_review_required,
                "output": task_obj.output
            })

        delete_allow = False if subtasks else True

        checklist_data.append({
            "checklist_id": checklist.checklist_id,
            "checklist_name": checklist.checklist_name,
            "is_completed": checklist.is_completed,
            "subtasks": subtasks,
            "delete_allow": delete_allow
        })

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "checklists": checklist_data
    }
