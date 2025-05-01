import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, TaskType, TaskChecklistLink, Checklist
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Tasks.inputs import UpdateTaskRequest, SendForReview
from Tasks.functions import reverse_completion_from_review,propagate_completion_upwards
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
                if task.task_type == TaskType.Normal:
                    if task_data.is_review_required:
                        task.is_review_required = True
                        log_task_field_change(db, task.task_id, "is_review_required", False, True, Current_user.employee_id)
                        if task.is_review_required:
                            existing_review = db.query(Task).filter(
                                Task.parent_task_id == task_id,
                                Task.task_type == TaskType.Review
                            ).first()

                            if existing_review and existing_review.is_delete:
                                print("Hi")
                                existing_review.is_delete = False
                                task.is_review_required = True
                                log_task_field_change(db, existing_review.task_id, "is_delete", True, False, Current_user.employee_id)
                                logger.info(f"Re-enabled review task {existing_review.task_id}")
                            elif not existing_review:
                                review_task = Task(
                                    task_name=f"Review - {task.task_name}",
                                    status=TaskStatus.New.name,
                                    assigned_to=task.created_by,
                                    created_by=Current_user.employee_id,
                                    due_date=task.due_date,
                                    task_type=TaskType.Review,
                                    parent_task_id=task.task_id,
                                    previous_status = TaskStatus.New.name)
                                db.add(review_task)
                                db.flush()
                                log_task_field_change(db, review_task.task_id, "status", None, "New", 2)
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


        if task_data.is_reviewed is not None and task.task_type == TaskType.Review:
            checklists = db.query(Checklist).join(TaskChecklistLink).filter(
                TaskChecklistLink.parent_task_id == task.task_id,
                Checklist.is_delete == False
            ).all()

            # Step 1: Prevent non-leaf review tasks from setting is_reviewed=True
            child_review_exists = db.query(Task).filter(
                Task.parent_task_id == task.task_id,
                Task.task_type == TaskType.Review,
                Task.is_delete == False
            ).first()
            if child_review_exists:
                    logger.warning("Only the final review task can mark is_reviewed=True")
                    raise HTTPException(status_code=403, detail="Only the last review task in the chain can mark this")

            if task_data.is_reviewed:
                checklists = db.query(Checklist).join(TaskChecklistLink).filter(
                    TaskChecklistLink.parent_task_id == task_data.task_id,
                    Checklist.is_delete == False
                ).all()
                if checklists and not all(c.is_completed for c in checklists):
                    logger.warning("Not all checklists completed in review chain")
                    raise HTTPException(status_code=403, detail="All checklists must be completed before marking reviewed")
                if checklists and  all(c.is_completed for c in checklists):
                    task.is_reviewed = True
                    log_task_field_change(db, task.task_id, "is_reviewed", False, True, Current_user.employee_id)
                    task.previous_status == task.status
                    task.status == TaskStatus.Completed.name
                    propagate_completion_upwards(task, db, Current_user.employee_id, logger)
                task.is_reviewed = True
                log_task_field_change(db, task.task_id, "is_reviewed", True, False, Current_user.employee_id)
                task.previous_status = task.status
                task.status = TaskStatus.Completed.name
                propagate_completion_upwards(task, db, Current_user.employee_id, logger,Current_user)
            else:
                
                task.is_reviewed = False
                log_task_field_change(db, task.task_id, "is_reviewed", True, False, Current_user.employee_id)
                reverse_completion_from_review(task, db, Current_user.employee_id, logger,Current_user)
    

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
    logger = get_logger("send_for_review", "send_for_review.log")
    logger.info(f"POST /send_for_review called by user_id={Current_user.employee_id} for task_id={data.task_id}")
    try:
        task = db.query(Task).filter(
            Task.task_id == data.task_id,
            Task.is_delete == False,
            or_(Task.created_by == Current_user.employee_id, Task.assigned_to == Current_user.employee_id)
        ).first()

        if not task:
            logger.warning(f"Task not found or unauthorized for user {Current_user.employee_id}")
            raise HTTPException(status_code=404, detail="Task not found or unauthorized")

        if task.task_type != TaskType.Review:
            raise HTTPException(status_code=400, detail="Only review tasks can send for further review.")

        # Check if a child review task already exists
        next_review = db.query(Task).filter(
            Task.parent_task_id == task.task_id,
            Task.task_type == TaskType.Review,
            Task.is_delete == False
        ).first()

        if next_review:
            raise HTTPException(status_code=400, detail="Already sent for further review. Cannot send again.")

        # Mark that review is required
        task.is_review_required = True
        task.status = TaskStatus.In_Review

        # Create a new review task
        review_task = Task(
            task_name=f"{task.task_name}",
            status=TaskStatus.To_Do.name,  
            assigned_to=data.assigned_to,
            created_by=Current_user.employee_id,
            due_date=task.due_date,
            task_type=TaskType.Review,
            parent_task_id=task.task_id,
            previous_status = TaskStatus.To_Do.name

        )
        db.add(review_task)
        db.flush()  

        db.commit()
        logger.info(f"Review task {review_task.task_id} created successfully")

        return {"message": "Review task created successfully", "review_task_id": review_task.task_id}

    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error while sending for review")
        raise HTTPException(status_code=500, detail="Internal Server Error")
