from app.services.deployment_validation import DeploymentValidationCheck, DeploymentValidationReport


def test_system_check_response_format(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.api.system._ami_command", lambda command: _fake_ami_command(command))
    monkeypatch.setattr("app.api.system._udp_options_probe", lambda host, port: ("ok", "UDP 探测成功"))

    response = client.get("/api/system/check", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    for item in payload:
        assert set(item) == {"item", "status", "msg"}
        assert item["status"] in {"ok", "warn", "fail"}


def test_deployment_validation_api_blocks_failures(client, auth_headers, monkeypatch):
    report = DeploymentValidationReport(
        status="fail",
        version="V-test",
        generated_at="2026-05-09T00:00:00Z",
        checks=[
            DeploymentValidationCheck(item="调用正常", status="fail", msg="Asterisk endpoint 缺失"),
            DeploymentValidationCheck(item="未产生重复呼叫", status="ok", msg="正常"),
        ],
    )
    monkeypatch.setattr("app.api.system.run_deployment_validation", lambda db: report)

    response = client.post("/api/system/validate-deployment", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "fail"
    assert payload["checks"][0]["item"] == "调用正常"
    assert payload["checks"][0]["status"] == "fail"


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
