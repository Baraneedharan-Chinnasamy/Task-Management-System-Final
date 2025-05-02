from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from models.models import ChatMessage, ChatRoom, ChatMessageRead,Task,TaskType
from database.database import get_db, SessionLocal
from Chat.chat_manager import ChatManager

def get_original_normal_task(db: Session, task_id: int):
    current_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not current_task:
        return None

    # Traverse up the parent chain until you reach a Normal task
    while current_task.task_type == TaskType.Review and current_task.parent_task_id:
        parent = db.query(Task).filter(Task.task_id == current_task.parent_task_id).first()
        if not parent:
            break
        current_task = parent

    return current_task

router = APIRouter()
chat_manager = ChatManager()


@router.websocket("/chat")
async def chat_websocket(
    websocket: WebSocket,
    task_id: int,
    user_id: int,
    db: Session = Depends(get_db)
):
    await websocket.accept()
    try:
        task = db.query(Task).filter(Task.task_id==task_id).first()
        if task.task_type == TaskType.Review:
            original_task = get_original_normal_task(db, task_id)
            task_ids = original_task.task_id
        else:
            task_ids = task.task_id
        print("task",task_ids)

        chat_room = db.query(ChatRoom).filter(ChatRoom.task_id == task_ids).first()
        if not chat_room:
            await websocket.close(code=1008)  # Policy Violation
            return

        chat_room_id = chat_room.chat_room_id
        websocket.scope["user_id"] = user_id
        await chat_manager.connect(websocket, chat_room_id)

        while True:
            data = await websocket.receive_json()
            message_text = data["message"]
            sender_id = data["sender_id"]
            visible_to = data.get("visible_to")

            # Save message to DB
            chat_message = ChatMessage(
                chat_room_id=chat_room_id,
                sender_id=sender_id,
                message=message_text,
                visible_to=visible_to
            )
            db.add(chat_message)
            db.commit()
            db.refresh(chat_message)

            message_payload = {
                "message_id": chat_message.message_id,
                "sender_id": sender_id,
                "message": message_text,
                "visible_to": visible_to,
                "timestamp": str(chat_message.timestamp)
            }

            # Broadcast to users
            if not visible_to:
                await chat_manager.broadcast(chat_room_id, message_payload, db=db)
            else:
                await chat_manager.broadcast_to_users(chat_room_id, message_payload, visible_to, db=db)

    except WebSocketDisconnect:
        chat_manager.disconnect(websocket, chat_room_id)
    except Exception as e:
        print("❌ WebSocket error:", e)
        chat_manager.disconnect(websocket, chat_room_id)
    finally:
        db.close()


@router.get("/chat_history")
def get_chat_history(
    task_id: int,
    user_id: int,
    limit: int = 20,
    before_timestamp: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.task_id==task_id).first()
    if task.task_type == TaskType.Review:
        original_task = get_original_normal_task(db, task_id)
        task_ids = original_task.task_id
    else:
        task_ids = task.task_id
    chat_room = db.query(ChatRoom).filter(ChatRoom.task_id == task_ids).first()
    if not chat_room:
        raise HTTPException(status_code=404, detail="Chat room not found")

    chat_room_id = chat_room.chat_room_id
    query = db.query(ChatMessage).filter(ChatMessage.chat_room_id == chat_room_id)
    if before_timestamp:
        query = query.filter(ChatMessage.timestamp < before_timestamp)

    messages = query.order_by(ChatMessage.timestamp.desc()).limit(limit).all()
    messages.reverse()

    read_message_ids = {
        r.message_id for r in db.query(ChatMessageRead.message_id)
        .filter_by(user_id=user_id)
        .all()
    }

    visible_messages = []
    for msg in messages:
        if not msg.visible_to or user_id in msg.visible_to:
            visible_messages.append({
                "message_id": msg.message_id,
                "sender_id": msg.sender_id,
                "message": msg.message,
                "timestamp": str(msg.timestamp),
                "seen": msg.message_id in read_message_ids
            })

            if msg.message_id not in read_message_ids and msg.sender_id != user_id:
                db.add(ChatMessageRead(message_id=msg.message_id, user_id=user_id))

    db.commit()
    return visible_messages
