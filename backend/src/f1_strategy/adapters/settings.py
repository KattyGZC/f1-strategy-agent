from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings


class PostgresSettings(BaseSettings):
    postgres_uri: SecretStr
    postgres_connect_timeout_s: int = Field(gt=0)


class Settings(PostgresSettings):
    mongo_uri: SecretStr
    mongo_database: str = Field(min_length=1)
    openf1_base_url: HttpUrl
    openf1_requests_per_second: int = Field(gt=0)
    openf1_requests_per_minute: int = Field(gt=0)
    openf1_max_concurrency: int = Field(gt=0)
    openf1_max_attempts: int = Field(gt=0)
    openf1_backoff_base_s: float = Field(gt=0)
    openf1_timeout_s: float = Field(gt=0)
    session_settle_h: int = Field(ge=0)
    telemetry_window_min: int = Field(gt=0)
    transform_max_concurrency: int = Field(gt=0)
    transform_max_attempts: int = Field(gt=0)
    transform_backoff_base_s: float = Field(gt=0)


class ApiSettings(PostgresSettings):
    postgres_pool_size: int = Field(gt=0)
    redis_uri: SecretStr
    redis_max_connections: int = Field(gt=0)
    redis_timeout_s: float = Field(gt=0)
    replay_max_active: int = Field(gt=0)
    replay_idle_ttl_s: int = Field(gt=0)
    replay_tick_s: float = Field(gt=0)
    replay_lease_s: float = Field(gt=0)
