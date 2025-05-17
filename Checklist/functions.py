from passlib.context import CryptContext
from models.models import Task, Checklist, TaskChecklistLink, TaskStatus, TaskType, TaskTimeLog
from sqlalchemy import desc
from Logs.functions import log_task_field_change, log_checklist_field_change
from datetime import datetime
from logger.logger import get_logger

def update_task_status(task, new_status, db, current_user_id):
    """Helper to update task status while preserving previous status and logging."""
    if task.status != new_status:
        old_status = task.status
        if task.previous_status != task.status:
            task.previous_status = task.status
        task.status = new_status
        log_task_field_change(db, task.task_id, "status", old_status, new_status, current_user_id)
        db.flush()


def update_parent_task_status(task_id, db, Current_user):
   
    if not task_id:
        return

    task_checklists = db.query(Checklist).join(
        TaskChecklistLink, Checklist.checklist_id == TaskChecklistLink.checklist_id
    ).filter(
        TaskChecklistLink.parent_task_id == task_id,
        Checklist.is_delete == False
    ).all()

    task = db.query(Task).filter(Task.task_id == task_id, Task.is_delete == False).first()
    if not task:
        return

    if all(cl.is_completed for cl in task_checklists):
        new_status = TaskStatus.In_Review if task.is_review_required else TaskStatus.Completed
        update_task_status(task, new_status, db, 1)

        time = db.query(TaskTimeLog).filter(
            TaskTimeLog.task_id == task.task_id,
            TaskTimeLog.end_time == None
        ).first()
        if time is not None:
            time.end_time = datetime.now()
            db.flush()

        if task.is_review_required:
            review_task = db.query(Task).filter(Task.parent_task_id == task.task_id).first()
            if review_task:
                old_status = review_task.status
                if review_task.previous_status != old_status:
                    review_task.previous_status = old_status
                review_task.status = TaskStatus.To_Do
                log_task_field_change(db, task.task_id, "status", old_status, TaskStatus.To_Do, 1)
                db.flush()

    else:
        if task.status != TaskStatus.In_Progress:
            update_task_status(task, TaskStatus.In_Progress, db, 1)


    parent_checklists = db.query(TaskChecklistLink.checklist_id).filter(
        TaskChecklistLink.sub_task_id == task_id
    ).all()

    for parent_checklist in parent_checklists:
        update_checklist_for_subtask_completion(parent_checklist[0], db, Current_user)


def update_checklist_for_subtask_completion(checklist_id, db, Current_user):
    

    subtask_ids = db.query(TaskChecklistLink.sub_task_id).filter(
        TaskChecklistLink.checklist_id == checklist_id,
        TaskChecklistLink.sub_task_id.isnot(None)
    ).all()
    subtask_ids = [st_id[0] for st_id in subtask_ids if st_id[0] is not None]

    if not subtask_ids:
        return

    subtask_statuses = db.query(Task.status).filter(
        Task.task_id.in_(subtask_ids),
        Task.is_delete == False
    ).all()

    all_completed = all(status[0] == TaskStatus.Completed for status in subtask_statuses)
    

    if subtask_statuses and all_completed:
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == checklist_id
        ).first()
        if checklist and not checklist.is_completed:
            

            log_checklist_field_change(db, checklist_id, "is_completed", checklist.is_completed, True, Current_user.employee_id)
            checklist.is_completed = True
            db.flush()

            parent_tasks = db.query(TaskChecklistLink.parent_task_id).filter(
                TaskChecklistLink.checklist_id == checklist_id,
                TaskChecklistLink.parent_task_id.isnot(None)
            ).all()

            for parent in parent_tasks:
                update_parent_task_status(parent[0], db, Current_user)


def propagate_incomplete_upwards(checklist_id, db, Current_user, visited_checklists=None):
    if visited_checklists is None:
        visited_checklists = set()
    if checklist_id in visited_checklists:
        return
    visited_checklists.add(checklist_id)

    

    checklist = db.query(Checklist).filter(
        Checklist.checklist_id == checklist_id,
        Checklist.is_delete == False
    ).first()

    if checklist and checklist.is_completed:
        
        log_checklist_field_change(db, checklist_id, "is_completed", checklist.is_completed, False, Current_user.employee_id)
        checklist.is_completed = False
        db.flush()

    parent_task = db.query(TaskChecklistLink.parent_task_id).filter(
        TaskChecklistLink.checklist_id == checklist_id,
        TaskChecklistLink.parent_task_id.isnot(None)
    ).first()

    if parent_task:
        parent_task_id = parent_task[0]
        task = db.query(Task).filter(Task.task_id == parent_task_id).first()

        if task:
            checklist_ids = db.query(TaskChecklistLink.checklist_id).filter(
                TaskChecklistLink.parent_task_id == task.task_id
            ).all()
            checklist_ids = [cid for (cid,) in checklist_ids]

            checklists = db.query(Checklist).filter(
                Checklist.checklist_id.in_(checklist_ids),
                Checklist.is_delete == False
            ).all()

            completed_count = sum(1 for c in checklists if c.is_completed)
            total_count = len(checklists)

            old_status = task.status
            if old_status in [TaskStatus.Completed, TaskStatus.In_Review]:
                time = db.query(TaskTimeLog).filter(
                    TaskTimeLog.task_id == task.task_id
                ).order_by(desc(TaskTimeLog.start_time)).first()

                if time:
                    time.end_time = None
                    db.flush()

                new_status = TaskStatus.To_Do if completed_count == 0 else TaskStatus.In_Progress
                update_task_status(task, new_status, db, Current_user.employee_id)

            if task.is_review_required:
                review_task = db.query(Task).filter(Task.parent_task_id == task.task_id).first()
                if review_task and review_task.previous_status:
                    cur = review_task.status
                    old = review_task.previous_status
                    review_task.status = old
                    review_task.previous_status = cur
                    log_task_field_change(db, task.task_id, "status", cur, old, Current_user.employee_id)
                    db.flush()

                    if old in [TaskStatus.Completed, TaskStatus.In_Review]:
                        time = db.query(TaskTimeLog).filter(
                            TaskTimeLog.task_id == task.task_id
                        ).order_by(desc(TaskTimeLog.start_time)).first()
                        if time:
                            time.end_time = None
                            db.flush()

        parent_checklists = db.query(TaskChecklistLink.checklist_id).filter(
            TaskChecklistLink.sub_task_id == parent_task_id
        ).all()

        for pcl in parent_checklists:
            propagate_incomplete_upwards(pcl[0], db, Current_user, visited_checklists)




