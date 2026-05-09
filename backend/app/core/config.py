from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Mini SIP Outbound Call Center"
    app_version: str = "V1.001"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://callcenter:callcenter@postgres:5432/callcenter"
    cors_origins: str = "http://localhost:3000,http://localhost:8080"
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    admin_username: str = "admin"
    admin_password: str = "admin123456"
    sip_password_encryption_key: str = "change-me-sip-password-encryption-key"

    asterisk_sip_port: int = 5060
    asterisk_rtp_start: int = 10000
    asterisk_rtp_end: int = 10020
    asterisk_ami_host: str = "asterisk"
    asterisk_ami_port: int = 5038
    asterisk_ami_username: str = "callcenter"
    asterisk_ami_password: str = "callcenter"
    asterisk_ami_event_listener_enabled: bool = True
    asterisk_originate_timeout_ms: int = 30000
    asterisk_outbound_hold_seconds: int = 7200
    sip_trunk_health_check_enabled: bool = True
    sip_trunk_health_check_interval_seconds: int = 60
    sip_vendor_ip: str = "218.245.102.33"
    sip_vendor_port: int = 6876
    sip_trunk_name: str = "outbound-trunk"
    manual_outbound_rate_limit_count: int = 5
    manual_outbound_rate_limit_window_seconds: int = 60
    recordings_local_dir: str = "/recordings"
    asterisk_recordings_dir: str = "/recordings"
    recordings_storage_backend: str = "local"
    recording_retention_days: int = 90
    aliyun_oss_endpoint: str = ""
    aliyun_oss_bucket: str = ""
    aliyun_oss_access_key_id: str = ""
    aliyun_oss_access_key_secret: str = ""
    aliyun_oss_prefix: str = "sip-call-recordings"
    aliyun_oss_signed_url_expire_seconds: int = 300

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
