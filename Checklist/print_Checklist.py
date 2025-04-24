from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import or_, update, asc, desc
from models.models import Task, Checklist, TaskChecklistLink
from database.database import get_db
from Checklist.inputs import checklist_sub
from logger.logger import get_logger


router = APIRouter()



@router.post("/Print_Checklist")
def get_checklists_by_task(
    payload: checklist_sub,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1)
):
    logger = get_logger('print_checklist', 'print_checklist.log')
    logger.info(f"POST /Print_Checklist called for task_id={payload.task_id} | Page={page} | Limit={limit}")

    offset = (page - 1) * limit

    total = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.parent_task_id == payload.task_id
    ).count()
    total_pages = (total + limit - 1) // limit  # Ceiling division

    logger.info(f"Total checklists found: {total} | Total pages: {total_pages}")

    links = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.parent_task_id == payload.task_id
    ).offset(offset).limit(limit).all()

    checklist_data = []
    skipped_checklists = 0

    for link in links:
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == link.checklist_id,
            Checklist.is_delete == False
        ).first()

        if not checklist:
            logger.warning(f"Checklist not found or deleted for link_id={link.link_id}")
            skipped_checklists += 1
            continue

        logger.debug(f"Processing checklist_id={checklist.checklist_id}")

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
                logger.warning(f"Subtask with ID={task.sub_task_id} not found or deleted.")
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
        logger.debug(f"Checklist {checklist.checklist_id} delete_allow={delete_allow} | Subtasks count={len(subtasks)}")

        checklist_data.append({
            "checklist_id": checklist.checklist_id,
            "checklist_name": checklist.checklist_name,
            "is_completed": checklist.is_completed,
            "subtasks": subtasks,
            "delete_allow": delete_allow
        })

    logger.info(f"Returning {len(checklist_data)} checklists | Skipped: {skipped_checklists}")

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
        "checklists": checklist_data
    }
