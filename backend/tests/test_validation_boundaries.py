def test_outbound_call_rejects_invalid_phone(client, auth_headers):
    trunks = client.get("/api/sip-trunks", headers=auth_headers).json()
    trunk_id = next(item["id"] for item in trunks if item["name"] == "outbound-trunk")

    response = client.post(
        "/api/outbound-calls",
        json={"sip_trunk_id": trunk_id, "destination_number": "abc", "caller_id": "02032730801"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_sip_trunk_rejects_invalid_port_and_codec(client, auth_headers):
    invalid_port = client.post(
        "/api/sip-trunks",
        json={
            "name": "bad-port",
            "host": "218.245.102.33",
            "port": 70000,
            "transport": "udp",
            "codecs": ["ulaw"],
        },
        headers=auth_headers,
    )
    assert invalid_port.status_code == 422

    invalid_codec = client.post(
        "/api/sip-trunks",
        json={
            "name": "bad-codec",
            "host": "218.245.102.33",
            "port": 6876,
            "transport": "udp",
            "codecs": ["not-a-codec"],
        },
        headers=auth_headers,
    )
    assert invalid_codec.status_code == 422


def test_blacklist_rejects_invalid_phone(client, auth_headers):
    response = client.post(
        "/api/phone-blacklists",
        json={"phone_number": "not-phone", "reason": "invalid"},
        headers=auth_headers,
    )
    assert response.status_code == 422
