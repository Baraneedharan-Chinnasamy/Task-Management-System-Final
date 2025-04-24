import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, TaskType, TaskChecklistLink, Checklist
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Tasks.inputs import UpdateTaskRequest, SendForReview
from Tasks.functions import Mark_complete_help, upload_output_to_all_reviews
from logger.logger import get_logger

router = APIRouter()


@router.post("/update_task")
def update_task(task_data: UpdateTaskRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    logger = get_logger("update_task", "update_task.log")
    logger.info(f"POST /update_task called by user_id={Current_user.employee_id}")
    logger.debug(f"Task update request: {task_data}")

    try:
        if not task_data.task_id:
            logger.warning("Task ID not provided")
            raise HTTPException(status_code=400, detail="Task ID is required")

        task_id = task_data.task_id
        update_fields = {}

        task = db.query(Task).filter(Task.task_id == task_id, Task.is_delete == False).first()

        if not task:
            logger.warning(f"Task ID {task_id} not found")
            raise HTTPException(status_code=404, detail="Task not found")

        is_creator = task.created_by == Current_user.employee_id
        is_assignee = task.assigned_to == Current_user.employee_id

        if not (is_creator or is_assignee):
            logger.warning(f"Unauthorized update attempt by user_id={Current_user.employee_id}")
            raise HTTPException(status_code=403, detail="You don't have permission to update this task")

        logger.info(f"User {Current_user.employee_id} is updating Task {task_id} | Creator={is_creator}, Assignee={is_assignee}")

        # Only creator can update certain fields
        if is_creator:
            if task_data.assigned_to is not None:
                log_task_field_change(db, task.task_id, "assigned_to", task.assigned_to, task_data.assigned_to, Current_user.employee_id)
                task.assigned_to = task_data.assigned_to
                update_fields['assigned_to'] = task_data.assigned_to
                logger.info("Assigned_to updated")

            if task_data.due_date is not None:
                log_task_field_change(db, task.task_id, "due_date", task.due_date, task_data.due_date, Current_user.employee_id)
                task.due_date = task_data.due_date
                update_fields['due_date'] = task_data.due_date
                logger.info("Due date updated")

            if task_data.is_review_required is not None:
                log_task_field_change(db, task.task_id, "is_review_required", task.is_review_required, task_data.is_review_required, Current_user.employee_id)
                if task_data.is_review_required:
                    if not task.is_review_required:
                        existing_review = db.query(Task).filter(
                            Task.parent_task_id == task_id,
                            Task.task_type == TaskType.Review
                        ).first()

                        if existing_review and existing_review.is_delete:
                            existing_review.is_delete = False
                            task.is_review_required = True
                            log_task_field_change(db, existing_review.task_id, "is_delete", True, False, Current_user.employee_id)
                            logger.info(f"Re-enabled review task {existing_review.task_id}")
                        elif not existing_review:
                            review_task = Task(
                                task_name=f"Review - {task.task_name}",
                                description="Review task",
                                status=TaskStatus.To_Do.name,
                                assigned_to=task.created_by,
                                created_by=Current_user.employee_id,
                                due_date=task.due_date,
                                task_type=TaskType.Review,
                                parent_task_id=task.task_id
                            )
                            db.add(review_task)
                            db.flush()
                            log_task_field_change(db, review_task.task_id, "status", None, "To_Do", 2)
                            logger.info(f"Review task created: {review_task.task_id}")
                    update_fields['is_review_required'] = True
                else:
                    task.is_review_required = False
                    update_fields['is_review_required'] = False
                    review_task = db.query(Task).filter(
                        Task.parent_task_id == task_id,
                        Task.task_type == TaskType.Review,
                        Task.is_delete == False
                    ).first()

                    if review_task:
                        dependent_tasks = db.query(Task).filter(
                            Task.parent_task_id == review_task.task_id,
                            Task.is_delete == False
                        ).first()

                        if dependent_tasks:
                            logger.warning(f"Cannot remove review requirement for task {task_id} — has dependents")
                            raise HTTPException(status_code=400, detail="Cannot remove review requirement - there are tasks linked to the review task")

                        log_task_field_change(db, review_task.task_id, "is_delete", False, True, Current_user.employee_id)
                        review_task.is_delete = True
                        logger.info(f"Review task {review_task.task_id} marked as deleted")

        else:
            for field in ['assigned_to', 'due_date', 'is_review_required']:
                if getattr(task_data, field) is not None:
                    logger.warning(f"Non-creator user tried to update '{field}', ignoring")

        # Shared fields
        if task_data.task_name is not None:
            log_task_field_change(db, task.task_id, "task_name", task.task_name, task_data.task_name, Current_user.employee_id)
            task.task_name = task_data.task_name
            update_fields['task_name'] = task_data.task_name

        if task_data.description is not None:
            log_task_field_change(db, task.task_id, "description", task.description, task_data.description, Current_user.employee_id)
            task.description = task_data.description
            update_fields['description'] = task_data.description

        if task_data.output is not None:
            log_task_field_change(db, task.task_id, "output", task.output, task_data.output, Current_user.employee_id)
            task.output = task_data.output
            update_fields['output'] = task_data.output

            if task.is_review_required:
                review_task = db.query(Task).filter(
                    Task.task_type == TaskType.Review,
                    Task.parent_task_id == task.task_id,
                    Task.is_delete == False
                ).first()
                upload_output_to_all_reviews(review_task.task_id, task_data.output, db, Current_user)
                logger.info(f"Output updated across review task {review_task.task_id}")

        if task_data.is_reviewed is not None and task.task_type == TaskType.Review:
            checklists = db.query(Checklist).join(TaskChecklistLink).filter(
                TaskChecklistLink.parent_task_id == task.task_id,
                Checklist.is_delete == False,
                TaskChecklistLink.checklist_id != None,
            ).all()

            if task_data.is_reviewed and checklists and not all(c.is_completed for c in checklists):
                logger.warning("Cannot mark review task as reviewed — not all checklist items are completed")
                raise HTTPException(status_code=403, detail="All checklist items must be completed before marking the review task as reviewed.")

            task.is_reviewed = task_data.is_reviewed
            update_fields['is_reviewed'] = task_data.is_reviewed

            new_status = TaskStatus.Completed if task_data.is_reviewed else TaskStatus.To_Do
            if task.status != new_status:
                log_task_field_change(db, task.task_id, "status", task.status, new_status, Current_user.employee_id)
                task.status = new_status
                update_fields['status'] = new_status.name
                logger.info(f"Review task {task_id} marked as {new_status.name}")

        if task_data.mark_complete and task.task_type == TaskType.Review:
            parent_task = db.query(Task).filter(
                Task.task_id == task.parent_task_id,
                Task.is_delete == False
            ).first()

            if parent_task and parent_task.task_type == TaskType.Normal:
                incomplete_checklists = db.query(Checklist).join(TaskChecklistLink).filter(
                    TaskChecklistLink.parent_task_id == parent_task.task_id,
                    Checklist.is_completed == False,
                    Checklist.is_delete == False
                ).count()

                if incomplete_checklists > 0:
                    logger.warning("Cannot mark task complete — incomplete checklists exist")
                    raise HTTPException(status_code=400, detail="All linked checklists must be completed before marking this task complete.")

                old_status = parent_task.status
                parent_task.status = TaskStatus.Completed
                log_task_field_change(db, parent_task.task_id, "status", old_status, TaskStatus.Completed, Current_user.employee_id)
                update_fields['parent_task_completed'] = True
                Mark_complete_help(parent_task.task_id, db, Current_user)
                logger.info(f"Parent task {parent_task.task_id} marked as Completed")

        db.commit()
        logger.info(f"Task {task_id} updated successfully with changes: {update_fields}")
        return {"message": "Task updated successfully", "updated_fields": update_fields}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while updating task")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/send_for_review")
def send_for_review(data: SendForReview, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    logger = get_logger("update_task", "update_task.log")
    logger.info(f"POST /send_for_review called by user_id={Current_user.employee_id} for task_id={data.task_id}")
    try:
        task = db.query(Task).filter(
            Task.task_id == data.task_id,
            Task.task_type == TaskType.Review,
            or_(Task.created_by == Current_user.employee_id, Task.assigned_to == Current_user.employee_id),
            Task.is_delete == False
        ).first()

        task.is_review_required = True
        db.flush()

        if not task:
            logger.warning(f"Review task not found or not authorized for user {Current_user.employee_id}")
            raise HTTPException(status_code=404, detail="Review task not found or unauthorized")

        review_task = Task(
            task_name=task.task_name,
            description="Review task",
            status=TaskStatus.To_Do.name,
            assigned_to=data.assigned_to,
            created_by=Current_user.employee_id,
            due_date=task.due_date,
            task_type=TaskType.Review,
            parent_task_id=task.task_id,
            output=task.output
        )
        db.add(review_task)
        db.commit()
        logger.info(f"Review task {review_task.task_id} created successfully")
        return {"message": "Review Task Created successfully"}

    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while sending for review")
        raise HTTPException(status_code=500, detail="Internal Server Error")
