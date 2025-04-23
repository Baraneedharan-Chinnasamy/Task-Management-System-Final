from pydantic import BaseModel

class CreateChecklistRequest(BaseModel):
    task_id: int
    checklist_name: str

class UpdateStatus(BaseModel):
    checklist_id: int
    is_completed: bool 

class UpdateChecklistRequest(BaseModel):
    checklist_id: int
    checklist_name: str


class checklist_sub(BaseModel):
    task_id: int