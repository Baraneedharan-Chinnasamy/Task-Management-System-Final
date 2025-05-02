from models.models import ChatMessageRead
from sqlalchemy.orm import Session
from fastapi import WebSocket
from typing import Dict, List
from sqlalchemy.exc import IntegrityError

class ChatManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, chat_room_id: int):
        # WebSocket should be accepted externally in the route handler
        if chat_room_id not in self.active_connections:
            self.active_connections[chat_room_id] = []
        self.active_connections[chat_room_id].append(websocket)

    def disconnect(self, websocket: WebSocket, chat_room_id: int):
        if chat_room_id in self.active_connections:
            if websocket in self.active_connections[chat_room_id]:
                self.active_connections[chat_room_id].remove(websocket)

    async def broadcast(self, chat_room_id: int, message: dict, db: Session = None):
        connections = self.active_connections.get(chat_room_id, [])
        to_remove = []

        for connection in connections:
            try:
                user_id = connection.scope.get("user_id")
                await connection.send_json(message)

                if db and user_id:
                    try:
                        db.add(ChatMessageRead(message_id=message["message_id"], user_id=user_id))
                        db.commit()
                    except IntegrityError:
                        db.rollback()
            except Exception:
                to_remove.append(connection)

        for conn in to_remove:
            self.disconnect(conn, chat_room_id)

    async def broadcast_to_users(self, chat_room_id: int, message: dict, user_ids: List[int], db: Session = None):
        connections = self.active_connections.get(chat_room_id, [])
        to_remove = []

        for connection in connections:
            try:
                user_id = connection.scope.get("user_id")
                if user_id in user_ids:
                    await connection.send_json(message)

                    if db and user_id:
                        try:
                            db.add(ChatMessageRead(message_id=message["message_id"], user_id=user_id))
                            db.commit()
                        except IntegrityError:
                            db.rollback()
            except Exception:
                to_remove.append(connection)

        for conn in to_remove:
            self.disconnect(conn, chat_room_id)
