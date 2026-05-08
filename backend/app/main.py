from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agents,
    audit_logs,
    auth,
    call_recordings,
    calls,
    campaigns,
    health,
    outbound_calls,
    phone_blacklists,
    sip_peer_whitelists,
    sip_trunks,
)
from app.core.config import settings
from app.db import Base, SessionLocal, engine
from app.services.provider_defaults import ensure_carrier_sip_trunk
from app.services.users import ensure_default_admin
from app import models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_default_admin(db)
        ensure_carrier_sip_trunk(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(campaigns.router, prefix="/api/campaigns", tags=["campaigns"])
app.include_router(calls.router, prefix="/api/calls", tags=["calls"])
app.include_router(sip_trunks.router, prefix="/api/sip-trunks", tags=["sip-trunks"])
app.include_router(sip_peer_whitelists.router, prefix="/api/sip-peer-whitelists", tags=["sip-peer-whitelists"])
app.include_router(outbound_calls.router, prefix="/api/outbound-calls", tags=["outbound-calls"])
app.include_router(phone_blacklists.router, prefix="/api/phone-blacklists", tags=["phone-blacklists"])
app.include_router(call_recordings.router, prefix="/api/call-recordings", tags=["call-recordings"])
app.include_router(audit_logs.router, prefix="/api/audit-logs", tags=["audit-logs"])


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health/live",
    }
