from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import or_, update, asc, desc
from models.models import ChatMessage
from database.database import get_db
from datetime import datetime
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect
from Chat.chat_manager import ChatManager,ChatMessageRead



router = APIRouter()

chat_manager = ChatManager()

@router.websocket("/chat/{chat_room_id}")
async def chat_websocket(
    websocket: WebSocket,
    chat_room_id: int,
    user_id: int,
    db: Session = Depends(get_db)
):
    websocket.scope["user_id"] = user_id
    await chat_manager.connect(websocket, chat_room_id)

    try:
        while True:
            data = await websocket.receive_json()
            message_text = data["message"]
            sender_id = data["sender_id"]
            visible_to = data.get("visible_to")

            # Save to DB
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

            if not visible_to:
                await chat_manager.broadcast(chat_room_id, message_payload, db=db)
            else:
                await chat_manager.broadcast_to_users(chat_room_id, message_payload, visible_to, db=db)

    except WebSocketDisconnect:
        chat_manager.disconnect(websocket, chat_room_id)


@router.get("/chat_history/{chat_room_id}")
def get_chat_history(
    chat_room_id: int,
    user_id: int,
    limit: int = 20,
    before_timestamp: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    query = db.query(ChatMessage).filter(ChatMessage.chat_room_id == chat_room_id)
    if before_timestamp:
        query = query.filter(ChatMessage.timestamp < before_timestamp)

    messages = query.order_by(ChatMessage.timestamp.desc()).limit(limit).all()
    messages.reverse()

    visible_messages = []
    read_message_ids = {
        r.message_id for r in db.query(ChatMessageRead.message_id)
        .filter_by(user_id=user_id)
        .all()
    }

    for msg in messages:
        if not msg.visible_to or user_id in msg.visible_to:
            visible_messages.append({
                "message_id": msg.message_id,
                "sender_id": msg.sender_id,
                "message": msg.message,
                "timestamp": str(msg.timestamp),
                "seen": msg.message_id in read_message_ids
            })

            # Mark as read if not already
            if msg.message_id not in read_message_ids and msg.sender_id != user_id:
                db.add(ChatMessageRead(message_id=msg.message_id, user_id=user_id))

    db.commit()
    return visible_messages
