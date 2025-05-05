from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import (
    Column, Integer, String, Text, Enum, Boolean, Date, TIMESTAMP, ForeignKey, func, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import LONGTEXT, JSON
from enum import Enum as PyEnum

Base = declarative_base()

# Updated TaskStatus Enum
class TaskStatus(PyEnum):
    To_Do = "To_Do"
    In_Progress = "In_Progress"
    In_Review = "In_Review"
    In_ReEdit = "In_ReEdit"
    Completed = "Completed"
    New = "New"

# Updated TaskType Enum
class TaskType(PyEnum):
    Normal = "Normal"
    Review = "Review"

class User(Base):
    __tablename__ = "users"

    employee_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    designation = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

class Task(Base):
    __tablename__ = "tasks"

    task_id = Column(Integer, primary_key=True, autoincrement=True)
    assigned_to = Column(Integer, ForeignKey("users.employee_id"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.employee_id"), nullable=True, index=True)
    task_name = Column(String(60), nullable=False, index=True)
    description = Column(LONGTEXT, nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.To_Do.name, index=True)
    previous_status = Column(Enum(TaskStatus), nullable=True, index=True)
    task_type = Column(Enum(TaskType), nullable=False, default=TaskType.Normal.name, index=True)
    due_date = Column(Date, nullable=True, index=True)

    is_review_required = Column(Boolean, default=False)
    is_reviewed = Column(Boolean, default=False)
    parent_task_id = Column(Integer, ForeignKey("tasks.task_id"), nullable=True, index=True)

    output = Column(LONGTEXT, nullable=True)
    is_delete = Column(Boolean, default=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    chat_room = relationship('ChatRoom', uselist=False, back_populates='task')

class Checklist(Base):
    __tablename__ = "checklist"

    checklist_id = Column(Integer, primary_key=True, autoincrement=True)
    checklist_name = Column(LONGTEXT, nullable=False, index=True)
    is_completed = Column(Boolean, default=False, index=True)
    created_by = Column(Integer, ForeignKey("users.employee_id"), nullable=True, index=True)
    is_delete = Column(Boolean, default=False, index=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

class TaskChecklistLink(Base):
    __tablename__ = "task_checklist_link"

    link_id = Column(Integer, primary_key=True, autoincrement=True)
    parent_task_id = Column(Integer, ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=True, index=True)
    checklist_id = Column(Integer, ForeignKey("checklist.checklist_id", ondelete="CASCADE"), nullable=True, index=True)
    sub_task_id = Column(Integer, ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=True, index=True)

class TaskUpdateLog(Base):
    __tablename__ = "task_update_logs"

    log_id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    old_value = Column(LONGTEXT)
    new_value = Column(LONGTEXT)
    updated_by = Column(Integer, ForeignKey("users.employee_id"), nullable=False, index=True)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Optional: Relationships (if needed)
    task = relationship("Task", backref="update_logs")
    user = relationship("User", foreign_keys=[updated_by])

class ChecklistUpdateLog(Base):
    __tablename__ = "checklist_update_logs"

    log_id = Column(Integer, primary_key=True, index=True)
    checklist_id = Column(Integer, ForeignKey("checklist.checklist_id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text)
    new_value = Column(Text)
    updated_by = Column(Integer, ForeignKey("users.employee_id"), nullable=False, index=True)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    # Optional: Relationships
    checklist = relationship("Checklist", backref="update_logs")
    user = relationship("User", foreign_keys=[updated_by])

class ChatRoom(Base):
    __tablename__ = 'chat_rooms'
    chat_room_id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey('tasks.task_id'), nullable=False, unique=True, index=True)  # One chat per task
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    task = relationship('Task', back_populates='chat_room')
    messages = relationship('ChatMessage', back_populates='chat_room', cascade='all, delete')

class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    message_id = Column(Integer, primary_key=True, index=True)
    chat_room_id = Column(Integer, ForeignKey('chat_rooms.chat_room_id'), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey('users.employee_id'), nullable=False, index=True)
    message = Column(Text, nullable=False)
    visible_to = Column(JSON, nullable=True)
    timestamp = Column(TIMESTAMP, server_default=func.current_timestamp(), index=True)

    chat_room = relationship('ChatRoom', back_populates='messages')
    sender = relationship('User')

class ChatMessageRead(Base):
    __tablename__ = 'chat_message_reads'
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey('chat_messages.message_id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.employee_id'), nullable=False, index=True)
    seen_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', name='uq_message_user_seen'),
    )