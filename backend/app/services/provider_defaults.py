from sqlalchemy.orm import Session

from app import models

CARRIER_TRUNK_NAME = "outbound-trunk"
CARRIER_PROVIDER_NAME = "Carrier SIP trunk"
CARRIER_HOST = "218.245.102.33"
CARRIER_PORT = 6876
CARRIER_CALLER_ID = "02032730801"
CARRIER_DESCRIPTION = "Whitelisted SIP carrier endpoint 218.245.102.33:6876, caller ID 02032730801"
CARRIER_OUTBOUND_PROXY = "sip:218.245.102.33:6876"


def ensure_carrier_sip_trunk(db: Session) -> None:
    trunk = db.query(models.SipTrunk).filter(models.SipTrunk.name == CARRIER_TRUNK_NAME).first()
    if trunk is None:
        trunk = models.SipTrunk(
            name=CARRIER_TRUNK_NAME,
            host=CARRIER_HOST,
            port=CARRIER_PORT,
            codecs="ulaw,alaw",
        )
        db.add(trunk)

    trunk.provider_name = CARRIER_PROVIDER_NAME
    trunk.description = CARRIER_DESCRIPTION
    trunk.host = CARRIER_HOST
    trunk.port = CARRIER_PORT
    trunk.transport = "udp"
    trunk.from_user = CARRIER_CALLER_ID
    trunk.from_domain = CARRIER_HOST
    trunk.outbound_proxy = CARRIER_OUTBOUND_PROXY
    trunk.caller_id = CARRIER_CALLER_ID
    trunk.codecs = "ulaw,alaw"
    trunk.registration_enabled = False
    trunk.enabled = True
    trunk.status = "active"
    db.flush()

    whitelist = (
        db.query(models.SipPeerWhitelist)
        .filter(
            models.SipPeerWhitelist.sip_trunk_id == trunk.id,
            models.SipPeerWhitelist.peer_cidr == f"{CARRIER_HOST}/32",
        )
        .first()
    )
    if whitelist is None:
        whitelist = models.SipPeerWhitelist(
            sip_trunk_id=trunk.id,
            peer_cidr=f"{CARRIER_HOST}/32",
        )
        db.add(whitelist)

    whitelist.name = f"Carrier SBC {CARRIER_HOST}"
    whitelist.description = "Carrier SIP peer IP provided for whitelist access"
    whitelist.enabled = True

    db.commit()
