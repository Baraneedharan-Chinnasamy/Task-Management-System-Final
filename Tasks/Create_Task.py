import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType, ChatRoom, User
from Logs.functions import log_task_field_change,log_checklist_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Tasks.inputs import CreateTask
from logger.logger import get_logger
from Checklist.functions import propagate_incomplete_upwards

router = APIRouter()


@router.post("/Create_Task")
def add_checklist_subtask(
    data: CreateTask,
    db: Session = Depends(get_db),
    Current_user: int = Depends(get_current_user)
):
    logger = get_logger('create_task', 'create_task.log')
    logger.info(f"Create Task endpoint hit by user_id={Current_user.employee_id}")
    logger.debug(f"Received data: {data}")

    
    try:
        # Create main task
        new_task = Task(
            task_name=data.task_name,
            description=data.description,
            due_date=data.due_date,
            assigned_to=data.assigned_to,
            status=TaskStatus.To_Do,
            created_by=Current_user.employee_id,
            is_review_required=data.is_review_required,
            previous_status=TaskStatus.To_Do
        )
        db.add(new_task)
        db.flush()
        logger.info(f"Main task created with ID={new_task.task_id}")

        db.add(ChatRoom(task_id=new_task.task_id))
        log_task_field_change(db, new_task.task_id, "status", None, "To_Do", 2)
        print(len(data.checklist_names))
        # Create checklists
        checklists_created = []
        for name in data.checklist_names:
            checklist = Checklist(
                checklist_name=name,
                is_completed=False,
                is_delete=False,
                created_by=Current_user.employee_id
            )
            db.add(checklist)
            db.flush()
            checklists_created.append(checklist)
            db.add(TaskChecklistLink(
                parent_task_id=new_task.task_id,
                checklist_id=checklist.checklist_id
            ))
            logger.info(f"Checklist {checklist.checklist_id} linked to task {new_task.task_id}")

        # Create review task if needed
        if data.is_review_required:
            review_task = Task(
                task_name=f"Review - {new_task.task_name}",
                status=TaskStatus.New,
                assigned_to=Current_user.employee_id,
                created_by=Current_user.employee_id,
                due_date=data.due_date,
                task_type=TaskType.Review,
                parent_task_id=new_task.task_id,
                previous_status=TaskStatus.New
            )
            db.add(review_task)
            db.flush()
            log_task_field_change(db, review_task.task_id, "status", None, "New", 2)

        # Handle if it's a subtask being linked to an existing checklist
        if data.checklist_id is not None:
            link = db.query(TaskChecklistLink).filter(
                TaskChecklistLink.checklist_id == data.checklist_id
            ).first()
            if not link:
                raise HTTPException(status_code=404, detail="Checklist not found")

            parent_task = db.query(Task).filter(
                Task.task_id == link.parent_task_id,
                or_(
                    Task.created_by == Current_user.employee_id,
                    Task.assigned_to == Current_user.employee_id
                ),
                Task.is_delete == False
            ).first()

            if not parent_task:
                raise HTTPException(status_code=403, detail="Task not found or unauthorized")

            if parent_task.task_type == TaskType.Review:
                raise HTTPException(status_code=400, detail="Cannot add subtask to a review task")

            db.add(TaskChecklistLink(
                checklist_id=data.checklist_id,
                sub_task_id=new_task.task_id
            ))

            logger.info(f"Subtask {new_task.task_id} linked to checklist {data.checklist_id}")
            # Trigger status/checklist propagation
            checklist = db.query(Checklist).filter(Checklist.checklist_id == data.checklist_id,Checklist.is_completed == True).first()
            if checklist:
                checklist.is_completed == False
                log_checklist_field_change(db,checklist.checklist_id,"is_completed",True,False,Current_user.employee_id)
                propagate_incomplete_upwards(data.checklist_id, db, Current_user)
        db.commit()
        users = db.query(User).filter().all()
        user_map = {u.employee_id: u.username for u in users}
        logger.info("Task and dependencies committed successfully")
        return {
            "message": "Task created successfully",
            "Checklist_id_parent": data.checklist_id if data.checklist_id else None,
            "task_id": new_task.task_id,
            "task_name": new_task.task_name,
            "description": new_task.description,
            "status": new_task.status,
            "assigned_to": new_task.assigned_to,
            "assigned_to_name": user_map.get(new_task.assigned_to),
            "due_date": new_task.due_date,
            "created_by": new_task.created_by,
            "created_by_name": user_map.get(new_task.created_by),
            "created_at": new_task.created_at,
            "updated_at": new_task.updated_at,
            "task_type": new_task.task_type,
            "is_review_required": new_task.is_review_required,
            "checklist_progress":f"0/{len(data.checklist_names)}" if len(data.checklist_names) > 0 else 2,
            "checklists_created": [
    {
        "checklist_id": c.checklist_id,
        "checklist_name": c.checklist_name,
        "created_by": c.created_by,
        "created_by_name": user_map.get(c.created_by)
    }
    for c in checklists_created
]

        }

    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while creating task")
        raise HTTPException(status_code=500, detail="Internal Server Error")
