import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import models
from app.core.config import settings


def build_recording_filename(call_id: int) -> str:
    return f"outbound-{call_id}-{uuid.uuid4().hex}.wav"


def local_recording_path(filename: str) -> str:
    return str(_safe_join(settings.recordings_local_dir, filename))


def asterisk_recording_path(filename: str) -> str:
    return str(_safe_join(settings.asterisk_recordings_dir, filename))


def retention_expires_at() -> datetime | None:
    if settings.recording_retention_days <= 0:
        return None
    return datetime.now(UTC) + timedelta(days=settings.recording_retention_days)


def ensure_recording_dir() -> None:
    Path(settings.recordings_local_dir).mkdir(parents=True, exist_ok=True)


def refresh_local_file_metadata(recording: models.CallRecording, *, mark_available: bool = True) -> None:
    if not recording.local_path:
        return
    path = Path(recording.local_path)
    if not path.exists() or not path.is_file():
        return
    recording.file_size_bytes = path.stat().st_size
    if mark_available and recording.status in {"pending", "recording", "failed"} and recording.file_size_bytes > 0:
        recording.status = "available"
        recording.failure_reason = None


def delete_local_file(recording: models.CallRecording) -> None:
    if not recording.local_path:
        return
    path = Path(recording.local_path)
    if path.exists() and path.is_file():
        path.unlink()


class AliyunOssAdapter:
    def __init__(self):
        if not settings.aliyun_oss_endpoint or not settings.aliyun_oss_bucket:
            raise RuntimeError("Aliyun OSS endpoint and bucket are required")
        import oss2

        auth = oss2.Auth(settings.aliyun_oss_access_key_id, settings.aliyun_oss_access_key_secret)
        self.bucket = oss2.Bucket(auth, settings.aliyun_oss_endpoint, settings.aliyun_oss_bucket)

    def upload_file(self, local_path: str, filename: str) -> str:
        oss_key = _oss_key(filename)
        self.bucket.put_object_from_file(oss_key, local_path)
        return oss_key

    def sign_url(self, oss_key: str, filename: str, as_attachment: bool) -> str:
        headers = {}
        if as_attachment:
            headers["response-content-disposition"] = f'attachment; filename="{filename}"'
        return self.bucket.sign_url("GET", oss_key, settings.aliyun_oss_signed_url_expire_seconds, params=headers)

    def delete_object(self, oss_key: str) -> None:
        self.bucket.delete_object(oss_key)


def upload_to_oss_if_enabled(recording: models.CallRecording) -> None:
    if settings.recordings_storage_backend.lower() != "oss":
        return
    if recording.oss_key:
        recording.storage_backend = "oss"
        return
    if not recording.local_path or not Path(recording.local_path).exists():
        return
    adapter = AliyunOssAdapter()
    recording.oss_key = adapter.upload_file(recording.local_path, recording.filename)
    recording.storage_backend = "oss"


def signed_oss_url(recording: models.CallRecording, *, as_attachment: bool) -> str:
    if not recording.oss_key:
        raise RuntimeError("Recording has no OSS object key")
    return AliyunOssAdapter().sign_url(recording.oss_key, recording.filename, as_attachment)


def delete_oss_object_if_exists(recording: models.CallRecording) -> None:
    if not recording.oss_key:
        return
    AliyunOssAdapter().delete_object(recording.oss_key)


def _oss_key(filename: str) -> str:
    prefix = settings.aliyun_oss_prefix.strip("/")
    return f"{prefix}/{filename}" if prefix else filename


def _safe_join(root: str, filename: str) -> Path:
    if os.path.basename(filename) != filename:
        raise ValueError("Recording filename must not contain path separators")
    root_path = Path(root).resolve()
    candidate = (root_path / filename).resolve()
    if root_path not in candidate.parents and candidate != root_path:
        raise ValueError("Recording path escapes configured root")
    return candidate
