from app import models
from app.services.ami_event_listener import AmiHangupEventListener


def test_hangup_event_backfills_call_and_recording(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.call_lifecycle.upload_to_oss_if_enabled", lambda recording: None)
    user = db_session.query(models.AppUser).filter(models.AppUser.username == "admin").first()
    trunk = db_session.query(models.SipTrunk).filter(models.SipTrunk.name == "outbound-trunk").first()
    recording_path = tmp_path / "hangup.wav"
    recording_path.write_bytes(b"RIFF0000WAVE")

    call = models.OutboundCall(
        user_id=user.id,
        sip_trunk_id=trunk.id,
        destination_number="13800138005",
        status="in_progress",
        ami_channel_id="ami-unique-1",
        asterisk_channel="PJSIP/13800138005-00000001",
    )
    db_session.add(call)
    db_session.flush()
    recording = models.CallRecording(
        outbound_call_id=call.id,
        user_id=user.id,
        destination_number=call.destination_number,
        status="recording",
        storage_backend="local",
        filename="hangup.wav",
        content_type="audio/wav",
        local_path=str(recording_path),
        file_path=str(recording_path),
    )
    db_session.add(recording)
    db_session.commit()

    listener = AmiHangupEventListener()
    listener._handle_hangup_event(
        {
            "Event": "Hangup",
            "Channel": "PJSIP/13800138005-00000001",
            "Uniqueid": "ami-unique-1",
            "Linkedid": "ami-unique-1",
            "Cause": "16",
            "Cause-txt": "Normal Clearing",
        }
    )

    db_session.expire_all()
    refreshed_call = db_session.get(models.OutboundCall, call.id)
    refreshed_recording = db_session.get(models.CallRecording, recording.id)
    assert refreshed_call.status == "completed"
    assert refreshed_call.ended_at is not None
    assert refreshed_call.hangup_cause == "16 Normal Clearing"
    assert refreshed_recording.status == "completed"
    assert refreshed_recording.file_size_bytes == recording_path.stat().st_size
