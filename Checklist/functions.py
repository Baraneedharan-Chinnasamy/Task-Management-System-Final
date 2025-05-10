from passlib.context import CryptContext
from models.models import Task, Checklist, TaskChecklistLink, TaskStatus
from enum import Enum
from fastapi import Depends
from sqlalchemy import select, or_, update
from dotenv import load_dotenv
from Logs.functions import log_task_field_change,log_checklist_field_change
from logger.logger import get_logger


def update_parent_task_status(task_id, db,Current_user):
    print(f"Checking parent task status: {task_id}")
    if not task_id:
        return

    task_checklists = db.query(Checklist).join(
        TaskChecklistLink, Checklist.checklist_id == TaskChecklistLink.checklist_id
    ).filter(
        TaskChecklistLink.parent_task_id == task_id,
        Checklist.is_delete == False
    ).all()

    task = db.query(Task).filter(Task.task_id == task_id).first()

    if not task:
        return

    if all(cl.is_completed for cl in task_checklists):
        new_status = "In_Review" if task.is_review_required else "Completed"
        if task.status != new_status:
            old_status = task.status
            if task.previous_status != task.status:
                task.previous_status = task.status
            print(f"Marking task {task_id} as {new_status}")
            task.status = new_status
            log_task_field_change(db, task.task_id,"status", old_status, task.status,2)
            
            review_task = db.query(Task).filter(Task.parent_task_id == task.task_id).first()
            if review_task is not None:
                print("re",review_task.task_id)
                review_task.previous_status = review_task.status 
                review_task.status = TaskStatus.To_Do
                log_task_field_change(db, task.task_id,"status",review_task.status, TaskStatus.To_Do,2)
            db.flush()
            
            print(task.status)
            

        parent_checklists = db.query(TaskChecklistLink.checklist_id).filter(
            TaskChecklistLink.sub_task_id == task_id
        ).all()

        for parent_checklist in parent_checklists:
            update_checklist_for_subtask_completion(parent_checklist[0], db,Current_user)
    else:
        if task.status != "In_Progress":
            old_status = task.status
            
            task.previous_status = task.status
            print(f"Marking task {task_id} as In_Progress")
            
            task.status = "In_Progress"
            log_task_field_change(db, task.task_id,"status", old_status, task.status,2)
            db.flush()


def update_checklist_for_subtask_completion(checklist_id, db,Current_user):
    print(f"Checking if all subtasks of checklist {checklist_id} are completed")

    subtask_ids = db.query(TaskChecklistLink.sub_task_id).filter(
        TaskChecklistLink.checklist_id == checklist_id,
        TaskChecklistLink.sub_task_id.isnot(None)
    ).all()
    subtask_ids = [st_id[0] for st_id in subtask_ids if st_id[0] is not None]
   
    if not subtask_ids:
        return
    
    subtask_statuses = db.query(Task.status).filter(
    Task.task_id.in_(subtask_ids),
    Task.is_delete == False).all()

    # Print all statuses to debug
    for status in subtask_statuses:
        print(f"Raw status: {status[0]}, type: {type(status[0])}")

# Correct comparison using enum
    all_completed = all(status[0] == TaskStatus.Completed for status in subtask_statuses)
    print(f"All subtasks completed: {all_completed}")
    

    if subtask_statuses and all_completed:
        checklist = db.query(Checklist).filter(
            Checklist.checklist_id == checklist_id
        ).first()
        if checklist and not checklist.is_completed:
            print(f"Marking checklist {checklist_id} as completed")

            log_checklist_field_change(db,checklist_id,"is_completed",checklist.is_completed,True,Current_user.employee_id)

            checklist.is_completed = True
            db.flush()

            parent_tasks = db.query(TaskChecklistLink.parent_task_id).filter(
                TaskChecklistLink.checklist_id == checklist_id,
                TaskChecklistLink.parent_task_id.isnot(None)
            ).all()

            for parent in parent_tasks:
                update_parent_task_status(parent[0], db,Current_user)

def propagate_incomplete_upwards(checklist_id, db,Current_user, visited_checklists=set()):
    if checklist_id in visited_checklists:
        return
    visited_checklists.add(checklist_id)

    print(f"🔁 Propagating incompletion from checklist {checklist_id}")

    checklist = db.query(Checklist).filter(
        Checklist.checklist_id == checklist_id,
        Checklist.is_delete == False
    ).first()

    if checklist and checklist.is_completed:
        print(f"❌ Marking checklist {checklist_id} as incomplete")
        log_checklist_field_change(db,checklist_id,"is_completed",checklist.is_completed,False,Current_user.employee_id)
        checklist.is_completed = False
        db.flush()

    parent_tasks = db.query(TaskChecklistLink.parent_task_id).filter(
        TaskChecklistLink.checklist_id == checklist_id,
        TaskChecklistLink.parent_task_id.isnot(None)
    ).first()
    

    parent_task_id = parent_tasks[0]
    task = db.query(Task).filter(Task.task_id == parent_task_id).first()
    if task and task.status not in ("In_Progress", "To_Do"):
        # Get all checklist IDs linked to this task
        checklist_id_tuples = db.query(TaskChecklistLink.checklist_id).filter(
            TaskChecklistLink.parent_task_id == task.task_id
        ).all()
        
        checklist_ids = [cid for (cid,) in checklist_id_tuples]

        # Get all checklist objects
        checklists = db.query(Checklist).filter(Checklist.checklist_id.in_(checklist_ids)).all()

        # Count how many are completed
        completed_count = sum(1 for checklist in checklists if checklist.is_completed)

        old_status = task.status

        if completed_count == 0:
            new_status = "To_Do"
        else:
            new_status = "In_Progress"

        task.previous_status = task.status
        task.status = new_status
        log_task_field_change(db, task.task_id, "status", old_status, new_status, 2)
        db.flush()

        if task.is_review_required:
            review_task = db.query(Task).filter(Task.parent_task_id == task.task_id).first()
            if review_task is not None:
                cur = review_task.status
                old = review_task.previous_status
                review_task.status = old
                review_task.previous_status = cur
                log_task_field_change(db, task.task_id, "status", review_task.status, TaskStatus.To_Do, 2)
                db.flush()


    parent_checklists = db.query(TaskChecklistLink.checklist_id).filter(
        TaskChecklistLink.sub_task_id == parent_task_id
    ).all()

    for pcl in parent_checklists:
        propagate_incomplete_upwards(pcl[0], db,Current_user)   


