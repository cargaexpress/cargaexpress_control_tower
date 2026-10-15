from pathlib import Path

from pydantic import Field
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
    database_url: str
    sql_echo: bool = False
    test_database_url: str | None = None
    admin_api_key: str = ""
    api_key: str = ""
    state_mapping_cache_ttl_seconds: int = Field(default=300, gt=0)


settings = Settings()
