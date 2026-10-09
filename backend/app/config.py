from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Keep deployment settings in environment variables, not source code.
# Test DB is optional for runtime, but tests require a separate database.
# La configuración de despliegue vive en variables de entorno, no en el código.
# La BD de pruebas es opcional en producción; los tests usan una aislada.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str
    sql_echo: bool = False
    test_database_url: str | None = None
    admin_api_key: str = ""
    state_mapping_cache_ttl_seconds: int = Field(default=300, gt=0)


settings = Settings()
