from sqlalchemy import select
from models.models import Task, TaskChecklistLink, TaskType

def get_related_tasks_checklists_logic(session, task_id, checklist_id):
    tasks_to_process = set()
    processed_tasks = set()
    processed_checklists = set()

    if task_id:
        tasks_to_process.add(task_id)
    elif checklist_id:
        results = session.execute(
            select(TaskChecklistLink.sub_task_id)
            .where(TaskChecklistLink.checklist_id == checklist_id)
        ).scalars().all()
        results = [task for task in results if task is not None]
        if results:
            tasks_to_process.update(results)
            processed_checklists.add(checklist_id)
        else:
            return {"tasks": [], "checklists": [checklist_id]}

    while tasks_to_process:
        new_tasks = set()
        new_checklists = set()

        for tid in tasks_to_process:
            if tid in processed_tasks:
                continue
            processed_tasks.add(tid)

            # 👇 RECURSIVELY process all review tasks linked to this task
            review_stack = [tid]
            while review_stack:
                current = review_stack.pop()
                review_tasks = session.execute(
                    select(Task.task_id)
                    .where(
                        Task.parent_task_id == current,
                        Task.task_type == TaskType.Review,
                        Task.is_delete == False
                    )
                ).scalars().all()

                for review_task_id in review_tasks:
                    if review_task_id not in processed_tasks:
                        processed_tasks.add(review_task_id)
                        review_stack.append(review_task_id)  # continue recursive review traversal

                        # Checklists linked to review task
                        review_checklists = session.execute(
                            select(TaskChecklistLink.checklist_id)
                            .where(TaskChecklistLink.sub_task_id == review_task_id)
                        ).scalars().all()
                        for cid in review_checklists:
                            if cid and cid not in processed_checklists:
                                processed_checklists.add(cid)

            # 👇 Existing logic: get child checklists/subtasks
            results = session.execute(
                select(TaskChecklistLink.checklist_id, TaskChecklistLink.sub_task_id)
                .where(TaskChecklistLink.parent_task_id == tid)
            ).all()

            for checklist_id, sub_task_id in results:
                if checklist_id and checklist_id not in processed_checklists:
                    new_checklists.add(checklist_id)
                    processed_checklists.add(checklist_id)
                if sub_task_id and sub_task_id not in processed_tasks:
                    new_tasks.add(sub_task_id)

        for checklist_id in new_checklists:
            results = session.execute(
                select(TaskChecklistLink.sub_task_id)
                .where(TaskChecklistLink.checklist_id == checklist_id)
            ).scalars().all()
            for sub_task_id in results:
                if sub_task_id and sub_task_id not in processed_tasks:
                    new_tasks.add(sub_task_id)

        tasks_to_process = new_tasks

    return {
        "tasks": list(processed_tasks),
        "checklists": list(processed_checklists)
    }
