from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.hub import hub

router = APIRouter()


@router.websocket("/sessions/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: int):
    await websocket.accept()
    hub.rejoindre(session_id, websocket)
    try:
        while True:
            # Le client n'envoie rien, ne fait qu'ecouter. On attend le
            # receive_text() qui bloque jusqu'a deconnexion. Uvicorn detecte
            # les pairs morts via ses pings WebSocket (20 s par defaut) meme
            # sans trame de fermeture, ce qui permet de gerer les scenarios
            # de coupure reseau brutale.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.quitter(session_id, websocket)
