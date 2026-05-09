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
    system,
)
from app.core.config import settings
from app.core.monitoring import ApiLoggingMiddleware, configure_logging, init_sentry
from app.db import Base, SessionLocal, engine
from app.services.ami_event_listener import ami_hangup_event_listener
from app.services.call_lifecycle import expire_stale_active_calls
from app.services.provider_defaults import ensure_carrier_sip_trunk
from app.services.schema_migrations import ensure_runtime_schema
from app.services.trunk_health import sip_trunk_health_monitor
from app.services.users import ensure_default_admin
from app import models  # noqa: F401

configure_logging()
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_runtime_schema(db)
        ensure_default_admin(db)
        ensure_carrier_sip_trunk(db)
        if expire_stale_active_calls(db):
            db.commit()
    sip_trunk_health_monitor.start()
    ami_hangup_event_listener.start()
    try:
        yield
    finally:
        ami_hangup_event_listener.stop()
        sip_trunk_health_monitor.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(ApiLoggingMiddleware)

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
app.include_router(outbound_calls.router, prefix="/api/calls/outbound", tags=["outbound-calls"])
app.include_router(phone_blacklists.router, prefix="/api/phone-blacklists", tags=["phone-blacklists"])
app.include_router(call_recordings.router, prefix="/api/call-recordings", tags=["call-recordings"])
app.include_router(audit_logs.router, prefix="/api/audit-logs", tags=["audit-logs"])
app.include_router(system.router, prefix="/api/system", tags=["system"])


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health/live",
    }
