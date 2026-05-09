from datetime import UTC, datetime

import pytest

from app import models
from app.services.asterisk import AmiChannel
from app.services.call_lifecycle import find_active_call_by_destination
from app.services.outbound_dialer import OutboundDialError, originate_with_failover


def test_duplicate_active_destination_is_detected(db_session):
    user = db_session.query(models.AppUser).filter(models.AppUser.username == "admin").first()
    trunk = db_session.query(models.SipTrunk).filter(models.SipTrunk.name == "outbound-trunk").first()
    call = models.OutboundCall(
        user_id=user.id,
        sip_trunk_id=trunk.id,
        destination_number="13800138002",
        status="ringing",
    )
    db_session.add(call)
    db_session.commit()

    active = find_active_call_by_destination(db_session, "13800138002")
    assert active is not None
    assert active.id == call.id


def test_originate_core_flow_with_mock_asterisk(db_session, monkeypatch):
    monkeypatch.setattr("app.services.outbound_dialer.AsteriskAmiClient", FakeAmiClient)
    user = db_session.query(models.AppUser).filter(models.AppUser.username == "admin").first()
    trunk = db_session.query(models.SipTrunk).filter(models.SipTrunk.name == "outbound-trunk").first()
    call = models.OutboundCall(
        user_id=user.id,
        sip_trunk_id=trunk.id,
        destination_number="13800138003",
        caller_id="02032730801",
        status="initiating",
    )
    db_session.add(call)
    db_session.commit()

    used_trunk = originate_with_failover(
        db_session,
        call,
        preferred_trunk=trunk,
        destination="13800138003",
        caller_id="02032730801",
    )
    db_session.commit()
    db_session.refresh(call)

    assert used_trunk.id == trunk.id
    assert call.status == "dialing"
    assert call.ami_action_id
    assert call.ami_channel_id
    assert call.started_at is not None
    assert call.recordings
    assert call.recordings[0].status == "recording"


def test_failover_does_not_retry_same_real_asterisk_endpoint(db_session, monkeypatch):
    AlwaysFailAmiClient.originate_count = 0
    monkeypatch.setattr("app.services.outbound_dialer.AsteriskAmiClient", AlwaysFailAmiClient)
    user = db_session.query(models.AppUser).filter(models.AppUser.username == "admin").first()
    first = db_session.query(models.SipTrunk).filter(models.SipTrunk.name == "outbound-trunk").first()
    second = models.SipTrunk(
        name="same-provider-second-row",
        host="218.245.102.33",
        port=6876,
        transport="udp",
        codecs="ulaw,alaw",
        max_channels=1,
        enabled=True,
        status="active",
    )
    db_session.add(second)
    db_session.flush()
    call = models.OutboundCall(
        user_id=user.id,
        sip_trunk_id=first.id,
        destination_number="13800138004",
        caller_id="02032730801",
        status="initiating",
    )
    db_session.add(call)
    db_session.commit()

    with pytest.raises(OutboundDialError) as exc:
        originate_with_failover(
            db_session,
            call,
            preferred_trunk=first,
            destination="13800138004",
            caller_id="02032730801",
        )

    assert AlwaysFailAmiClient.originate_count == 1
    assert "所有可用 SIP 线路外呼失败" in str(exc.value)


class FakeAmiClient:
    def __init__(self, *args, **kwargs):
        pass

    def command(self, command):
        return "Endpoint: outbound-trunk\nContact: outbound-trunk-aor/sip:218.245.102.33:6876"

    def originate(self, **kwargs):
        return {"Response": "Success"}

    def find_channel_by_id(self, channel_id):
        return AmiChannel(channel="PJSIP/13800138003-00000001", unique_id=channel_id, linked_id=channel_id, state="Up")

    def start_mixmonitor(self, channel, file_path):
        return {"Response": "Success"}


class AlwaysFailAmiClient:
    originate_count = 0

    def __init__(self, *args, **kwargs):
        pass

    def command(self, command):
        return "Endpoint: outbound-trunk\nContact: outbound-trunk-aor/sip:218.245.102.33:6876"

    def originate(self, **kwargs):
        type(self).originate_count += 1
        from app.services.asterisk import AmiError

        raise AmiError("503 Service Unavailable")
