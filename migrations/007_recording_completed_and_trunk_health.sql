ALTER TABLE call_recordings
    ADD COLUMN IF NOT EXISTS file_path TEXT;

UPDATE call_recordings
SET
    status = 'completed',
    file_path = COALESCE(file_path, local_path)
WHERE status = 'available';

UPDATE call_recordings
SET file_path = COALESCE(file_path, local_path)
WHERE status = 'completed' AND storage_backend = 'local';

ALTER TABLE sip_trunks
    ADD COLUMN IF NOT EXISTS last_health_checked_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_health_message TEXT;

ALTER TABLE outbound_calls
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS attempted_trunk_ids TEXT;
