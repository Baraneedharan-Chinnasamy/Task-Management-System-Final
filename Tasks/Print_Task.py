from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import or_, desc, asc, func, case
from database.database import get_db
from datetime import date
from typing import Optional
from collections import defaultdict
from Currentuser.currentUser import get_current_user
from models.models import Task, User, ChatRoom, Checklist, TaskChecklistLink, TaskType, TaskTimeLog
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
    is_ongoing: Optional[bool] = Query(None),  # ✅ NEW PARAMETER
    sort_by: Optional[str] = Query("due_date"),
    sort_order: Optional[str] = Query("desc"),
    filter_by: Optional[str] = Query(None, regex="^(created_by|assigned_to)?$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    logger = get_logger("print_task", "print_task.log")
    logger.info("GET /tasks - Called by user_id=%s", current_user.employee_id)

    limit = 50
    offset = (page - 1) * limit

    valid_sort_fields = {
        "created_at": Task.created_at,
        "updated_at": Task.updated_at,
        "due_date": Task.due_date,
        "task_name": Task.task_name,
        "status": Task.status
    }

    sort_column = valid_sort_fields.get(sort_by, Task.created_at)
    order = desc(sort_column) if sort_order.lower() == "desc" else asc(sort_column)

    # Step 1: Get ongoing task IDs based on latest time log where end_time is NULL
    latest_logs = db.query(
        TaskTimeLog.task_id,
        func.max(TaskTimeLog.start_time).label("max_start")
    ).filter(
        TaskTimeLog.user_id == current_user.employee_id
    ).group_by(
        TaskTimeLog.task_id
    ).subquery()

    latest_active_logs = db.query(TaskTimeLog.task_id).join(
        latest_logs,
        (TaskTimeLog.task_id == latest_logs.c.task_id) &
        (TaskTimeLog.start_time == latest_logs.c.max_start)
    ).filter(
        TaskTimeLog.end_time == None
    ).all()

    ongoing_task_ids = {row.task_id for row in latest_active_logs}

    # Step 2: Base task query
    query = db.query(Task).options(joinedload(Task.chat_room)).filter(
        or_(
            Task.created_by == current_user.employee_id,
            Task.assigned_to == current_user.employee_id
        ),
        Task.is_delete == False
    )

    # Step 3: Apply filter_by
    if filter_by == "created_by":
        query = query.filter(Task.created_by == current_user.employee_id)
    elif filter_by == "assigned_to":
        query = query.filter(Task.assigned_to == current_user.employee_id)

    # Step 4: Apply status filter
    if status:
        query = query.filter(Task.status == status.title())

    # Step 4.1: Apply is_ongoing filter independently
    if is_ongoing is True:
        if ongoing_task_ids:
            query = query.filter(Task.task_id.in_(ongoing_task_ids))
        else:
            return {
                "page": page,
                "limit": limit,
                "has_more": False,
                "total": 0,
                "tasks": [],
                "summary": {
                    "created_by_me": {"total": 0, "status_counts": {}},
                    "assigned_to_me": {"total": 0, "status_counts": {}}
                }
            }
    elif is_ongoing is False:
        if ongoing_task_ids:
            query = query.filter(~Task.task_id.in_(ongoing_task_ids))

    # Step 5: Task name search
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

    # Step 6: Other filters
    if description:
        query = query.filter(func.lower(Task.description).like(f"%{description.lower()}%"))
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
    has_more = (page * limit) < total_count

    # Step 7: Get users
    users = db.query(User).all()
    user_map = {u.employee_id: u.username for u in users}

    # Step 8: Checklist progress
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
            checklist = checklist_map.get(link.checklist_id)
            if checklist:
                checklist_counts[link.parent_task_id]["total"] += 1
                if checklist.is_completed:
                    checklist_counts[link.parent_task_id]["completed"] += 1

    # Step 9: Summary
    created_by_me_tasks = db.query(Task).filter(
        Task.created_by == current_user.employee_id,
        Task.is_delete == False
    ).all()
    assigned_to_me_tasks = db.query(Task).filter(
        Task.assigned_to == current_user.employee_id,
        Task.is_delete == False
    ).all()

    created_by_me_summary = defaultdict(int)
    assigned_to_me_summary = defaultdict(int)

    for t in created_by_me_tasks:
        created_by_me_summary[t.status] += 1

    for t in assigned_to_me_tasks:
        assigned_to_me_summary[t.status] += 1


    # Step 10: Get latest time log per task
    latest_time_logs_subquery = db.query(
        TaskTimeLog.task_id,
        func.max(TaskTimeLog.start_time).label("max_start")
    ).filter(
        TaskTimeLog.user_id == current_user.employee_id,
        TaskTimeLog.task_id.in_([t.task_id for t in tasks])
    ).group_by(TaskTimeLog.task_id).subquery()

    latest_time_logs = db.query(TaskTimeLog).join(
        latest_time_logs_subquery,
        (TaskTimeLog.task_id == latest_time_logs_subquery.c.task_id) &
        (TaskTimeLog.start_time == latest_time_logs_subquery.c.max_start)
    ).all()

    time_log_map = {log.task_id: {"start_time": log.start_time, "end_time": log.end_time} for log in latest_time_logs}

    # Step 11: Construct result
    result = []
    for task in tasks:
        completed = checklist_counts[task.task_id]["completed"]
        total = checklist_counts[task.task_id]["total"]
        checklist_progress = f"{completed}/{total}" if total > 0 else "0/0"
        is_ongoing_task = task.task_id in ongoing_task_ids
        delete_allow = task.created_by == current_user.employee_id
        latest_time = time_log_map.get(task.task_id, {"start_time": None, "end_time": None})

        result.append({
            "task_id": task.task_id,
            "task_name": task.task_name,
            "due_date": task.due_date,
            "assigned_to_name": user_map.get(task.assigned_to),
            "created_by_name": user_map.get(task.created_by),
            "status": task.status,
            "is_ongoing": is_ongoing_task,
            "task_type": task.task_type,
            "checklist_progress": checklist_progress,
            "delete_allow": delete_allow,
            "start_time": latest_time["start_time"],
            "end_time": latest_time["end_time"]
        })

    return {
        "page": page,
        "limit": limit,
        "has_more": has_more,
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
        task = db.query(Task).filter(Task.task_id == task_id, Task.is_delete == False).first()
        if not task:
            logger.warning("Task not found for task_id=%s", task_id)
            return {"error": "Task not found"}

        delete_allow = task.created_by == current_user.employee_id

        users = db.query(User).all()
        user_map = {u.employee_id: u.username for u in users}

        # 🔁 Helper function for time log info
        def get_latest_time_log_info(task_id: int) -> dict:
            latest_log_subq = db.query(
                func.max(TaskTimeLog.start_time)
            ).filter(
                TaskTimeLog.task_id == task_id,
                TaskTimeLog.user_id == current_user.employee_id
            ).scalar_subquery()

            log = db.query(TaskTimeLog).filter(
                TaskTimeLog.task_id == task_id,
                TaskTimeLog.user_id == current_user.employee_id,
                TaskTimeLog.start_time == latest_log_subq
            ).first()

            if log:
                return {
                    "is_ongoing": log.end_time is None,
                    "ongoing_start_time": log.start_time.isoformat(),
                    "ongoing_end_time": log.end_time.isoformat() if log.end_time else None
                }
            else:
                return {
                    "is_ongoing": None,
                    "ongoing_start_time": None,
                    "ongoing_end_time": None
                }

        main_task_time_info = get_latest_time_log_info(task.task_id)

        # ---------------- Checklist processing ----------------
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
                        "task_type": subtask.task_type,
                        "is_review_required": subtask.is_review_required,
                        "output": subtask.output,
                        "checklist_progress": st_checklist_progress,
                        **get_latest_time_log_info(subtask.task_id)
                    })

            delete_allow_checklist = False if subtasks else True

            checklist_data.append({
                "checklist_id": checklist.checklist_id,
                "checklist_name": checklist.checklist_name,
                "is_completed": checklist.is_completed,
                "subtasks": subtasks,
                "checkbox_status": delete_allow_checklist,
                "created_by_name": user_map.get(checklist.created_by),
                "created_by": checklist.created_by,
                "created_at": checklist.created_at
            })

        completed = sum(1 for c in checklist_data if c["is_completed"])
        total = len(checklist_data)
        checklist_progress = f"{completed}/{total}" if total > 0 else "0/0"

        # ---------------- Parent Task Chain ----------------
        parent_task_chain = []

        def get_parent_chain(current_task_id):
            if not current_task_id:
                return

            current_task = db.query(Task).filter(
                Task.task_id == current_task_id,
                Task.is_delete == False
            ).first()

            if current_task:
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
                    "description": current_task.description,
                    "status": current_task.status,
                    "task_type": current_task.task_type,
                    "assigned_to": current_task.assigned_to,
                    "assigned_to_name": user_map.get(current_task.assigned_to),
                    "created_by": current_task.created_by,
                    "created_by_name": user_map.get(current_task.created_by),
                    "due_date": current_task.due_date,
                    "is_reviewed": current_task.is_reviewed,
                    "output": current_task.output,
                    "created_at": current_task.created_at,
                    "checklist_progress": checklist_progress,
                    **get_latest_time_log_info(current_task.task_id)
                })

                if current_task.parent_task_id:
                    get_parent_chain(current_task.parent_task_id)

        get_parent_chain(task.parent_task_id)
        parent_task_chain = parent_task_chain[::-1]

        if parent_task_chain:
            first_task = parent_task_chain[0]
            output = first_task.get("output")
            description = first_task.get("description")
        else:
            output = None
            description = None

        # ---------------- Review Checklists ----------------
        review_checklists = []
        review_task = db.query(Task).filter(
            Task.task_id == task.parent_task_id,
            Task.is_delete == False
        ).first()

        if review_task:
            checklist_links = db.query(TaskChecklistLink).filter(
                TaskChecklistLink.parent_task_id == review_task.task_id
            ).all()
            checklist_ids = [link.checklist_id for link in checklist_links if link.checklist_id]
            checklists = db.query(Checklist).filter(
                Checklist.checklist_id.in_(checklist_ids),
                Checklist.created_by == task.assigned_to,
                Checklist.is_delete == False
            ).all()
            for checklist in checklists:
                group = "Initial Checklist" if checklist.created_at == review_task.created_at else "Review Checklist"
                review_checklists.append({
                    "checklist_id": checklist.checklist_id,
                    "checklist_name": checklist.checklist_name,
                    "is_completed": checklist.is_completed,
                    "created_by": checklist.created_by,
                    "created_by_name": user_map.get(checklist.created_by),
                    "created_at": checklist.created_at,
                    "group": group
                })

        # ---------------- Last Review ----------------
        is_last_review = False
        if task.task_type == TaskType.Review:
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
            "due_date": task.due_date,
            "assigned_to": task.assigned_to,
            "assigned_to_name": user_map.get(task.assigned_to),
            "created_by": task.created_by,
            "created_by_name": user_map.get(task.created_by),
            "status": task.status,
            "output": task.output if task.task_type == TaskType.Normal else output,
            "created_at": task.created_at,
            "task_type": task.task_type,
            "is_review_required": task.is_review_required,
            "is_reviewed": task.is_reviewed,
            "checklist_progress": checklist_progress,
            "checklists": checklist_data,
            "delete_allow": delete_allow,
            "parent_task_chain": parent_task_chain,
            "last_review": is_last_review,
            "review_checklist": review_checklists if review_checklists else None,
            **main_task_time_info
        }

    except Exception as e:
        logger.exception("Error retrieving task details for task_id=%s: %s", task_id, str(e))
        return {"error": str(e)}