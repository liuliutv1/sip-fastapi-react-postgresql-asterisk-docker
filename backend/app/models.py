from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")
    outbound_calls: Mapped[list["OutboundCall"]] = relationship(back_populates="user")
    phone_blacklists: Mapped[list["PhoneBlacklist"]] = relationship(back_populates="created_by_user")
    call_recordings: Mapped[list["CallRecording"]] = relationship(back_populates="user", foreign_keys="CallRecording.user_id")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    extension: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32), default="offline", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    calls: Mapped[list["CallRecord"]] = relationship(back_populates="agent")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    calls: Mapped[list["CallRecord"]] = relationship(back_populates="campaign")


class CallRecord(Base):
    __tablename__ = "call_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    destination: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped[Campaign | None] = relationship(back_populates="calls")
    agent: Mapped[Agent | None] = relationship(back_populates="calls")


class SipTrunk(Base):
    __tablename__ = "sip_trunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    host: Mapped[str] = mapped_column(String(255), index=True)
    port: Mapped[int] = mapped_column(Integer, default=5060)
    transport: Mapped[str] = mapped_column(String(16), default="udp")
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    auth_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_user: Mapped[str | None] = mapped_column(String(120), nullable=True)
    from_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outbound_proxy: Mapped[str | None] = mapped_column(String(255), nullable=True)
    caller_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    codecs: Mapped[str] = mapped_column(String(255), default="ulaw,alaw")
    max_channels: Mapped[int] = mapped_column(Integer, default=30)
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="inactive", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    peer_whitelists: Mapped[list["SipPeerWhitelist"]] = relationship(back_populates="sip_trunk")
    outbound_calls: Mapped[list["OutboundCall"]] = relationship(back_populates="sip_trunk")


class SipPeerWhitelist(Base):
    __tablename__ = "sip_peer_whitelists"
    __table_args__ = (UniqueConstraint("sip_trunk_id", "peer_cidr", name="uq_sip_peer_whitelists_trunk_cidr"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sip_trunk_id: Mapped[int | None] = mapped_column(ForeignKey("sip_trunks.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    peer_cidr: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    sip_trunk: Mapped[SipTrunk | None] = relationship(back_populates="peer_whitelists")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(80), index=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    before_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped[AppUser | None] = relationship(back_populates="audit_logs")


class OutboundCall(Base):
    __tablename__ = "outbound_calls"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True, index=True)
    sip_trunk_id: Mapped[int | None] = mapped_column(ForeignKey("sip_trunks.id", ondelete="SET NULL"), nullable=True, index=True)
    destination_number: Mapped[str] = mapped_column(String(32), index=True)
    caller_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="initiating", index=True)
    ami_action_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    ami_channel_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    asterisk_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[AppUser | None] = relationship(back_populates="outbound_calls")
    sip_trunk: Mapped[SipTrunk | None] = relationship(back_populates="outbound_calls")
    recordings: Mapped[list["CallRecording"]] = relationship(back_populates="outbound_call")


class PhoneBlacklist(Base):
    __tablename__ = "phone_blacklists"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    normalized_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by_user: Mapped[AppUser | None] = relationship(back_populates="phone_blacklists")


class CallRecording(Base):
    __tablename__ = "call_recordings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    outbound_call_id: Mapped[int | None] = mapped_column(ForeignKey("outbound_calls.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True, index=True)
    destination_number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    storage_backend: Mapped[str] = mapped_column(String(32), default="local", index=True)
    filename: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    content_type: Mapped[str] = mapped_column(String(80), default="audio/wav")
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    asterisk_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    oss_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    outbound_call: Mapped[OutboundCall | None] = relationship(back_populates="recordings")
    user: Mapped[AppUser | None] = relationship(back_populates="call_recordings", foreign_keys=[user_id])
    deleted_by_user: Mapped[AppUser | None] = relationship(foreign_keys=[deleted_by_user_id])
