from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://cargaexpress:cargaexpress@localhost:5432/cargaexpress"
    sql_echo: bool = False


settings = Settings()
