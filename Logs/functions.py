from enum import Enum
from datetime import datetime
from models.models import TaskUpdateLog,ChecklistUpdateLog

def log_task_field_change(db, task_id: int, field_name: str, old_value, new_value, user_id):
    """
    Generic logger for any field change in a task.

    Args:
        db: Database session
        task_id: ID of the task being updated
        field_name: The name of the field being changed (e.g., 'status', 'output')
        old_value: The old value of the field
        new_value: The new value of the field
        user_id: The user who made the change
    """
      # Skip logging if no change

    try:
        # Convert enums or other objects to string
        old_str = old_value.name if isinstance(old_value, Enum) else str(old_value)
        new_str = new_value.name if isinstance(new_value, Enum) else str(new_value)

        if old_str == new_str:
            return

        log = TaskUpdateLog(
            task_id=task_id,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            updated_by=user_id,
            updated_at=datetime.utcnow()
        )
        db.add(log)
        db.flush()  # Let the main transaction handle commit

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to log change for {field_name} on task {task_id}: {str(e)}")


def log_checklist_field_change(db, checklist_id: int, field_name: str, old_value, new_value, user_id=None):
    """
    Generic logger for any field change in a checklist.

    Args:
        db: Database session
        checklist_id: ID of the checklist being updated
        field_name: The name of the field being changed (e.g., 'is_completed', 'checklist_name')
        old_value: The old value of the field
        new_value: The new value of the field
        user_id: The user who made the change
    """
    if old_value == new_value:
        return  # Skip logging if nothing changed

    try:
        old_str = old_value.name if isinstance(old_value, Enum) else str(old_value)
        new_str = new_value.name if isinstance(new_value, Enum) else str(new_value)

        log = ChecklistUpdateLog(
            checklist_id=checklist_id,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            updated_by=user_id,
            updated_at=datetime.utcnow()
        )
        db.add(log)
        db.flush()

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to log checklist field '{field_name}' change for checklist {checklist_id}: {str(e)}")