import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "debug"])
def test_log_level_accepts_supported_values(level):
    configured = Settings(database_url="postgresql+asyncpg://localhost/test", log_level=level)

    assert configured.log_level == level.upper()


def test_log_level_rejects_unsupported_values():
    with pytest.raises(ValidationError, match="LOG_LEVEL must be"):
        Settings(database_url="postgresql+asyncpg://localhost/test", log_level="production")


@pytest.mark.parametrize(
    ("secret_name", "secret"),
    [
        ("api_key", ""),
        ("api_key", "x" * 31),
        ("api_key", "change_me" + "x" * 32),
        ("admin_api_key", ""),
        ("admin_api_key", "x" * 31),
        ("admin_api_key", "change_me" + "x" * 32),
    ],
)
def test_production_rejects_unsafe_api_secrets(secret_name, secret):
    secrets = {"api_key": "a" * 32, "admin_api_key": "b" * 32}
    secrets[secret_name] = secret

    with pytest.raises(ValidationError, match=secret_name.upper()):
        Settings(
            database_url="postgresql+asyncpg://localhost/test",
            app_env="production",
            **secrets,
        )


def test_production_accepts_strong_api_secrets():
    configured = Settings(
        database_url="postgresql+asyncpg://localhost/test",
        app_env="production",
        api_key="a" * 32,
        admin_api_key="b" * 32,
        brand_api_keys={"c" * 32: 1},
    )

    assert configured.app_env == "production"


def test_production_rejects_unsafe_brand_api_keys():
    with pytest.raises(ValidationError, match="BRAND_API_KEYS entries"):
        Settings(
            database_url="postgresql+asyncpg://localhost/test",
            app_env="production",
            api_key="a" * 32,
            admin_api_key="b" * 32,
            brand_api_keys={"short": 1},
        )


def test_development_allows_short_api_secrets():
    configured = Settings(
        database_url="postgresql+asyncpg://localhost/test",
        app_env="development",
        api_key="short",
        admin_api_key="",
    )

    assert configured.api_key == "short"
