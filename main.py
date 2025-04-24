from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models.models import Base
from database.database import engine

from Tasks.Create_Task import router as create_task_router
from Tasks.Update_Task import router as update_task_router
from Tasks.Print_Task import router as print_task_router
from Checklist.Create_Checklist import router as create_checklist_router
from Checklist.Update_Checklist import router as update_checklist_router
from Checklist.checklist_status import router as checklist_status_router
from Delete.delete import router as delete_router
from Authentication.authy import router as auth_router
from Chat.chat import router as chat_router
from Logs.logs import router as logs_router

# Create all tables
Base.metadata.create_all(bind=engine)

# Initialize app
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://0.0.0.0:8001"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prefix for all routes
API_PREFIX = "/api/v1"

# Include routers with /api/v1/... prefix
app.include_router(auth_router, prefix=f"{API_PREFIX}/auth", tags=["Authentication"])
app.include_router(chat_router, prefix=f"{API_PREFIX}/chat", tags=["Chat"])
app.include_router(create_task_router, prefix=f"{API_PREFIX}/tasks", tags=["Tasks"])
app.include_router(update_task_router, prefix=f"{API_PREFIX}/tasks", tags=["Tasks"])
app.include_router(print_task_router, prefix=f"{API_PREFIX}/tasks", tags=["Tasks"])
app.include_router(create_checklist_router, prefix=f"{API_PREFIX}/checklist", tags=["Checklist"])
app.include_router(update_checklist_router, prefix=f"{API_PREFIX}/checklist", tags=["Checklist"])
app.include_router(checklist_status_router, prefix=f"{API_PREFIX}/checklist", tags=["Checklist"])
app.include_router(delete_router, prefix=f"{API_PREFIX}/delete", tags=["Delete"])
app.include_router(logs_router, prefix=f"{API_PREFIX}/logs", tags=["Logs"])
