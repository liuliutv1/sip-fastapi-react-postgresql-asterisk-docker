CREATE TABLE IF NOT EXISTS app_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_app_users_username ON app_users(username);
CREATE INDEX IF NOT EXISTS ix_app_users_is_active ON app_users(is_active);

CREATE TABLE IF NOT EXISTS sip_trunks (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    provider_name VARCHAR(120),
    description TEXT,
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL DEFAULT 5060 CHECK (port >= 1 AND port <= 65535),
    transport VARCHAR(16) NOT NULL DEFAULT 'udp' CHECK (transport IN ('udp', 'tcp', 'tls')),
    username VARCHAR(120),
    auth_username VARCHAR(120),
    password_encrypted TEXT,
    from_user VARCHAR(120),
    from_domain VARCHAR(255),
    outbound_proxy VARCHAR(255),
    caller_id VARCHAR(80),
    codecs VARCHAR(255) NOT NULL DEFAULT 'ulaw,alaw',
    max_channels INTEGER NOT NULL DEFAULT 30 CHECK (max_channels >= 1),
    registration_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'inactive' CHECK (status IN ('inactive', 'active', 'error', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_sip_trunks_name ON sip_trunks(name);
CREATE INDEX IF NOT EXISTS ix_sip_trunks_host ON sip_trunks(host);
CREATE INDEX IF NOT EXISTS ix_sip_trunks_enabled ON sip_trunks(enabled);
CREATE INDEX IF NOT EXISTS ix_sip_trunks_status ON sip_trunks(status);

CREATE TABLE IF NOT EXISTS sip_peer_whitelists (
    id SERIAL PRIMARY KEY,
    sip_trunk_id INTEGER REFERENCES sip_trunks(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL,
    peer_cidr VARCHAR(64) NOT NULL,
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sip_peer_whitelists_trunk_cidr UNIQUE (sip_trunk_id, peer_cidr)
);

CREATE INDEX IF NOT EXISTS ix_sip_peer_whitelists_name ON sip_peer_whitelists(name);
CREATE INDEX IF NOT EXISTS ix_sip_peer_whitelists_peer_cidr ON sip_peer_whitelists(peer_cidr);
CREATE INDEX IF NOT EXISTS ix_sip_peer_whitelists_enabled ON sip_peer_whitelists(enabled);

CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES app_users(id) ON DELETE SET NULL,
    username VARCHAR(80),
    action VARCHAR(64) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id INTEGER,
    ip_address VARCHAR(64),
    user_agent VARCHAR(255),
    before_values JSONB,
    after_values JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_username ON audit_logs(username);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_resource_type ON audit_logs(resource_type);
CREATE INDEX IF NOT EXISTS ix_audit_logs_resource_id ON audit_logs(resource_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs(created_at);
