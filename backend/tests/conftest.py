import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123456")
os.environ.setdefault("ASTERISK_AMI_EVENT_LISTENER_ENABLED", "false")
os.environ.setdefault("SIP_TRUNK_HEALTH_CHECK_ENABLED", "false")
os.environ.setdefault("RECORDINGS_LOCAL_DIR", str(Path.cwd() / ".test-recordings"))
os.environ.setdefault("ASTERISK_RECORDINGS_DIR", str(Path.cwd() / ".test-recordings"))
os.environ.setdefault("SENTRY_DSN", "")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.provider_defaults import ensure_carrier_sip_trunk  # noqa: E402
from app.services.schema_migrations import ensure_runtime_schema  # noqa: E402
from app.services.users import ensure_default_admin  # noqa: E402


def _require_database() -> None:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for database-backed backend tests")


@pytest.fixture()
def reset_database():
    _require_database()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    Path(os.environ["RECORDINGS_LOCAL_DIR"]).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        ensure_runtime_schema(db)
        ensure_default_admin(db)
        ensure_carrier_sip_trunk(db)
    yield


@pytest.fixture()
def db_session(reset_database):
    with SessionLocal() as db:
        yield db


@pytest.fixture()
def client(reset_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(db_session):
    from app import models

    user = db_session.query(models.AppUser).filter(models.AppUser.username == "admin").first()
    token = create_access_token(subject=str(user.id), username=user.username)
    return {"Authorization": f"Bearer {token}"}
