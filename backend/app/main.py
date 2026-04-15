from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import (
    admin,
    analytics,
    auth,
    chat,
    employee_portal,
    innovation,
    integrations,
    leave,
    public_candidate,
    recruitment,
)
from backend.app.core.config import settings
from backend.app.core.database import create_db_and_tables, session_scope
from backend.app.seed import seed_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_db_and_tables()
    with session_scope() as session:
        seed_database(session)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(leave.router, prefix="/api")
app.include_router(recruitment.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(employee_portal.router, prefix="/api")
app.include_router(public_candidate.router, prefix="/api")
app.include_router(innovation.router, prefix="/api")


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
