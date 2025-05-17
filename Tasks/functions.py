from models.models import TaskChecklistLink,Task,Checklist,TaskStatus, TaskType ,TaskUpdateLog, TaskTimeLog
from Logs.functions import log_task_field_change,log_checklist_field_change
from logger.logger import get_logger
from Checklist.functions import update_parent_task_status,propagate_incomplete_upwards
from datetime import datetime
from sqlalchemy import desc

def propagate_completion_upwards(task, db, updated_by, logger, Current_user):
    logger.info(f"Starting propagate_completion_upwards for task_id={task.task_id}")
    visited_tasks = set()
    updated_tasks = []  # ✅ To collect updated task info

    def complete_task_and_children(t):
        last_task = None
        while t and t.task_type == TaskType.Review:
            logger.debug(f"Review task: {t.task_id}")
            child = db.query(Task).filter(
                Task.task_id == t.parent_task_id,
                Task.is_delete == False
            ).first()

            if not child:
                logger.warning(f"No parent task found for review task {t.task_id}")
                break

            child.previous_status = child.status
            child.status = TaskStatus.Completed
            time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == task.task_id,TaskTimeLog.end_time == None).first()
            if time is not None:
                time.end_time = datetime.now()
                db.flush()
            db.flush()
            log_task_field_change(db, child.task_id, "status", child.previous_status, child.status, 1)
            logger.info(f"Child task {child.task_id} of review task {t.task_id} marked as Completed")

            updated_tasks.append({  # ✅ Add to list
                "task_id": child.task_id,
                "status": child.status
            })

            last_task = child
            t = child  # Move upward

        return last_task

    def check_checklist_completion(task_id):
        logger.debug(f"Checking checklist completion for task_id={task_id}")
        link = db.query(TaskChecklistLink).filter(TaskChecklistLink.sub_task_id == task_id).first()

        if link:
            checklist = db.query(Checklist).filter(
                Checklist.checklist_id == link.checklist_id,
                Checklist.is_delete == False
            ).first()

            if checklist:
                sub_tasks = db.query(Task).join(
                    TaskChecklistLink,
                    Task.task_id == TaskChecklistLink.sub_task_id
                ).filter(
                    TaskChecklistLink.checklist_id == checklist.checklist_id,
                    Task.is_delete == False
                ).all()

                if all(sub_task.status == TaskStatus.Completed for sub_task in sub_tasks):
                    if not checklist.is_completed:
                        checklist.is_completed = True
                        log_checklist_field_change(db, checklist.checklist_id, "is_completed", False, True, 1)
                        logger.info(f"Checklist {checklist.checklist_id} marked as completed")

                        parent_link = db.query(TaskChecklistLink).filter(
                            TaskChecklistLink.checklist_id == checklist.checklist_id,
                            TaskChecklistLink.parent_task_id.isnot(None)
                        ).first()

                        if parent_link:
                            update_parent_task_status(parent_link.parent_task_id, db, Current_user)

    final_task = complete_task_and_children(task) if task.task_type == TaskType.Review else task

    if final_task:
        check_checklist_completion(final_task.task_id)
        updated_tasks.append({ "task_id": final_task.task_id, "status": final_task.status })  # ✅ Add final
        logger.info(f"propagate_completion_upwards completed for task_id={final_task.task_id}")
        return { "message": "Task completion propagated successfully", "updated_tasks": updated_tasks }

    return { "message": "No parent task found to propagate completion", "updated_tasks": [] }


def reverse_completion_from_review(task, db, updated_by, logger, Current_user):
    logger.info(f"Starting reverse_completion_from_review for task_id={task.task_id}")
    reverted_tasks = []

    def revert_review_chain_until_normal(task):
        while task and task.task_type == TaskType.Review:
            if task.status == TaskStatus.Completed or task.status == TaskStatus.In_Review:
                time = db.query(TaskTimeLog).filter(TaskTimeLog.task_id == task.task_id).order_by(desc(TaskTimeLog.start_time)).first()
                time.end_time = None
                db.flush()
            task.is_reviewed = False
            task.status = task.previous_status
            db.flush()

            log_task_field_change(db, task.task_id, "is_reviewed", True, False, 1)
            log_task_field_change(db, task.task_id, "status", task.previous_status, task.status, 1)
            logger.info(f"Review task {task.task_id} reverted to {task.status}")

            reverted_tasks.append({ "task_id": task.task_id, "status": task.status })  # ✅ collect

            task = db.query(Task).filter(
                Task.task_id == task.parent_task_id,
                Task.is_delete == False
            ).first()

        return task

    def recurse_up_from_normal_task(task_id):
        task = db.query(Task).filter(Task.task_id == task_id, Task.is_delete == False).first()

        if task and task.status == TaskStatus.Completed:
            logger.info(f"Reverting normal task {task.task_id} from Completed to {task.previous_status}")
            task.status = task.previous_status
            reverted_tasks.append({ "task_id": task.task_id, "status": task.status })
            

            Link = db.query(TaskChecklistLink).filter(TaskChecklistLink.sub_task_id == task.task_id).first()
            if Link:
                checklist = db.query(Checklist).filter(Checklist.checklist_id == Link.checklist_id, Checklist.is_delete == False).first()
                if checklist and checklist.is_completed:
                    checklist.is_completed = False
                    log_checklist_field_change(db, checklist.checklist_id, "is_completed", True, False, 1)
                    logger.info(f"Checklist {checklist.checklist_id} reverted to incomplete")
                    propagate_incomplete_upwards(checklist.checklist_id, db, Current_user)

    if task:
        final_normal_task = revert_review_chain_until_normal(task)
        if final_normal_task:
            recurse_up_from_normal_task(final_normal_task.task_id)
            logger.info(f"reverse_completion_from_review completed for task_id={final_normal_task.task_id}")
            return { "message": "Review reversal successful", "updated_tasks": reverted_tasks }

    return { "message": "No parent task found to revert review", "updated_tasks": [] }

def deduplicate_tasks(tasks):
    seen = set()
    unique = []
    for task in tasks:
        task_id = task.get("task_id")
        if task_id not in seen:
            seen.add(task_id)
            unique.append(task)
    return unique


