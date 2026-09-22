from fastapi import FastAPI

from app.api.v1 import health, ingest

app = FastAPI(title="C.A.L.M.E. - API serveur de bord")

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])