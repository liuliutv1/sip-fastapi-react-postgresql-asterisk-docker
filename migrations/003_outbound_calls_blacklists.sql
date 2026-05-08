CREATE TABLE IF NOT EXISTS outbound_calls (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    sip_trunk_id INTEGER REFERENCES sip_trunks(id) ON DELETE SET NULL,
    destination_number VARCHAR(32) NOT NULL,
    caller_id VARCHAR(80),
    status VARCHAR(32) NOT NULL DEFAULT 'initiating',
    ami_action_id VARCHAR(120),
    ami_channel_id VARCHAR(120),
    asterisk_channel VARCHAR(255),
    failure_reason TEXT,
    started_at TIMESTAMPTZ,
    answered_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_outbound_calls_user_id ON outbound_calls(user_id);
CREATE INDEX IF NOT EXISTS ix_outbound_calls_sip_trunk_id ON outbound_calls(sip_trunk_id);
CREATE INDEX IF NOT EXISTS ix_outbound_calls_destination_number ON outbound_calls(destination_number);
CREATE INDEX IF NOT EXISTS ix_outbound_calls_status ON outbound_calls(status);
CREATE INDEX IF NOT EXISTS ix_outbound_calls_ami_action_id ON outbound_calls(ami_action_id);
CREATE INDEX IF NOT EXISTS ix_outbound_calls_ami_channel_id ON outbound_calls(ami_channel_id);
CREATE INDEX IF NOT EXISTS ix_outbound_calls_created_at ON outbound_calls(created_at);

CREATE TABLE IF NOT EXISTS phone_blacklists (
    id SERIAL PRIMARY KEY,
    normalized_number VARCHAR(32) NOT NULL UNIQUE,
    reason TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_phone_blacklists_normalized_number ON phone_blacklists(normalized_number);
CREATE INDEX IF NOT EXISTS ix_phone_blacklists_enabled ON phone_blacklists(enabled);
CREATE INDEX IF NOT EXISTS ix_phone_blacklists_created_by_user_id ON phone_blacklists(created_by_user_id);

INSERT INTO sip_trunks (name, provider_name, description, host, port, transport, from_user, from_domain, outbound_proxy, caller_id, codecs, enabled, status)
VALUES ('outbound-trunk', 'Carrier SIP trunk', 'Whitelisted SIP carrier endpoint 218.245.102.33:6876, caller ID 02032730801', '218.245.102.33', 6876, 'udp', '02032730801', '218.245.102.33', 'sip:218.245.102.33:6876', '02032730801', 'ulaw,alaw', TRUE, 'active')
ON CONFLICT (name) DO NOTHING;
