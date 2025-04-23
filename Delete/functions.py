import logging
from sqlalchemy.sql import or_, update,select
from models.models import TaskChecklistLink


def get_related_tasks_checklists_logic(session, task_id, checklist_id):
    tasks_to_process = set()
    processed_tasks = set()
    processed_checklists = set()

    if task_id:
        tasks_to_process.add(task_id)
        logging.info(f"Starting with task_id: {task_id}")
    elif checklist_id:
        logging.info(f"Starting with checklist_id: {checklist_id}")

        # Start with checklist and find linked tasks
        results = session.execute(
            select(TaskChecklistLink.sub_task_id)
            .where(TaskChecklistLink.checklist_id == checklist_id)
        ).scalars().all()
        results = [task for task in results if task is not None]

        if results:
            tasks_to_process.update(results)

           
            processed_checklists.add(checklist_id)
            logging.info(f"Found tasks linked to Checklist ID: {checklist_id} -> Tasks: {results}")
        else:
            logging.info(f"No tasks found for Checklist ID: {checklist_id}")
            return {"tasks": [], "checklists": [checklist_id]}  # Return only the given checklist if no tasks found
    else:
        logging.error("No task_id or checklist_id provided")
        return {"tasks": [], "checklists": []}  # No valid input

    while tasks_to_process:
        new_tasks = set()
        new_checklists = set()

        for tid in tasks_to_process:
            if tid in processed_tasks:
                continue
            processed_tasks.add(tid)
            logging.info(f"Processing Task ID: {tid}")

            # Find all checklists linked to this parent task
            results = session.execute(
                select(TaskChecklistLink.checklist_id, TaskChecklistLink.sub_task_id)
                .where(TaskChecklistLink.parent_task_id == tid)
            ).all()
            logging.info(f"Found checklists/subtasks for Task ID: {tid} -> {results}")

            for checklist_id, sub_task_id in results:
                if checklist_id and checklist_id not in processed_checklists:
                    new_checklists.add(checklist_id)
                    processed_checklists.add(checklist_id)
                    logging.info(f"Found Checklist ID: {checklist_id} for Task ID: {tid}")

                if sub_task_id and sub_task_id not in processed_tasks:
                    new_tasks.add(sub_task_id)
                    logging.info(f"Found Sub-task ID: {sub_task_id} for Task ID: {tid} (Checklist ID: {checklist_id})")

        # Process new checklists and link subtasks to them
        for checklist_id in new_checklists:
            results = session.execute(
                select(TaskChecklistLink.sub_task_id)
                .where(TaskChecklistLink.checklist_id == checklist_id)
            ).scalars().all()

            for sub_task_id in results:
                if sub_task_id and sub_task_id not in processed_tasks:
                    new_tasks.add(sub_task_id)
                    logging.info(f"Found Sub-task ID: {sub_task_id} for Checklist ID: {checklist_id}")

        tasks_to_process = new_tasks

    logging.info(f"Final Processed Tasks: {processed_tasks}")
    logging.info(f"Final Processed Checklists: {processed_checklists}")

    return {
        "tasks": list(processed_tasks),
        "checklists": list(processed_checklists)
    }