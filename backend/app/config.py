from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str
    sql_echo: bool = False
    admin_api_key: str = ""
    state_mapping_cache_ttl_seconds: int = Field(default=300, gt=0)


settings = Settings()
