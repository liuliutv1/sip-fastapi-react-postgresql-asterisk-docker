from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_runtime_schema(db: Session) -> None:
    """Apply small idempotent schema changes for already-initialized Docker volumes."""
    db.execute(text("ALTER TABLE outbound_calls ADD COLUMN IF NOT EXISTS hangup_cause VARCHAR(120)"))
    db.execute(text("ALTER TABLE outbound_calls ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0"))
    db.execute(text("ALTER TABLE outbound_calls ADD COLUMN IF NOT EXISTS attempted_trunk_ids TEXT"))
    db.execute(text("ALTER TABLE call_recordings ADD COLUMN IF NOT EXISTS file_path TEXT"))
    db.execute(text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS last_health_checked_at TIMESTAMPTZ"))
    db.execute(text("ALTER TABLE sip_trunks ADD COLUMN IF NOT EXISTS last_health_message TEXT"))
    db.execute(
        text(
            """
            WITH ranked_active_calls AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY destination_number
                        ORDER BY created_at DESC, id DESC
                    ) AS row_num
                FROM outbound_calls
                WHERE status IN (
                    'queued',
                    'initiating',
                    'dialing',
                    'ringing',
                    'answered',
                    'in_progress',
                    'hangup_requested'
                )
            )
            UPDATE outbound_calls
            SET
                status = 'completed',
                ended_at = COALESCE(ended_at, NOW()),
                hangup_cause = COALESCE(hangup_cause, '历史重复外呼自动归档')
            WHERE id IN (
                SELECT id
                FROM ranked_active_calls
                WHERE row_num > 1
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_calls_active_destination
            ON outbound_calls(destination_number)
            WHERE status IN (
                'queued',
                'initiating',
                'dialing',
                'ringing',
                'answered',
                'in_progress',
                'hangup_requested'
            )
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE call_recordings
            SET
                status = 'completed',
                file_path = COALESCE(file_path, local_path)
            WHERE status = 'available'
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE call_recordings
            SET file_path = COALESCE(file_path, local_path)
            WHERE status = 'completed' AND storage_backend = 'local'
            """
        )
    )
    db.commit()
