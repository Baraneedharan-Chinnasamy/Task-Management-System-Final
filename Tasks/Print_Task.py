from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import or_, update, asc, desc, not_,func,case
from database.database import get_db
from datetime import date, datetime
from typing import Optional
from collections import defaultdict
from Currentuser.currentUser import get_current_user
from models.models import Task, User, ChatRoom, ChatMessage, ChatMessageRead, Checklist, TaskChecklistLink,TaskType
from logger.logger import get_logger

router = APIRouter()


@router.get("/tasks")
def get_tasks_by_employees(
    page: int = Query(1, ge=1),
    task_name: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    due_date: Optional[date] = Query(None),
    task_type: Optional[str] = Query(None),
    is_reviewed: Optional[bool] = Query(None),
    is_review_required: Optional[bool] = Query(None),
    sort_by: Optional[str] = Query("due_date"),
    sort_order: Optional[str] = Query("desc"),
    filter_by: Optional[str] = Query(None, regex="^(created_by|assigned_to)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger = get_logger("print_task", "print_task.log")
    logger.info("GET /tasks - Called by user_id=%s", current_user.employee_id)

    limit = 50
    offset = (page - 1) * limit

    logger.info("Pagination: Page=%d, Limit=%d", page, limit)
    logger.info("Filters - task_name=%s, description=%s, status=%s, due_date=%s, task_type=%s, is_reviewed=%s, is_review_required=%s",
                task_name, description, status, due_date, task_type, is_reviewed, is_review_required)

    valid_sort_fields = {
        "created_at": Task.created_at,
        "updated_at": Task.updated_at,
        "due_date": Task.due_date,
        "task_name": Task.task_name,
        "status": Task.status
    }

    sort_column = valid_sort_fields.get(sort_by, Task.created_at)
    order = desc(sort_column) if sort_order.lower() == "desc" else asc(sort_column)
    logger.info("Sorting by: %s %s", sort_by, sort_order.upper())

    query = db.query(Task).options(
        joinedload(Task.chat_room),
    ).filter(
        or_(
            Task.created_by == current_user.employee_id,
            Task.assigned_to == current_user.employee_id
        ),
        Task.is_delete == False
    )

    # Apply filter for created_by or assigned_to
    if filter_by == "created_by":
        query = query.filter(Task.created_by == current_user.employee_id)
        logger.info("Filter applied: created_by")
    elif filter_by == "assigned_to":
        query = query.filter(Task.assigned_to == current_user.employee_id)
        logger.info("Filter applied: assigned_to")

    # New: Task name search (case-insensitive, prioritized startswith)
    if task_name:
        prefix_match = f"{task_name.lower()}%"
        contains_match = f"%{task_name.lower()}%"
        query = query.filter(func.lower(Task.task_name).like(contains_match))
        query = query.order_by(
            case(
                [(func.lower(Task.task_name).like(prefix_match), 0)],
                else_=1
            ),
            order
        )
        logger.info("Filtered by task_name: %s", task_name)

    # New: Description search (case-insensitive, contains)
    if description:
        query = query.filter(func.lower(Task.description).like(f"%{description.lower()}%"))
        logger.info("Filtered by description: %s", description)

    # Standard filters
    if status:
        query = query.filter(Task.status == status)
    if due_date:
        query = query.filter(Task.due_date == due_date)
    if task_type:
        query = query.filter(Task.task_type == task_type)
    if is_reviewed is not None:
        query = query.filter(Task.is_reviewed == is_reviewed)
    if is_review_required is not None:
        query = query.filter(Task.is_review_required == is_review_required)

    total_count = query.count()
    tasks = query.offset(offset).limit(limit).all()
    logger.info("Total filtered tasks: %d, Returned: %d", total_count, len(tasks))

   
    user_map = {}
    users = db.query(User).filter().all()
    user_map = {u.employee_id: u.username for u in users}

    # Checklist processing
    checklist_counts = defaultdict(lambda: {"total": 0, "completed": 0})
    checklist_links = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.parent_task_id.in_([t.task_id for t in tasks])
    ).all()

    checklist_ids = [link.checklist_id for link in checklist_links if link.checklist_id]
    checklist_map = {}
    if checklist_ids:
        checklists = db.query(Checklist).filter(Checklist.checklist_id.in_(checklist_ids)).all()
        checklist_map = {c.checklist_id: c for c in checklists}

        for link in checklist_links:
            if link.parent_task_id and link.checklist_id:
                checklist = checklist_map.get(link.checklist_id)
                if checklist:
                    checklist_counts[link.parent_task_id]["total"] += 1
                    if checklist.is_completed:
                        checklist_counts[link.parent_task_id]["completed"] += 1

    # Summary info
    created_by_me_tasks = db.query(Task).filter(
        Task.created_by == current_user.employee_id,
        Task.is_delete == False
    ).all()
    assigned_to_me_tasks = db.query(Task).filter(
        Task.assigned_to == current_user.employee_id,
        Task.is_delete == False
    ).all()

    created_by_me_summary = defaultdict(int)
    for t in created_by_me_tasks:
        created_by_me_summary[t.status] += 1

    assigned_to_me_summary = defaultdict(int)
    for t in assigned_to_me_tasks:
        assigned_to_me_summary[t.status] += 1

    # Build response
    result = []
    for task in tasks:
        completed = checklist_counts[task.task_id]["completed"]
        total = checklist_counts[task.task_id]["total"]
        checklist_progress = f"{completed}/{total}" if total > 0 else "0/0"
        delete_allow = filter_by == "created_by"

        result.append({
            "task_id": task.task_id,
            "task_name": task.task_name,
            "due_date": task.due_date if task.due_date else None,
            "assigned_to_name": user_map.get(task.assigned_to),
            "created_by_name": user_map.get(task.created_by),
            "status": task.status,
            "task_type": task.task_type,
            "checklist_progress": checklist_progress,
            "delete_allow": delete_allow
        })

    return {
        "page": page,
        "limit": limit,
        "total": total_count,
        "tasks": result,
        "summary": {
            "created_by_me": {
                "total": len(created_by_me_tasks),
                "status_counts": dict(created_by_me_summary)
            },
            "assigned_to_me": {
                "total": len(assigned_to_me_tasks),
                "status_counts": dict(assigned_to_me_summary)
            }
        }
    }


@router.get("/task/task_id")
def task_details(
    task_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger = get_logger("print_task", "print_task.log")
    logger.info("GET /task/task_id called - task_id=%s by user_id=%s", task_id, current_user.employee_id)

    try:
        task = db.query(Task).filter(Task.task_id == task_id,Task.is_delete == False).first()
        if not task:
            logger.warning("Task not found for task_id=%s", task_id)
            return {"error": "Task not found"}

        delete_allow = task.created_by == current_user.employee_id

        
        users = db.query(User).filter().all()
        user_map = {u.employee_id: u.username for u in users}

        # ---------------- Checklist processing for given task ----------------
        checklist_data = []

        checklist_links = db.query(TaskChecklistLink).filter(
            TaskChecklistLink.parent_task_id == task_id
        ).all()

        for link in checklist_links:
            checklist = db.query(Checklist).filter(
                Checklist.checklist_id == link.checklist_id,
                Checklist.is_delete == False
            ).first()

            if not checklist:
                continue

            subtasks = []

            subtask_links = db.query(TaskChecklistLink).filter(
                TaskChecklistLink.checklist_id == checklist.checklist_id,
                TaskChecklistLink.sub_task_id.isnot(None)
            ).all()

            for subtask_link in subtask_links:
                subtask = db.query(Task).filter(
                    Task.task_id == subtask_link.sub_task_id,
                    Task.is_delete == False
                ).first()

                if subtask:
                    # Fetch checklists for the subtask
                    subtask_checklist_links = db.query(TaskChecklistLink).filter(
                        TaskChecklistLink.parent_task_id == subtask.task_id
                    ).all()

                    subtask_checklist_data = []
                    for st_link in subtask_checklist_links:
                        st_checklist = db.query(Checklist).filter(
                            Checklist.checklist_id == st_link.checklist_id,
                            Checklist.is_delete == False
                        ).first()
                        if st_checklist:
                            subtask_checklist_data.append(st_checklist)

                    st_completed = sum(1 for c in subtask_checklist_data if c.is_completed)
                    st_total = len(subtask_checklist_data)
                    st_checklist_progress = f"{st_completed}/{st_total}" if st_total > 0 else "0/0"
                    subtasks.append({
                        "task_id": subtask.task_id,
                        "task_name": subtask.task_name,
                        "description": subtask.description,
                        "status": subtask.status,
                        "assigned_to": subtask.assigned_to,
                        "assigned_to_name": user_map.get(subtask.assigned_to),
                        "due_date": subtask.due_date,
                        "created_by": subtask.created_by,
                        "created_by_name": user_map.get(subtask.created_by),
                        "created_at": subtask.created_at,
                        "updated_at": subtask.updated_at,
                        "task_type": subtask.task_type,
                        "is_review_required": subtask.is_review_required,
                        "output": subtask.output,
                        "checklist_progress": st_checklist_progress
                    })

            delete_allow_checklist = False if subtasks else True

            checklist_data.append({
                "checklist_id": checklist.checklist_id,
                "checklist_name": checklist.checklist_name,
                "is_completed": checklist.is_completed,
                "subtasks": subtasks,
                "checkbox_status": delete_allow_checklist,
                "created_by_name":user_map.get(checklist.created_by),
                "created_by":checklist.created_by

            })

        completed = sum(1 for c in checklist_data if c["is_completed"])
        total = len(checklist_data)
        checklist_progress = f"{completed}/{total}" if total > 0 else "0/0"

        # ---------------- Parent Task Chain with Checklists ----------------
        parent_task_chain = []

        def get_parent_chain(current_task_id):
            if not current_task_id:
                return

            current_task = db.query(Task).filter(
                Task.task_id == current_task_id,
                Task.is_delete == False
            ).first()

            if current_task:
                # Get checklists for current task
                checklists = []
                checklist_links = db.query(TaskChecklistLink).filter(
                    TaskChecklistLink.parent_task_id == current_task.task_id
                ).all()

                total_count = 0
                completed_count = 0
                for link in checklist_links:
                    checklist = db.query(Checklist).filter(
                        Checklist.checklist_id == link.checklist_id,
                        Checklist.is_delete == False
                    ).first()

                    if checklist:
                        total_count += 1
                        if checklist.is_completed:
                            completed_count += 1
                    
                checklist_progress = f"{completed_count}/{total_count}" if total_count > 0 else "0/0"

                parent_task_chain.append({
                    "task_id": current_task.task_id,
                    "task_name": current_task.task_name,
                    "description":current_task.description,
                    "status": current_task.status,
                    "task_type": current_task.task_type,
                    "assigned_to": current_task.assigned_to,
                    "assigned_to_name": user_map.get(current_task.assigned_to),
                    "created_by": current_task.created_by,
                    "created_by_name": user_map.get(current_task.created_by),
                    "due_date": current_task.due_date if current_task.due_date else None,
                    "is_reviewed": current_task.is_reviewed,
                    "output": current_task.output,
                    "created_at": current_task.created_at,
                    "updated_at": current_task.updated_at,
                    "checklist_progress": checklist_progress
                    
                })

                if current_task.parent_task_id:
                    get_parent_chain(current_task.parent_task_id)

        # 🚀 Start from parent_task_id (not task_id) to exclude current task
        get_parent_chain(task.parent_task_id)
        parent_task_chain = parent_task_chain[::-1]  # reverse order to show top -> bottom
        if parent_task_chain:
            first_task = parent_task_chain[0]
            output = first_task.get("output")
            description = first_task.get("description")


      
        is_last_review = False
        if task.task_type == TaskType.Review:
            # Check if there are any other review tasks with this task as parent
            newer_review_tasks = db.query(Task).filter(
                Task.parent_task_id == task.task_id,
                Task.task_type == "Review",
                Task.is_delete == False
            ).all()
            
            is_last_review = len(newer_review_tasks) == 0
                    
        logger.info("Returning task details for task_id=%s", task_id)

        return {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "description": task.description if task.task_type == TaskType.Normal else description,
            "due_date": task.due_date if task.due_date else None,
            "assigned_to": task.assigned_to,
            "assigned_to_name": user_map.get(task.assigned_to),
            "created_by": task.created_by,
            "created_by_name": user_map.get(task.created_by),
            "status": task.status,
            "output": task.output if task.task_type == TaskType.Normal else output,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "task_type": task.task_type,
            "is_review_required": task.is_review_required,
            "is_reviewed": task.is_reviewed,
            "checklist_progress": checklist_progress,
            "checklists": checklist_data,
            "delete_allow": delete_allow,
            "parent_task_chain": parent_task_chain,
            "last_review":is_last_review 
        }

    except Exception as e:
        logger.exception("Error retrieving task details for task_id=%s: %s", task_id, str(e))
        return {"error": str(e)}
