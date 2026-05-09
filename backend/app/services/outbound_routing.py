from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app import models
from app.services.call_lifecycle import ACTIVE_CALL_STATUSES


def active_call_count_for_trunk(db: Session, trunk_id: int, *, exclude_call_id: int | None = None) -> int:
    query = db.query(func.count(models.OutboundCall.id)).filter(
        models.OutboundCall.sip_trunk_id == trunk_id,
        models.OutboundCall.status.in_(ACTIVE_CALL_STATUSES),
    )
    if exclude_call_id is not None:
        query = query.filter(models.OutboundCall.id != exclude_call_id)
    count = query.scalar()
    return int(count or 0)


def trunk_has_capacity(db: Session, trunk: models.SipTrunk, *, exclude_call_id: int | None = None) -> bool:
    max_channels = max(int(trunk.max_channels or 1), 1)
    return active_call_count_for_trunk(db, trunk.id, exclude_call_id=exclude_call_id) < max_channels


def attempted_trunk_ids(call: models.OutboundCall) -> set[int]:
    if not call.attempted_trunk_ids:
        return set()
    values: set[int] = set()
    for item in call.attempted_trunk_ids.split(","):
        item = item.strip()
        if item.isdigit():
            values.add(int(item))
    return values


def mark_trunk_attempt(call: models.OutboundCall, trunk: models.SipTrunk) -> None:
    attempted = attempted_trunk_ids(call)
    attempted.add(trunk.id)
    call.attempted_trunk_ids = ",".join(str(item) for item in sorted(attempted))
    call.attempt_count = len(attempted)


def candidate_trunks(
    db: Session,
    *,
    preferred_trunk: models.SipTrunk | None = None,
    exclude_ids: set[int] | None = None,
    current_call_id: int | None = None,
) -> list[models.SipTrunk]:
    exclude_ids = exclude_ids or set()
    health_order = case(
        (models.SipTrunk.status == "active", 0),
        (models.SipTrunk.status == "inactive", 1),
        else_=2,
    )
    trunks = (
        db.query(models.SipTrunk)
        .filter(
            models.SipTrunk.enabled.is_(True),
            models.SipTrunk.status != "error",
        )
        .order_by(health_order, models.SipTrunk.id.asc())
        .all()
    )

    ordered: list[models.SipTrunk] = []
    if preferred_trunk and preferred_trunk.enabled and preferred_trunk.status != "error":
        ordered.append(preferred_trunk)
    ordered.extend(trunk for trunk in trunks if trunk.id not in {item.id for item in ordered})

    return [
        trunk
        for trunk in ordered
        if trunk.id not in exclude_ids and trunk_has_capacity(db, trunk, exclude_call_id=current_call_id)
    ]
