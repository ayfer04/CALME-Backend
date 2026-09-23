from fastapi import FastAPI

from app.api.v1 import assess, cabine, health, ingest, recommendations, sessions, stream

app = FastAPI(title="C.A.L.M.E. - API serveur de bord")

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
app.include_router(stream.router, prefix="/api/v1", tags=["stream"])
app.include_router(assess.router, prefix="/api/v1", tags=["assess"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["recommendations"])
app.include_router(cabine.router, prefix="/api/v1", tags=["cabine"])