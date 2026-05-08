INSERT INTO sip_trunks (
    name,
    provider_name,
    description,
    host,
    port,
    transport,
    from_user,
    from_domain,
    outbound_proxy,
    caller_id,
    codecs,
    enabled,
    status
)
VALUES (
    'outbound-trunk',
    'Carrier SIP trunk',
    'Whitelisted SIP carrier endpoint 218.245.102.33:6876, caller ID 02032730801',
    '218.245.102.33',
    6876,
    'udp',
    '02032730801',
    '218.245.102.33',
    'sip:218.245.102.33:6876',
    '02032730801',
    'ulaw,alaw',
    TRUE,
    'active'
)
ON CONFLICT (name) DO UPDATE SET
    provider_name = EXCLUDED.provider_name,
    description = EXCLUDED.description,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    transport = EXCLUDED.transport,
    from_user = EXCLUDED.from_user,
    from_domain = EXCLUDED.from_domain,
    outbound_proxy = EXCLUDED.outbound_proxy,
    caller_id = EXCLUDED.caller_id,
    codecs = EXCLUDED.codecs,
    enabled = EXCLUDED.enabled,
    status = EXCLUDED.status,
    updated_at = NOW();

INSERT INTO sip_peer_whitelists (sip_trunk_id, name, peer_cidr, description, enabled)
SELECT id, 'Carrier SBC 218.245.102.33', '218.245.102.33/32', 'Carrier SIP peer IP provided for whitelist access', TRUE
FROM sip_trunks
WHERE name = 'outbound-trunk'
ON CONFLICT (sip_trunk_id, peer_cidr) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();
