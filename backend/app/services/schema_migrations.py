from sqlalchemy import text
from sqlalchemy.orm import Session


def ensure_runtime_schema(db: Session) -> None:
    """Apply small idempotent schema changes for already-initialized Docker volumes."""
    db.execute(
        text(
            """
            ALTER TABLE sip_trunks
                ADD COLUMN IF NOT EXISTS name VARCHAR(120),
                ADD COLUMN IF NOT EXISTS provider_name VARCHAR(120),
                ADD COLUMN IF NOT EXISTS description TEXT,
                ADD COLUMN IF NOT EXISTS host VARCHAR(255),
                ADD COLUMN IF NOT EXISTS port INTEGER DEFAULT 5060,
                ADD COLUMN IF NOT EXISTS transport VARCHAR(16) DEFAULT 'udp',
                ADD COLUMN IF NOT EXISTS username VARCHAR(120),
                ADD COLUMN IF NOT EXISTS auth_username VARCHAR(120),
                ADD COLUMN IF NOT EXISTS password_encrypted TEXT,
                ADD COLUMN IF NOT EXISTS from_user VARCHAR(120),
                ADD COLUMN IF NOT EXISTS from_domain VARCHAR(255),
                ADD COLUMN IF NOT EXISTS outbound_proxy VARCHAR(255),
                ADD COLUMN IF NOT EXISTS caller_id VARCHAR(80),
                ADD COLUMN IF NOT EXISTS codecs VARCHAR(255) DEFAULT 'ulaw,alaw',
                ADD COLUMN IF NOT EXISTS max_channels INTEGER DEFAULT 30,
                ADD COLUMN IF NOT EXISTS registration_enabled BOOLEAN DEFAULT FALSE,
                ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'inactive',
                ADD COLUMN IF NOT EXISTS last_health_checked_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS last_health_message TEXT,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE sip_trunks
            SET
                name = COALESCE(NULLIF(name, ''), 'trunk-' || id::text),
                host = COALESCE(NULLIF(host, ''), '218.245.102.33'),
                port = COALESCE(port, 5060),
                transport = COALESCE(NULLIF(transport, ''), 'udp'),
                codecs = COALESCE(NULLIF(codecs, ''), 'ulaw,alaw'),
                max_channels = COALESCE(max_channels, 30),
                registration_enabled = COALESCE(registration_enabled, FALSE),
                enabled = COALESCE(enabled, TRUE),
                status = COALESCE(NULLIF(status, ''), 'inactive'),
                created_at = COALESCE(created_at, NOW()),
                updated_at = COALESCE(updated_at, NOW())
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE sip_peer_whitelists
                ADD COLUMN IF NOT EXISTS sip_trunk_id INTEGER,
                ADD COLUMN IF NOT EXISTS name VARCHAR(120),
                ADD COLUMN IF NOT EXISTS peer_cidr VARCHAR(64),
                ADD COLUMN IF NOT EXISTS description TEXT,
                ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE sip_peer_whitelists
            SET
                name = COALESCE(NULLIF(name, ''), 'SIP peer ' || id::text),
                peer_cidr = COALESCE(NULLIF(peer_cidr, ''), '0.0.0.0/32'),
                enabled = COALESCE(enabled, TRUE),
                created_at = COALESCE(created_at, NOW()),
                updated_at = COALESCE(updated_at, NOW())
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE audit_logs
                ADD COLUMN IF NOT EXISTS user_id INTEGER,
                ADD COLUMN IF NOT EXISTS username VARCHAR(80),
                ADD COLUMN IF NOT EXISTS action VARCHAR(64),
                ADD COLUMN IF NOT EXISTS resource_type VARCHAR(80),
                ADD COLUMN IF NOT EXISTS resource_id INTEGER,
                ADD COLUMN IF NOT EXISTS ip_address VARCHAR(64),
                ADD COLUMN IF NOT EXISTS user_agent VARCHAR(255),
                ADD COLUMN IF NOT EXISTS before_values JSONB,
                ADD COLUMN IF NOT EXISTS after_values JSONB,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE audit_logs
            SET
                action = COALESCE(NULLIF(action, ''), 'unknown'),
                resource_type = COALESCE(NULLIF(resource_type, ''), 'unknown'),
                created_at = COALESCE(created_at, NOW())
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE outbound_calls
                ADD COLUMN IF NOT EXISTS user_id INTEGER,
                ADD COLUMN IF NOT EXISTS sip_trunk_id INTEGER,
                ADD COLUMN IF NOT EXISTS destination_number VARCHAR(32),
                ADD COLUMN IF NOT EXISTS caller_id VARCHAR(80),
                ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'initiating',
                ADD COLUMN IF NOT EXISTS ami_action_id VARCHAR(120),
                ADD COLUMN IF NOT EXISTS ami_channel_id VARCHAR(120),
                ADD COLUMN IF NOT EXISTS asterisk_channel VARCHAR(255),
                ADD COLUMN IF NOT EXISTS failure_reason TEXT,
                ADD COLUMN IF NOT EXISTS hangup_cause VARCHAR(120),
                ADD COLUMN IF NOT EXISTS attempt_count INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS attempted_trunk_ids TEXT,
                ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS answered_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE outbound_calls
            SET
                destination_number = COALESCE(NULLIF(destination_number, ''), 'unknown'),
                status = COALESCE(NULLIF(status, ''), 'initiating'),
                attempt_count = COALESCE(attempt_count, 0),
                created_at = COALESCE(created_at, NOW()),
                updated_at = COALESCE(updated_at, NOW())
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE phone_blacklists
                ADD COLUMN IF NOT EXISTS normalized_number VARCHAR(32),
                ADD COLUMN IF NOT EXISTS reason TEXT,
                ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE phone_blacklists
            SET
                normalized_number = COALESCE(NULLIF(normalized_number, ''), 'unknown-' || id::text),
                enabled = COALESCE(enabled, TRUE),
                created_at = COALESCE(created_at, NOW()),
                updated_at = COALESCE(updated_at, NOW())
            """
        )
    )
    db.execute(
        text(
            """
            ALTER TABLE call_recordings
                ADD COLUMN IF NOT EXISTS outbound_call_id INTEGER,
                ADD COLUMN IF NOT EXISTS user_id INTEGER,
                ADD COLUMN IF NOT EXISTS destination_number VARCHAR(32),
                ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'pending',
                ADD COLUMN IF NOT EXISTS storage_backend VARCHAR(32) DEFAULT 'local',
                ADD COLUMN IF NOT EXISTS filename VARCHAR(255),
                ADD COLUMN IF NOT EXISTS content_type VARCHAR(80) DEFAULT 'audio/wav',
                ADD COLUMN IF NOT EXISTS local_path TEXT,
                ADD COLUMN IF NOT EXISTS asterisk_path TEXT,
                ADD COLUMN IF NOT EXISTS oss_key TEXT,
                ADD COLUMN IF NOT EXISTS file_path TEXT,
                ADD COLUMN IF NOT EXISTS file_size_bytes BIGINT,
                ADD COLUMN IF NOT EXISTS duration_seconds INTEGER,
                ADD COLUMN IF NOT EXISTS retention_expires_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
                ADD COLUMN IF NOT EXISTS deleted_by_user_id INTEGER,
                ADD COLUMN IF NOT EXISTS failure_reason TEXT,
                ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE call_recordings
            SET
                destination_number = COALESCE(NULLIF(destination_number, ''), 'unknown'),
                status = COALESCE(NULLIF(status, ''), 'pending'),
                storage_backend = COALESCE(NULLIF(storage_backend, ''), 'local'),
                filename = COALESCE(NULLIF(filename, ''), 'recording-' || id::text || '.wav'),
                content_type = COALESCE(NULLIF(content_type, ''), 'audio/wav'),
                created_at = COALESCE(created_at, NOW()),
                updated_at = COALESCE(updated_at, NOW())
            """
        )
    )
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
