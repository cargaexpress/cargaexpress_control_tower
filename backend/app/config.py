from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Keep deployment settings in environment variables, not source code.
# The project can be started from either the repo root or backend/, so support both.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(PROJECT_ROOT / ".env"), str(PROJECT_ROOT / "backend" / ".env")],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = (
        "postgresql+asyncpg://cargaexpress:change_me_local_only@localhost:5432/cargaexpress"
    )
    sql_echo: bool = False
    test_database_url: str | None = (
        "postgresql+asyncpg://cargaexpress:change_me_local_only@localhost:5432/cargaexpress_test"
    )
    admin_api_key: str = ""
    api_key: str = ""
    brand_api_keys: dict[str, int] = Field(default_factory=dict)
    log_level: str = "INFO"
    state_mapping_cache_ttl_seconds: int = Field(default=300, gt=0)

    # Type A Simulator Configuration (F3 / Webhook Receiver Extractor)
    type_a_simulator_url: str = "http://localhost:9000"
    type_a_max_retries: int = 3
    type_a_retry_base_delay_seconds: float = 0.5

    # Type B Carriers API Configuration (F4)
    type_b_carriers_urls: dict[str, str] = Field(
        default_factory=lambda: {
            "SimCarrier A": "http://localhost:8001",
            "SimCarrier B": "http://localhost:8002",
            "SimCarrier C": "http://localhost:8003",
            "SimCarrier D": "http://localhost:8004",
        }
    )
    type_b_max_retries: int = 3
    type_b_retry_base_delay_seconds: float = 0.5

    # RabbitMQ Message Broker Configuration (RNF-01 / Webhook Queue)
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_exchange: str = "eventos_exchange"
    rabbitmq_queue: str = "eventos_transportadora"
    rabbitmq_retry_queue: str = "eventos_transportadora.retry"
    rabbitmq_dlq_queue: str = "eventos_transportadora.dlq"
    rabbitmq_retry_ttl_ms: int = 5000
    rabbitmq_max_retries: int = 3
    rabbitmq_prefetch_count: int = 10

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return normalized

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env.strip().lower() == "production":
            for name, value in (
                ("API_KEY", self.api_key),
                ("ADMIN_API_KEY", self.admin_api_key),
            ):
                if len(value) < 32 or value.lower().startswith("change_me"):
                    raise ValueError(
                        f"{name} must be at least 32 characters and must not start with 'change_me' in production"
                    )
            if any(
                len(api_key) < 32 or api_key.lower().startswith("change_me")
                for api_key in self.brand_api_keys
            ):
                raise ValueError(
                    "BRAND_API_KEYS entries must be at least 32 characters and must not start with "
                    "'change_me' in production"
                )
        return self


settings = Settings()
