from pydantic import BaseModel, EmailStr
from typing import Optional,List
from datetime import date
from typing import Dict, List


class CreateTask(BaseModel):
    checklist_id: Optional[int] = None
    task_name: str
    description: str
    due_date: date
    assigned_to: int
    checklist_names: List[str]
    is_review_required : bool


class UpdateTaskRequest(BaseModel):
    task_id: Optional[int] = None
    assigned_to: Optional[int] = None
    task_name: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    output :Optional[str] = None
    is_review_required: Optional[bool] = None
    is_reviewed: Optional[bool] = None
    


class SendForReview(BaseModel):
    task_id: int
    assigned_to: int