CREATE TABLE IF NOT EXISTS call_recordings (
    id SERIAL PRIMARY KEY,
    outbound_call_id INTEGER REFERENCES outbound_calls(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    destination_number VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    storage_backend VARCHAR(32) NOT NULL DEFAULT 'local',
    filename VARCHAR(255) NOT NULL UNIQUE,
    content_type VARCHAR(80) NOT NULL DEFAULT 'audio/wav',
    local_path TEXT,
    asterisk_path TEXT,
    oss_key TEXT,
    file_size_bytes BIGINT,
    duration_seconds INTEGER,
    retention_expires_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    deleted_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_call_recordings_outbound_call_id ON call_recordings(outbound_call_id);
CREATE INDEX IF NOT EXISTS ix_call_recordings_user_id ON call_recordings(user_id);
CREATE INDEX IF NOT EXISTS ix_call_recordings_destination_number ON call_recordings(destination_number);
CREATE INDEX IF NOT EXISTS ix_call_recordings_status ON call_recordings(status);
CREATE INDEX IF NOT EXISTS ix_call_recordings_storage_backend ON call_recordings(storage_backend);
CREATE INDEX IF NOT EXISTS ix_call_recordings_filename ON call_recordings(filename);
CREATE INDEX IF NOT EXISTS ix_call_recordings_retention_expires_at ON call_recordings(retention_expires_at);
CREATE INDEX IF NOT EXISTS ix_call_recordings_deleted_at ON call_recordings(deleted_at);
CREATE INDEX IF NOT EXISTS ix_call_recordings_created_at ON call_recordings(created_at);
