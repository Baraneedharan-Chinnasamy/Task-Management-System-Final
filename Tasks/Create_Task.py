import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, Checklist, TaskChecklistLink, TaskType, ChatRoom
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Tasks.inputs import CreateTask
from logger.logger import get_logger

router = APIRouter()


@router.post("/Create_Task")
def add_checklist_subtask(
    data: CreateTask,
    db: Session = Depends(get_db),
    Current_user: int = Depends(get_current_user)
):
    """
    Create a new task with associated checklists and optionally link it to an existing checklist.
    Also creates a review task if review is required.
    """
    logger = get_logger('create_task', 'create_task.log')
    logger.info(f"Create Task endpoint hit by user_id={Current_user.employee_id}")
    logger.debug(f"Received data: {data}")

    try:
        # Create the main task
        logger.info("Creating main task...")
        new_task = Task(
            task_name=data.task_name,
            description=data.description,
            due_date=data.due_date,
            assigned_to=data.assigned_to,
            status=TaskStatus.To_Do,
            created_by=Current_user.employee_id,
            is_review_required=data.is_review_required
        )
        db.add(new_task)
        db.flush()  # Get task_id before commit
        logger.info(f"Main task created with ID={new_task.task_id}")

        # Create chat room for the task
        logger.info(f"Creating chat room for task_id={new_task.task_id}")
        new_chat_room = ChatRoom(task_id=new_task.task_id)
        db.add(new_chat_room)

        # Log status change
        logger.info(f"Logging initial status change for task_id={new_task.task_id}")
        log_task_field_change(db, new_task.task_id, "status", None, "To_Do", 2)

        # Create and link checklists
        checklists_created = []
        logger.info(f"Creating {len(data.checklist_names)} checklists...")
        for name in data.checklist_names:
            checklist = Checklist(
                checklist_name=name,
                is_completed=False,
                is_delete=False
            )
            db.add(checklist)
            db.flush()
            checklists_created.append(checklist)
            logger.info(f"Checklist created with ID={checklist.checklist_id}")

            task_checklist_link = TaskChecklistLink(
                parent_task_id=new_task.task_id,
                checklist_id=checklist.checklist_id,
                sub_task_id=None
            )
            db.add(task_checklist_link)
            logger.info(f"Linked checklist_id={checklist.checklist_id} to task_id={new_task.task_id}")

        # Create review task if needed
        if data.is_review_required:
            logger.info("Creating review task...")
            review_task = Task(
                task_name=f"Review - {new_task.task_name}",
                description="Review task",
                status=TaskStatus.To_Do.name,
                assigned_to=Current_user.employee_id,
                created_by=Current_user.employee_id,
                due_date=data.due_date,
                task_type=TaskType.Review,
                parent_task_id=new_task.task_id
            )
            db.add(review_task)
            logger.info(f"Review task created with parent_task_id={new_task.task_id}")

        # Handle linking to existing checklist
        if data.checklist_id is not None:
            logger.info(f"Attempting to link to existing checklist_id={data.checklist_id}")
            parent_task_relation = db.query(TaskChecklistLink.parent_task_id).filter(
                TaskChecklistLink.checklist_id == data.checklist_id
            ).first()

            if not parent_task_relation:
                logger.error(f"Checklist with ID {data.checklist_id} not found")
                raise HTTPException(status_code=404, detail="Checklist not found")

            parent_task_id = parent_task_relation[0]
            logger.info(f"Checklist {data.checklist_id} linked to parent_task_id={parent_task_id}")

            task = db.query(Task).filter(
                Task.task_id == parent_task_id,
                or_(Task.created_by == Current_user.employee_id, Task.assigned_to == Current_user.employee_id),
                Task.is_delete == False
            ).first()

            if not task:
                logger.error(f"User {Current_user.employee_id} unauthorized or task not found for parent_task_id={parent_task_id}")
                raise HTTPException(status_code=403, detail="Task not found or you don't have permission")

            if task.task_type == TaskType.Review:
                logger.error(f"Cannot add subtask to review task with ID={task.task_id}")
                raise HTTPException(status_code=400, detail="Cannot add subtask to a review task")

            task_checklist_link_sub = TaskChecklistLink(
                parent_task_id=None,
                checklist_id=data.checklist_id,
                sub_task_id=new_task.task_id
            )
            db.add(task_checklist_link_sub)
            logger.info(f"Linked new task_id={new_task.task_id} as subtask to checklist_id={data.checklist_id}")

        # Final commit
        db.commit()
        logger.info(f"Task {new_task.task_id} created and committed successfully")

        return {
            "message": "Task created successfully",
            "task_id": new_task.task_id,
            "checklists_created": len(checklists_created)
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Unexpected error while creating task: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
