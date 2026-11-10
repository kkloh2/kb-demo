"""Drop and re-seed the demo database: `python -m app.db.reset`."""

from app.core.config import get_settings
from app.db.session import reset_database

if __name__ == "__main__":
    reset_database()
    print(f"Database reset and seeded: {get_settings().database_url}")
