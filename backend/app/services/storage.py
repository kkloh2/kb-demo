"""Local-disk file storage for uploaded documents (swap for an object store in production)."""

import re
from pathlib import Path, PurePath

from app.core.config import get_settings


def safe_filename(name: str) -> str:
    """Keep the base name only, with safe characters; never empty."""
    base = PurePath(name.replace("\\", "/")).name.strip()
    base = re.sub(r"[^\w.\- ()]+", "_", base)[:200].strip(" .")
    return base or "file"


def save(kb_id: str, document_id: int, filename: str, data: bytes) -> str:
    """Write the file and return its path relative to the upload directory."""
    rel = Path(kb_id) / f"{document_id}-{filename}"
    path = get_settings().upload_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel.as_posix()


def resolve(rel: str) -> Path | None:
    """Absolute path for a stored file, or None if missing or outside the upload directory."""
    root = get_settings().upload_dir.resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def delete(rel: str | None) -> None:
    if rel and (path := resolve(rel)):
        path.unlink(missing_ok=True)
