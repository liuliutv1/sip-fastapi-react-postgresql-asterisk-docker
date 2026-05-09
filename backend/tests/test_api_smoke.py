from pathlib import Path

from app import models


def test_public_health_and_auth_flow(client):
    live = client.get("/api/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123456"})
    assert login.status_code == 200
    payload = login.json()
    assert payload["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_core_api_crud_smoke(client, auth_headers, monkeypatch, db_session, tmp_path):
    monkeypatch.setattr("app.api.system._ami_command", lambda command: _fake_ami_command(command))
    monkeypatch.setattr("app.api.system._udp_options_probe", lambda host, port: ("ok", f"{host}:{port}/udp 可探测"))
    monkeypatch.setattr("app.api.outbound_calls.originate_with_failover", _fake_originate)
    monkeypatch.setattr("app.api.outbound_calls.AsteriskAmiClient", FakeAmiClient)

    agent = client.post("/api/agents", json={"extension": "6002", "display_name": "测试坐席", "status": "available"})
    assert agent.status_code == 201
    assert client.get("/api/agents").status_code == 200

    campaign = client.post("/api/campaigns", json={"name": "测试批次", "status": "active"})
    assert campaign.status_code == 201
    assert client.get("/api/campaigns").status_code == 200

    call_record = client.post("/api/calls", json={"destination": "13800138000"})
    assert call_record.status_code == 201
    assert client.get("/api/calls").status_code == 200

    trunk_payload = {
        "name": "test-trunk",
        "provider_name": "测试运营商",
        "host": "218.245.102.33",
        "port": 6876,
        "transport": "udp",
        "codecs": ["ulaw", "alaw"],
        "max_channels": 1,
        "enabled": True,
        "status": "active",
    }
    trunk = client.post("/api/sip-trunks", json=trunk_payload, headers=auth_headers)
    assert trunk.status_code == 201
    trunk_id = trunk.json()["id"]
    assert client.get("/api/sip-trunks", headers=auth_headers).status_code == 200
    assert client.get(f"/api/sip-trunks/{trunk_id}", headers=auth_headers).status_code == 200
    assert client.patch(f"/api/sip-trunks/{trunk_id}", json={"description": "updated"}, headers=auth_headers).status_code == 200

    whitelist = client.post(
        "/api/sip-peer-whitelists",
        json={"sip_trunk_id": trunk_id, "name": "供应商", "peer_cidr": "218.245.102.33/32", "enabled": True},
        headers=auth_headers,
    )
    assert whitelist.status_code == 201
    whitelist_id = whitelist.json()["id"]
    assert client.get("/api/sip-peer-whitelists", headers=auth_headers).status_code == 200
    assert client.patch(f"/api/sip-peer-whitelists/{whitelist_id}", json={"description": "updated"}, headers=auth_headers).status_code == 200

    blacklist = client.post("/api/phone-blacklists", json={"phone_number": "13900139000", "reason": "测试"}, headers=auth_headers)
    assert blacklist.status_code == 201
    blacklist_id = blacklist.json()["id"]
    assert client.get("/api/phone-blacklists", headers=auth_headers).status_code == 200
    assert client.patch(f"/api/phone-blacklists/{blacklist_id}", json={"reason": "updated"}, headers=auth_headers).status_code == 200

    outbound = client.post(
        "/api/outbound-calls",
        json={"sip_trunk_id": trunk_id, "destination_number": "13800138001", "caller_id": "02032730801"},
        headers=auth_headers,
    )
    assert outbound.status_code == 201
    outbound_id = outbound.json()["id"]
    assert client.get("/api/outbound-calls", headers=auth_headers).status_code == 200
    assert client.post(f"/api/outbound-calls/{outbound_id}/refresh", headers=auth_headers).status_code == 200
    assert client.post(f"/api/outbound-calls/{outbound_id}/hangup", headers=auth_headers).status_code == 200

    recording_path = tmp_path / "recording.wav"
    recording_path.write_bytes(b"RIFF0000WAVE")
    user = db_session.query(models.AppUser).filter(models.AppUser.username == "admin").first()
    recording = models.CallRecording(
        outbound_call_id=outbound_id,
        user_id=user.id,
        destination_number="13800138001",
        status="completed",
        storage_backend="local",
        filename="recording.wav",
        content_type="audio/wav",
        local_path=str(recording_path),
        file_path=str(recording_path),
        file_size_bytes=recording_path.stat().st_size,
    )
    db_session.add(recording)
    db_session.commit()

    recordings = client.get("/api/call-recordings", headers=auth_headers)
    assert recordings.status_code == 200
    assert client.get(f"/api/call-recordings/{recording.id}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/call-recordings/{recording.id}/play", headers=auth_headers).status_code == 200
    assert client.get(f"/api/call-recordings/{recording.id}/download", headers=auth_headers).status_code == 200
    assert client.post("/api/call-recordings/retention/purge", headers=auth_headers).status_code == 200

    system_check = client.get("/api/system/check", headers=auth_headers)
    assert system_check.status_code == 200
    assert all({"item", "status", "msg"} <= set(item) for item in system_check.json())

    audit_logs = client.get("/api/audit-logs?limit=50", headers=auth_headers)
    assert audit_logs.status_code == 200

    assert client.delete(f"/api/call-recordings/{recording.id}", headers=auth_headers).status_code == 200
    assert client.delete(f"/api/phone-blacklists/{blacklist_id}", headers=auth_headers).status_code == 204
    assert client.delete(f"/api/sip-peer-whitelists/{whitelist_id}", headers=auth_headers).status_code == 204
    assert client.delete(f"/api/sip-trunks/{trunk_id}", headers=auth_headers).status_code == 204


def _fake_ami_command(command: str) -> str:
    if "core show uptime" in command:
        return "System uptime: 1 minute"
    if "pjsip show transports" in command:
        return "transport-udp 0.0.0.0:5060"
    if "pjsip show endpoint" in command:
        return "Endpoint: outbound-trunk\nContact: outbound-trunk-aor/sip:218.245.102.33:6876"
    if "pjsip show contacts" in command:
        return "outbound-trunk-aor/sip:218.245.102.33:6876 NonQual"
    if "pjsip show registrations" in command:
        return "No objects found."
    if "dialplan show outbound" in command:
        return "Dial(PJSIP/${EXTEN}@outbound-trunk,30)"
    return ""


def _fake_originate(db, call, *, preferred_trunk, destination, caller_id=None):
    call.status = "dialing"
    call.sip_trunk_id = preferred_trunk.id
    call.ami_action_id = "test-action"
    call.ami_channel_id = "test-channel"
    call.caller_id = caller_id
    db.flush()
    return preferred_trunk


class FakeAmiClient:
    def __init__(self, *args, **kwargs):
        pass

    def find_channel_by_id(self, channel_id):
        return None
