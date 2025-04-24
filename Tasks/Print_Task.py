from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import or_, update, asc, desc, not_,func,case
from database.database import get_db
from datetime import date, datetime
from typing import Optional
from collections import defaultdict
from Currentuser.currentUser import get_current_user
from models.models import Task, User, ChatRoom, ChatMessage, ChatMessageRead, Checklist, TaskChecklistLink
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

    # Fetch related user data
    user_ids = {task.assigned_to for task in tasks if task.assigned_to} | \
               {task.created_by for task in tasks if task.created_by}
    user_map = {}
    if user_ids:
        users = db.query(User).filter(User.employee_id.in_(user_ids)).all()
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
        task = db.query(Task).filter(Task.task_id == task_id).first()
        if not task:
            logger.warning("Task not found for task_id=%s", task_id)
            return {"error": "Task not found"}

        delete_allow = task.created_by == current_user.employee_id

        user_ids = {task.assigned_to, task.created_by}
        users = db.query(User).filter(User.employee_id.in_(user_ids)).all()
        user_map = {u.employee_id: u.username for u in users}

        checklist_progress = 0  # Can be updated if checklist is fetched

        chat_room = db.query(ChatRoom).filter(ChatRoom.task_id == task_id).first()
        unread_message_count = 0
        visible_messages = []

        if chat_room:
            logger.info("Chat room found for task_id=%s", task_id)
            read_subq = db.query(ChatMessageRead.message_id).filter(
                ChatMessageRead.user_id == current_user.employee_id
            ).subquery()

            unread_message_count = db.query(ChatMessage).filter(
                ChatMessage.chat_room_id == chat_room.chat_room_id,
                ChatMessage.sender_id != current_user.employee_id,
                not_(ChatMessage.message_id.in_(read_subq))
            ).count()

            limit = int(request.query_params.get("limit", 50))
            before_ts_str = request.query_params.get("before_timestamp")
            before_ts = datetime.fromisoformat(before_ts_str) if before_ts_str else None

            messages_query = db.query(ChatMessage).filter(ChatMessage.chat_room_id == chat_room.chat_room_id)
            if before_ts:
                messages_query = messages_query.filter(ChatMessage.timestamp < before_ts)

            messages = messages_query.order_by(ChatMessage.timestamp.desc()).limit(limit).all()
            messages.reverse()

            read_ids_set = {
                r.message_id for r in db.query(ChatMessageRead.message_id)
                .filter_by(user_id=current_user.employee_id)
                .all()
            }

            for msg in messages:
                if not msg.visible_to or current_user.employee_id in msg.visible_to:
                    visible_messages.append({
                        "message_id": msg.message_id,
                        "sender_id": msg.sender_id,
                        "message": msg.message,
                        "timestamp": str(msg.timestamp),
                        "seen": msg.message_id in read_ids_set
                    })

                    if msg.message_id not in read_ids_set and msg.sender_id != current_user.employee_id:
                        db.add(ChatMessageRead(message_id=msg.message_id, user_id=current_user.employee_id))

            db.commit()

        logger.info("Returning task details for task_id=%s", task_id)
        return {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "description": task.description,
            "due_date": task.due_date if task.due_date else None,
            "assigned_to": task.assigned_to,
            "assigned_to_name": user_map.get(task.assigned_to),
            "created_by": task.created_by,
            "created_by_name": user_map.get(task.created_by),
            "status": task.status,
            "output": task.output,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "task_type": task.task_type,
            "is_review_required": task.is_review_required,
            "is_reviewed": task.is_reviewed,
            "checklist_progress": checklist_progress,
            "delete_allow": delete_allow,
            "chat_messages": visible_messages,
            "unread_message_count": unread_message_count
        }

    except Exception as e:
        logger.exception("Error retrieving task details for task_id=%s: %s", task_id, str(e))
        return {"error": str(e)}
