import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.sql import or_
from models.models import Task, TaskStatus, TaskType, TaskChecklistLink,Checklist
from Logs.functions import log_task_field_change
from database.database import get_db
from Currentuser.currentUser import get_current_user
from Tasks.inputs import UpdateTaskRequest,SendForReview
from Tasks.functions import Mark_complete_help,upload_output_to_all_reviews


router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/update_task/")
def update_task(task_data: UpdateTaskRequest, db: Session = Depends(get_db), Current_user: int = Depends(get_current_user)):
    """
    Update a task with new information.
    Only the task creator can change assignee, due date, and review requirements.
    Both creator and assignee can update other fields.
    """
    try:
        if not task_data.task_id:
            raise HTTPException(status_code=400, detail="Task ID is required")
            
        task_id = task_data.task_id
        update_fields = {}
        
        # Get the task and check permissions in one query
        task = db.query(Task).filter(
            Task.task_id == task_id,
            Task.is_delete == False
        ).first()
        
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check if user has permission to edit this task
        is_creator = task.created_by == Current_user.employee_id
        is_assignee = task.assigned_to == Current_user.employee_id
        
        if not (is_creator or is_assignee):
            raise HTTPException(status_code=403, detail="You don't have permission to update this task")
        
        # Fields that only the creator can update
        if is_creator:
            # Update assigned_to if provided
            if task_data.assigned_to is not None:
                log_task_field_change(db, task.task_id,"assigned_to", task.assigned_to, task_data.assigned_to,Current_user.employee_id)
                task.assigned_to = task_data.assigned_to
                update_fields['assigned_to'] = task_data.assigned_to
                
            
            # Update due_date if provided
            if task_data.due_date is not None:
                task.due_date = task_data.due_date
                log_task_field_change(db, task.task_id,"due_date", task.due_date, task_data.due_date,Current_user.employee_id)
                update_fields['due_date'] = task_data.due_date
            
            # Handle review requirement changes
            if task_data.is_review_required is not None:
                log_task_field_change(db, task.task_id,"is_review_required", task.is_review_required, task_data.is_review_required,Current_user.employee_id)
                if task_data.is_review_required:
                    # Enable review if it wasn't already enabled
                    
                    if not task.is_review_required:
                        # Check if a review task already exists but is marked as deleted
                        existing_review = db.query(Task).filter(
                            Task.parent_task_id == task_id,
                            Task.task_type == TaskType.Review
                        ).first()
                        
                        
                        
                        if existing_review and existing_review.is_delete:
                            task.is_review_required = True
                            log_task_field_change(db, existing_review.task_id,"is_delete",True, False,Current_user.employee_id)
                            # Re-enable existing review task
                            existing_review.is_delete = False
                            logger.info(f"Review task re-enabled: {existing_review.task_id}")
                        elif not existing_review:
                            # Create new review task
                            task.is_review_required = True
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
                            log_task_field_change(db, review_task.task_id,"status",None, "To_Do",Current_user.employee_id)
                            update_fields['is_review_required'] = True
                            logger.info(f"Review task created: {review_task.task_id}")
                    update_fields['is_review_required'] = True
                else:
                    # Disable review
                    task.is_review_required = False
                    update_fields['is_review_required'] = False
                    
                    # Find review task and mark as deleted
                    review_task = db.query(Task).filter(
                        Task.parent_task_id == task_id,
                        Task.task_type == TaskType.Review,
                        Task.is_delete == False
                    ).first()

                    if review_task:
                        # Check if this review task has dependents
                        dependent_tasks = db.query(Task).filter(
                            Task.parent_task_id == review_task.task_id,
                            Task.is_delete == False
                        ).first()
                        
                        if dependent_tasks:
                            raise HTTPException(
                                status_code=400,
                                detail="Cannot remove review requirement - there are tasks linked to the review task"
                            )
                        else:
                            log_task_field_change(db, review_task.task_id,"is_delete",False, True,Current_user.employee_id)
                            review_task.is_delete = True
                            logger.info(f"Review task marked as deleted: {review_task.task_id}")
        elif not is_creator:
            # If non-creator tries to update restricted fields, reject those changes
            for field in ['assigned_to', 'due_date', 'is_review_required']:
                if getattr(task_data, field) is not None:
                    logger.warning(f"Non-creator tried to update {field}, ignoring this change")
        
        # Fields that both creator and assignee can update
        if task_data.task_name is not None:
            log_task_field_change(db,task.task_id,"task_name",task.task_name,task_data.task_name,Current_user.employee_id)
            task.task_name = task_data.task_name
            
            update_fields['task_name'] = task_data.task_name
            
        if task_data.description is not None:
            log_task_field_change(db,task.task_id,"description",task.description,task_data.description,Current_user.employee_id)
            task.description = task_data.description
            update_fields['description'] = task_data.description
            
        if task_data.output is not None:
            log_task_field_change(db,task.task_id,"output",task.output,task_data.output,Current_user.employee_id)
            task.output = task_data.output
            update_fields['output'] = task_data.output
            
            # Update output in review task if it exists
            if task.is_review_required:
                review_task = db.query(Task).filter(
                    Task.task_type == TaskType.Review,
                    Task.parent_task_id == task.task_id,
                    Task.is_delete == False
                ).first()

                upload_output_to_all_reviews(review_task.task_id, task_data.output, db, Current_user)
                
        # Handle review status changes for review tasks
        if task_data.is_reviewed is not None and task.task_type == TaskType.Review:
            if task_data.is_reviewed:
                # Find all checklists linked to this review task
                checklists = (
                    db.query(Checklist)
                    .join(TaskChecklistLink, TaskChecklistLink.checklist_id == Checklist.checklist_id)
                    .filter(
                        TaskChecklistLink.parent_task_id == task.task_id,
                        Checklist.is_delete == False,
                        TaskChecklistLink.checklist_id != None,
                    )
                    .all()
                )

                if checklists:
                    all_completed = all(item.is_completed for item in checklists)
                    if not all_completed:
                        raise HTTPException(status_code=403, detail="All checklist items must be completed before marking the review task as reviewed.")
    
            # Passed validation or is_reviewed is False
            task.is_reviewed = task_data.is_reviewed
            update_fields['is_reviewed'] = task_data.is_reviewed

            old_status = task.status
            new_status = TaskStatus.Completed if task_data.is_reviewed else TaskStatus.To_Do

            if old_status != new_status:
                task.status = new_status
                log_task_field_change(db, task.task_id, "status", old_status, new_status, Current_user.employee_id)
                update_fields['status'] = new_status.name
        
        # Handle task completion for review tasks
        if (task_data.mark_complete is not None and task_data.mark_complete and task.task_type == TaskType.Review):
            # ✅ Step 1: Get parent task
            parent_task = db.query(Task).filter(
                Task.task_id == task.parent_task_id,
                Task.is_delete == False
            ).first()

            if parent_task and parent_task.task_type == TaskType.Normal:

                # ✅ Step 2: Get all checklists linked to this parent task
                checklist_ids = db.query(TaskChecklistLink.checklist_id).filter(
                    TaskChecklistLink.parent_task_id == parent_task.task_id
                ).subquery()

                # ✅ Step 3: Get checklist objects and validate completion
                incomplete_checklists = db.query(Checklist).filter(
                    Checklist.checklist_id.in_(checklist_ids),
                    Checklist.is_delete == False,
                    Checklist.is_completed == False
                ).count()

                if incomplete_checklists > 0:
                    raise HTTPException(
                        status_code=400,
                        detail="All linked checklists must be completed before marking this task complete."
                    )

                # ✅ Step 4: Mark parent task as completed
                old_status = parent_task.status
                parent_task.status = TaskStatus.Completed

                log_task_field_change(
                    db,
                    parent_task.task_id,
                    "status",
                    old_status,
                    TaskStatus.Completed,
                    Current_user.employee_id
                )

                update_fields['parent_task_completed'] = True

                # Optionally handle post-complete logic
                Mark_complete_help(task.task_id, db, Current_user)
        
        db.commit()
        return {"message": "Task updated successfully", "updated_fields": update_fields}
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error occurred while updating task: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")
    

@router.post("/Send_For_Review/")
def send_for_review(data: SendForReview, db: Session = Depends(get_db),Current_user: int = Depends(get_current_user)):
    try:
        task = db.query(Task).filter(Task.task_id == data.task_id,Task.task_type == TaskType.Review,
                                     or_(Task.created_by == Current_user.employee_id, Task.assigned_to == Current_user.employee_id),
                                    Task.is_delete == False).first()
        if not task:
            logger.info("Task not found or creator is not you")
        
        if task:
            review_task = Task(
                    task_name=task.task_name,
                    description="Review task",
                    status=TaskStatus.To_Do.name,
                    assigned_to=data.assigned_to,  
                    created_by=Current_user.employee_id,  
                    due_date=task.due_date,
                    task_type = TaskType.Review,
                    parent_task_id = task.task_id,
                    output = task.output)
        db.add(review_task)
        db.commit()
        return {"message": "Review Task Created successfully"}
    except Exception as e:
        db.rollback()
        logger.error(f"Error occurred while Sending for review: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")