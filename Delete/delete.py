import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_, update
from models.models import Task,  Checklist, TaskChecklistLink
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Delete.inputs import DeleteItemsRequest
from Delete.functions import get_related_tasks_checklists_logic
from Logs.functions import log_checklist_field_change,log_task_field_change


router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/delete")
def delete_related_items(
    delete_request: DeleteItemsRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)
):
    # Validate the request
    task_id = delete_request.task_id
    checklist_id = delete_request.checklist_id

    # employee id and created by id should be same
    if task_id:
        task = db.query(Task).filter(Task.task_id == task_id, Task.created_by == Current_user.employee_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found or employee is not the creator of the task.")
    elif checklist_id:
        parent_task = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.checklist_id == checklist_id,
            TaskChecklistLink.parent_task_id.isnot(None)
        ).first()
        task = db.query(Task).filter(Task.task_id == parent_task.parent_task_id, Task.created_by == Current_user.employee_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found or employee is not the creator of the task.")


    # Get the related tasks and checklists
    result = get_related_tasks_checklists_logic(db, task_id, checklist_id)
    tasks_to_delete = result.get("tasks", [])
    checklists_to_delete = result.get("checklists", [])

    if not tasks_to_delete and not checklists_to_delete:
        raise HTTPException(status_code=404, detail="No related tasks or checklists found")
    
    def get_all_review_tasks(db: Session, base_task_ids: list[int]) -> set[int]:
        all_task_ids = set(base_task_ids)
        queue = list(base_task_ids)

        while queue:
            current_id = queue.pop(0)
            child_tasks = db.query(Task).filter(
                Task.parent_task_id == current_id,
                Task.is_delete == False
            ).all()

            for task in child_tasks:
                if task.task_id not in all_task_ids:
                    all_task_ids.add(task.task_id)
                    queue.append(task.task_id)

        return all_task_ids
    
    tasks_to_delete = get_all_review_tasks(db, tasks_to_delete)


    # Mark tasks as deleted
    # Mark tasks as deleted
    if tasks_to_delete:
        db.execute(
        update(Task)
        .where(Task.task_id.in_(tasks_to_delete))
        .values(is_delete=True))
    for task_id in tasks_to_delete:
        log_task_field_change(db, task_id, 'is_delete', False, True, Current_user.employee_id)  # pass actual user_id

# Mark checklists as deleted
    if checklists_to_delete:
        db.execute(
        update(Checklist)
        .where(Checklist.checklist_id.in_(checklists_to_delete))
        .values(is_delete=True))
    for checklist_id in checklists_to_delete:
        log_checklist_field_change(db, checklist_id, 'is_delete', False, True,Current_user.employee_id)


    db.commit() 

    return {"message": "Related tasks and checklists marked as deleted", "tasks": tasks_to_delete, "checklists": checklists_to_delete}