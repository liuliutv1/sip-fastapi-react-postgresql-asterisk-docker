ALTER TABLE outbound_calls
    ADD COLUMN IF NOT EXISTS hangup_cause VARCHAR(120);

WITH ranked_active_calls AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY destination_number
            ORDER BY created_at DESC, id DESC
        ) AS row_num
    FROM outbound_calls
    WHERE status IN ('queued', 'initiating', 'dialing', 'ringing', 'answered', 'in_progress', 'hangup_requested')
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
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_calls_active_destination
ON outbound_calls(destination_number)
WHERE status IN ('queued', 'initiating', 'dialing', 'ringing', 'answered', 'in_progress', 'hangup_requested');
