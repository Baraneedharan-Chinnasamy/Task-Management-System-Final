from models.models import TaskChecklistLink,Task,Checklist,TaskStatus  
from Logs.functions import log_task_field_change,log_checklist_field_change
def Mark_complete_help(task_id, db,Current_user, visited_tasks=None):
    """
    Recursively updates task completion status based on checklist completions.
    
    This function checks if all subtasks linked to a checklist are completed,
    marks the checklist as completed if so, and then propagates this status
    up the task hierarchy.
    
    Args:
        task_id: The ID of the task to start processing from
        db: Database session
        visited_tasks: Set of already visited task IDs to prevent infinite recursion
    """
    # Initialize visited_tasks if not provided to prevent mutable default argument issues
    if visited_tasks is None:
        visited_tasks = set()
    
    # Prevent cycles in the recursion
    if task_id in visited_tasks:
        return
    visited_tasks.add(task_id)

    # Find all links where this task is a subtask
    subtask_links = db.query(TaskChecklistLink).filter(
        TaskChecklistLink.sub_task_id == task_id
    ).all()
    
    # Group links by checklist_id to reduce database queries
    checklist_groups = {}
    for link in subtask_links:
        if link.checklist_id not in checklist_groups:
            checklist_groups[link.checklist_id] = []
        checklist_groups[link.checklist_id].append(link)
    
    # Process each checklist group
    for checklist_id, _ in checklist_groups.items():
        # Get all subtasks linked to this checklist in a single query
        sibling_subtasks = db.query(Task).join(
            TaskChecklistLink, 
            TaskChecklistLink.sub_task_id == Task.task_id
        ).filter(
            TaskChecklistLink.checklist_id == checklist_id, 
            Task.is_delete == False
        ).all()
        
        # Check if all siblings are completed
        all_completed = all(task.status == TaskStatus.Completed for task in sibling_subtasks)
        
        if all_completed:
            # Find and update the checklist
            checklist = db.query(Checklist).filter(
                Checklist.checklist_id == checklist_id, 
                Checklist.is_delete == False
            ).first()
            
            if checklist and not checklist.is_completed:
                log_checklist_field_change(db,checklist.checklist_id,"is_compelete",checklist.is_completed,True,Current_user.employee_id)
                checklist.is_completed = True
                
                # Find all parent tasks for this checklist in a single query
                parent_links = db.query(TaskChecklistLink).filter(
                    TaskChecklistLink.checklist_id == checklist_id,
                    TaskChecklistLink.parent_task_id.isnot(None)
                ).all()
                
                # Group parent links by parent_task_id to reduce queries
                parent_task_groups = {}
                for parent_link in parent_links:
                    if parent_link.parent_task_id not in parent_task_groups:
                        parent_task_groups[parent_link.parent_task_id] = []
                    parent_task_groups[parent_link.parent_task_id].append(parent_link)
                
                # Process each parent task
                for parent_task_id, _ in parent_task_groups.items():
                    # Get all checklists for this parent task in a single query
                    all_checklists = db.query(Checklist).join(
                        TaskChecklistLink, 
                        TaskChecklistLink.checklist_id == Checklist.checklist_id
                    ).filter(
                        TaskChecklistLink.parent_task_id == parent_task_id, 
                        Checklist.is_delete == False
                    ).all()
                    
                    # If all checklists are completed, update parent task status
                    if all(c.is_completed for c in all_checklists):
                        parent_task = db.query(Task).filter(
                            Task.task_id == parent_task_id, 
                            Task.is_delete == False
                        ).first()
                        
                        if parent_task:
                            # Determine new status based on review requirements
                            new_status = TaskStatus.In_Review if parent_task.is_review_required else TaskStatus.Completed
                            
                            if parent_task.status != new_status:
                                old_status = parent_task.status
                                parent_task.status = new_status
                                # Log the status change
                                log_task_field_change(db, parent_task.task_id,"status", old_status, new_status,2)
                                
                                # Continue the recursive process for the parent task
                                Mark_complete_help(parent_task_id, db,Current_user, visited_tasks)


def upload_output_to_all_reviews(task_id, output, db,current_user):
    while True:
        task = db.query(Task).filter(Task.task_id == task_id, Task.is_delete == False).first()
        if not task:
            break

        old_status = task.status
        log_task_field_change(db, task.task_id, "output", task.output, output, current_user.employee_id)
        task.output = output
        task.is_reviewed = False
        task.status = TaskStatus.To_Do
        print(current_user.employee_id)
        log_task_field_change(db, task.task_id,"output", old_status, "To_Do",2)
        db.flush()

        next_review = db.query(Task).filter(Task.parent_task_id == task.task_id, Task.is_delete == False).first()
        if next_review:
            task_id = next_review.task_id
        else:
            break