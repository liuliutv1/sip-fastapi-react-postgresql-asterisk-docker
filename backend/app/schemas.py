from datetime import datetime
from ipaddress import ip_network
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.services.phone_numbers import is_valid_phone_number, mask_phone_number, normalize_phone_number

ALLOWED_CODECS = {"ulaw", "alaw", "g729", "opus", "gsm", "g722"}


class AgentCreate(BaseModel):
    extension: str = Field(min_length=2, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)
    status: str = "offline"


class AgentRead(AgentCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    status: str = "draft"


class CampaignRead(CampaignCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CallCreate(BaseModel):
    destination: str = Field(min_length=3, max_length=64)
    campaign_id: int | None = None
    agent_id: int | None = None


class CallRead(BaseModel):
    id: int
    destination: str
    status: str
    campaign_id: int | None = None
    agent_id: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class UserRead(BaseModel):
    id: int
    username: str
    is_active: bool
    is_admin: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class SipTrunkBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider_name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5060, ge=1, le=65535)
    transport: Literal["udp", "tcp", "tls"] = "udp"
    username: str | None = Field(default=None, max_length=120)
    auth_username: str | None = Field(default=None, max_length=120)
    from_user: str | None = Field(default=None, max_length=120)
    from_domain: str | None = Field(default=None, max_length=255)
    outbound_proxy: str | None = Field(default=None, max_length=255)
    caller_id: str | None = Field(default=None, max_length=80)
    codecs: list[str] = Field(default_factory=lambda: ["ulaw", "alaw"], min_length=1, max_length=8)
    max_channels: int = Field(default=30, ge=1, le=10000)
    registration_enabled: bool = False
    enabled: bool = True
    status: Literal["inactive", "active", "error", "disabled"] = "inactive"

    @field_validator("name", "host", "provider_name", "username", "auth_username", "from_user", "from_domain", "outbound_proxy", "caller_id")
    @classmethod
    def strip_string(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("host", "from_domain")
    @classmethod
    def validate_host_like(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if any(char in value for char in ("/", "\\", " ")):
            raise ValueError("must be a host, domain, or IP address without scheme/path")
        return value.lower()

    @field_validator("outbound_proxy")
    @classmethod
    def validate_outbound_proxy(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if " " in value or "\\" in value:
            raise ValueError("must not contain whitespace or backslashes")
        return value

    @field_validator("codecs")
    @classmethod
    def validate_codecs(cls, value: list[str]) -> list[str]:
        normalized = []
        for codec in value:
            item = codec.strip().lower()
            if item not in ALLOWED_CODECS:
                raise ValueError(f"unsupported codec: {codec}")
            if item not in normalized:
                normalized.append(item)
        return normalized


class SipTrunkCreate(SipTrunkBase):
    sip_password: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        validation_alias=AliasChoices("sip_password", "password"),
    )

    model_config = ConfigDict(populate_by_name=True)


class SipTrunkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    transport: Literal["udp", "tcp", "tls"] | None = None
    username: str | None = Field(default=None, max_length=120)
    auth_username: str | None = Field(default=None, max_length=120)
    from_user: str | None = Field(default=None, max_length=120)
    from_domain: str | None = Field(default=None, max_length=255)
    outbound_proxy: str | None = Field(default=None, max_length=255)
    caller_id: str | None = Field(default=None, max_length=80)
    codecs: list[str] | None = Field(default=None, min_length=1, max_length=8)
    max_channels: int | None = Field(default=None, ge=1, le=10000)
    registration_enabled: bool | None = None
    enabled: bool | None = None
    status: Literal["inactive", "active", "error", "disabled"] | None = None
    sip_password: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        validation_alias=AliasChoices("sip_password", "password"),
    )

    model_config = ConfigDict(populate_by_name=True)

    _strip_string = field_validator(
        "name",
        "host",
        "provider_name",
        "username",
        "auth_username",
        "from_user",
        "from_domain",
        "outbound_proxy",
        "caller_id",
    )(SipTrunkBase.strip_string)
    _validate_host_like = field_validator("host", "from_domain")(SipTrunkBase.validate_host_like)
    _validate_outbound_proxy = field_validator("outbound_proxy")(SipTrunkBase.validate_outbound_proxy)
    _validate_codecs = field_validator("codecs")(SipTrunkBase.validate_codecs)

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class SipTrunkRead(SipTrunkBase):
    id: int
    password_configured: bool
    last_health_checked_at: datetime | None = None
    last_health_message: str | None = None
    created_at: datetime
    updated_at: datetime


class SipPeerWhitelistBase(BaseModel):
    sip_trunk_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    peer_cidr: str = Field(min_length=3, max_length=64)
    description: str | None = None
    enabled: bool = True

    @field_validator("name", "peer_cidr")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("peer_cidr")
    @classmethod
    def validate_peer_cidr(cls, value: str) -> str:
        try:
            network = ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError("must be a valid IP address or CIDR range") from exc
        return str(network)


class SipPeerWhitelistCreate(SipPeerWhitelistBase):
    pass


class SipPeerWhitelistUpdate(BaseModel):
    sip_trunk_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    peer_cidr: str | None = Field(default=None, min_length=3, max_length=64)
    description: str | None = None
    enabled: bool | None = None

    _strip_required = field_validator("name", "peer_cidr")(SipPeerWhitelistBase.strip_required)
    _validate_peer_cidr = field_validator("peer_cidr")(SipPeerWhitelistBase.validate_peer_cidr)

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class SipPeerWhitelistRead(SipPeerWhitelistBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuditLogRead(BaseModel):
    id: int
    user_id: int | None = None
    username: str | None = None
    action: str
    resource_type: str
    resource_id: int | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    before_values: dict | None = None
    after_values: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OutboundCallCreate(BaseModel):
    sip_trunk_id: int
    destination_number: str = Field(min_length=3, max_length=32)
    caller_id: str | None = Field(default=None, max_length=80)

    @field_validator("destination_number")
    @classmethod
    def validate_destination_number(cls, value: str) -> str:
        if not is_valid_phone_number(value):
            raise ValueError("must be a valid phone number, for example 13800138000 or +8613800138000")
        return normalize_phone_number(value)

    @field_validator("caller_id")
    @classmethod
    def validate_caller_id(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        stripped = value.strip()
        if not is_valid_phone_number(stripped):
            raise ValueError("caller_id must be a valid phone number")
        return normalize_phone_number(stripped)


class OutboundCallRead(BaseModel):
    id: int
    user_id: int | None = None
    sip_trunk_id: int | None = None
    destination_number: str
    caller_id: str | None = None
    status: str
    ami_action_id: str | None = None
    ami_channel_id: str | None = None
    asterisk_channel: str | None = None
    failure_reason: str | None = None
    hangup_cause: str | None = None
    attempt_count: int = 0
    attempted_trunk_ids: str | None = None
    started_at: datetime | None = None
    answered_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("destination_number", "caller_id")
    def serialize_masked_phone(self, value: str | None):
        return mask_phone_number(value)

    model_config = {"from_attributes": True}


class PhoneBlacklistCreate(BaseModel):
    phone_number: str = Field(min_length=3, max_length=32)
    reason: str | None = None
    enabled: bool = True

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        if not is_valid_phone_number(value):
            raise ValueError("must be a valid phone number")
        return normalize_phone_number(value)


class PhoneBlacklistUpdate(BaseModel):
    phone_number: str | None = Field(default=None, min_length=3, max_length=32)
    reason: str | None = None
    enabled: bool | None = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not is_valid_phone_number(value):
            raise ValueError("must be a valid phone number")
        return normalize_phone_number(value)

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class PhoneBlacklistRead(BaseModel):
    id: int
    normalized_number: str
    reason: str | None = None
    enabled: bool
    created_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("normalized_number")
    def serialize_masked_phone(self, value: str):
        return mask_phone_number(value)

    model_config = {"from_attributes": True}


class CallRecordingRead(BaseModel):
    id: int
    outbound_call_id: int | None = None
    user_id: int | None = None
    destination_number: str
    status: str
    storage_backend: str
    filename: str
    content_type: str
    file_path: str | None = None
    file_size_bytes: int | None = None
    duration_seconds: int | None = None
    retention_expires_at: datetime | None = None
    deleted_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("destination_number")
    def serialize_masked_phone(self, value: str):
        return mask_phone_number(value)

    model_config = {"from_attributes": True}
