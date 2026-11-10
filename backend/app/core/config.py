from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEV_JWT_SECRET = "dev-only-secret-change-me-32-bytes-min"


class Settings(BaseSettings):
    """All settings can be overridden with DATAHUB_* environment variables or backend/.env."""

    model_config = SettingsConfigDict(env_prefix="DATAHUB_", env_file=".env", extra="ignore")

    app_name: str = "Data Hub API"
    environment: Literal["development", "test", "production"] = "development"

    # Database (SQLite for the demo; any SQLAlchemy URL works)
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'datahub.db'}"
    seed_demo_data: bool = True

    # Tokens
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "data-hub"
    jwt_audience: str = "data-hub-api"
    access_token_minutes: int = 60

    # Sign-in directory: a YAML stand-in for LDAP / Active Directory for now.
    # Password policy and account lockout are the directory's job, not Data Hub's.
    ldap_directory_file: Path = BACKEND_DIR / "ldap-directory.yaml"

    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="after")
    def _require_real_secret_outside_dev(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "DATAHUB_JWT_SECRET must be set to a random value of at least 32 characters "
                "when DATAHUB_ENVIRONMENT=production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
