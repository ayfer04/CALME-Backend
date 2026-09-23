from fastapi import FastAPI

from app.api.v1 import assess, health, ingest, stream

app = FastAPI(title="C.A.L.M.E. - API serveur de bord")

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
app.include_router(stream.router, prefix="/api/v1", tags=["stream"])
app.include_router(assess.router, prefix="/api/v1", tags=["assess"])