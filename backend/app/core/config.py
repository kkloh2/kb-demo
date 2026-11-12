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

    # Sign-in directory (see app/auth/ldap.py). Password policy and account lockout are the
    # directory's job, not Data Hub's.
    #   "yaml": a local file stands in for the directory (demo and tests)
    #   "ldap": a real LDAP / Active Directory server, through ldap3
    directory: Literal["yaml", "ldap"] = "yaml"
    ldap_directory_file: Path = BACKEND_DIR / "ldap-directory.yaml"  # for directory="yaml"

    # For directory="ldap". Sign-in binds as the person, with their own LAN ID and password, then
    # reads their own entry; no service account is needed.
    ldap_server_url: str = ""  # e.g. "ldaps://ad.corp.example.com" (ldaps:// or start TLS outside dev)
    ldap_start_tls: bool = False  # upgrade an ldap:// connection to TLS before binding
    ldap_ca_certs_file: Path | None = None  # CA bundle for the server certificate; None = system CAs
    ldap_bind_format: str = "{lan_id}"  # e.g. "{lan_id}@corp.example.com" or "CORP\\{lan_id}"
    ldap_search_base: str = ""  # e.g. "DC=corp,DC=example,DC=com"
    ldap_search_filter: str = "(sAMAccountName={lan_id})"  # {lan_id} is escaped
    ldap_timeout_seconds: int = 5
    # Directory attribute holding each detail Data Hub keeps (Active Directory names by default).
    ldap_attribute_display_name: str = "displayName"
    ldap_attribute_email: str = "mail"
    ldap_attribute_department: str = "department"
    ldap_attribute_title: str = "title"

    # LAN IDs made system admins at start-up when nobody holds SYSTEM_ADMIN (how the first one gets in).
    bootstrap_system_admins: list[str] = ["admin"]

    # Document uploads (local disk for now). Files go under upload_dir/doc-repos/<doc-repo id>/.
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    max_upload_mb: int = 25  # per file
    max_files_per_upload: int = 200
    allowed_upload_extensions: list[str] = [
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".csv", ".txt", ".md",
    ]

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

    @model_validator(mode="after")
    def _require_complete_ldap_settings(self) -> "Settings":
        if self.directory != "ldap":
            return self
        missing = [name for name in ("ldap_server_url", "ldap_search_base") if not getattr(self, name)]
        if missing:
            raise ValueError(f"DATAHUB_DIRECTORY=ldap needs {', '.join('DATAHUB_' + m.upper() for m in missing)}.")
        if "{lan_id}" not in self.ldap_bind_format or "{lan_id}" not in self.ldap_search_filter:
            raise ValueError("DATAHUB_LDAP_BIND_FORMAT and DATAHUB_LDAP_SEARCH_FILTER must contain {lan_id}.")
        plain = self.ldap_server_url.lower().startswith("ldap://") and not self.ldap_start_tls
        if plain and self.environment == "production":
            raise ValueError(
                "Passwords would cross the network unencrypted: use an ldaps:// DATAHUB_LDAP_SERVER_URL "
                "or set DATAHUB_LDAP_START_TLS=true."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
