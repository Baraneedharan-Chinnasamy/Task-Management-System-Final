from pydantic import BaseModel

class DeleteItemsRequest(BaseModel):
    task_id: int = None
    checklist_id: int = None