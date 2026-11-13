"""Drop and re-seed the demo database: `python -m app.db.reset`. Refuses to run in production."""

import sys

from app.core.config import get_settings
from app.db.session import reset_database

if __name__ == "__main__":
    settings = get_settings()
    if settings.environment == "production":
        sys.exit("Refusing to reset: DATAHUB_ENVIRONMENT=production. This drops every table.")
    reset_database()
    print(f"Database reset and seeded: {settings.database_url}")
