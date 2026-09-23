import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.hub import hub

router = APIRouter()


@router.websocket("/sessions/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: int):
    await websocket.accept()
    hub.rejoindre(session_id, websocket)
    try:
        while True:
            # Le client ne pousse rien d'autre qu'un ping : on attend
            # simplement qu'il se taise pour detecter la deconnexion.
            await asyncio.wait_for(websocket.receive_text(), timeout=60)
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        pass
    finally:
        hub.quitter(session_id, websocket)
