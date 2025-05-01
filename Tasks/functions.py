from models.models import TaskChecklistLink,Task,Checklist,TaskStatus, TaskType ,TaskUpdateLog
from Logs.functions import log_task_field_change,log_checklist_field_change
from logger.logger import get_logger
from Checklist.functions import update_parent_task_status,propagate_incomplete_upwards

def propagate_completion_upwards(task, db, updated_by, logger, Current_user):
    visited_tasks = set()

    def complete_task_and_children(t):
        last_task = None
        while t and t.task_type == TaskType.Review:
            print(f"Review task: {t.task_id}")
            child = db.query(Task).filter(
                Task.task_id == t.parent_task_id,
                Task.is_delete == False
            ).first()

            if not child:
                break

            print(f"Marking child task {child.task_id} as Completed")
            child.previous_status = child.status
            child.status = TaskStatus.Completed
            db.flush()

            log_task_field_change(db, child.task_id, "status", child.previous_status, child.status, updated_by)
            logger.info(f"Child task {child.task_id} of review task {t.task_id} marked as Completed")

            last_task = child
            t = child  # Move upward

        return last_task

    def check_checklist_completion(task_id):
        """ Walk upward through checklist/task hierarchy """
        print("Checking checklist for task:", task_id)
        link = db.query(TaskChecklistLink).filter(TaskChecklistLink.sub_task_id == task_id).first()

        if link:
            checklist = db.query(Checklist).filter(
                Checklist.checklist_id == link.checklist_id,
                Checklist.is_delete == False
            ).first()

            if checklist:
                # Check if all subtasks under the checklist are completed
                sub_tasks = db.query(Task).join(
                        TaskChecklistLink,
                        Task.task_id == TaskChecklistLink.sub_task_id  # Explicit join condition
                    ).filter(
                        TaskChecklistLink.checklist_id == checklist.checklist_id,
                        Task.is_delete == False
                    ).all()

                if all(sub_task.status == TaskStatus.Completed for sub_task in sub_tasks):
                    if not checklist.is_completed:
                        checklist.is_completed = True
                        logger.info(f"Checklist {checklist.checklist_id} marked as completed")

                        parent_link = db.query(TaskChecklistLink).filter(
                            TaskChecklistLink.checklist_id == checklist.checklist_id,
                            TaskChecklistLink.parent_task_id.isnot(None)
                        ).first()

                        if parent_link:
                            update_parent_task_status(parent_link.parent_task_id, db, Current_user)

    # --- Entry point ---
    # Phase 1: complete chain of Review tasks up to a Normal task
    final_task = complete_task_and_children(task) if task.task_type == TaskType.Review else task
    if final_task:
        check_checklist_completion(final_task.task_id)


def reverse_completion_from_review(task, db, updated_by, logger,Current_user):
    def revert_review_chain_until_normal(task):
        while task and task.task_type == TaskType.Review:
            task.is_reviewed = False
            task.status = task.previous_status
            print(task.previous_status)
            db.flush()
            log_task_field_change(db, task.task_id, "is_reviewed", True, False, updated_by)
            log_task_field_change(db, task.task_id, "status", task.previous_status, task.status, updated_by)
            logger.info(f"Review task {task.task_id} reverted to {task.previous_status}")
            task = db.query(Task).filter(
                Task.task_id == task.parent_task_id,
                Task.is_delete == False
            ).first()
            
        return task  

    def recurse_up_from_normal_task(task_id):
    
        task = db.query(Task).filter(Task.task_id == task_id,Task.is_delete == False).first()

        if task.status == TaskStatus.Completed:
            task.status = task.previous_status
            Link = db.query(TaskChecklistLink).filter(TaskChecklistLink.sub_task_id == task.task_id).first()
            if Link:
                checklist = db.query(Checklist).filter(Checklist.checklist_id==Link.checklist_id,Checklist.is_delete == False).first()
                if checklist.is_completed == True:
                    checklist.is_completed = False
                    propagate_incomplete_upwards(checklist.checklist_id, db, Current_user)
    # === Start the process ===
    if task:
        final_normal_task = revert_review_chain_until_normal(task)
        if final_normal_task:
            recurse_up_from_normal_task(final_normal_task.task_id)
