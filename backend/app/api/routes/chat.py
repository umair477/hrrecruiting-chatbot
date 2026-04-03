from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlmodel import Session, select

from backend.app.core.database import engine
from backend.app.core.security import decode_token
from backend.app.models import User, UserRole
from backend.app.services.chat import ChatRuntime, handle_chat_turn

router = APIRouter(tags=["chat"])


@router.websocket("/ws/chat")
async def chat_socket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    try:
        payload = decode_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        await websocket.close(code=4401)
        return

    with Session(engine) as session:
        user = session.exec(select(User).where(User.id == user_id)).first()
        if user is None:
            await websocket.close(code=4401)
            return
        if user.role == UserRole.CANDIDATE:
            await websocket.close(code=4403)
            return

        thread_id = websocket.query_params.get("thread_id") or f"user-{user_id}"
        runtime = ChatRuntime(user=user, thread_id=thread_id)
        await websocket.accept()
        await websocket.send_json(
            {
                "thread_id": thread_id,
                "workflow": "unknown",
                "reply": "Talent Spark is live. Ask for leave help or start a recruitment screening request.",
                "missing_slots": [],
                "privacy_note": None,
                "structured_report": None,
            }
        )

        try:
            while True:
                payload = await websocket.receive_json()
                message = str(payload.get("message", "")).strip()
                if not message:
                    continue
                response = handle_chat_turn(runtime, message, session)
                await websocket.send_json(response.model_dump(mode="json"))
        except WebSocketDisconnect:
            return
