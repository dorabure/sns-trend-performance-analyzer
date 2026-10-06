import os
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import URL


@dataclass(frozen=True)
class Settings:
    database_url: URL
    frontend_origin: str
    max_import_file_size_bytes: int = 20971520
    max_import_request_size_bytes: int = 22020096


@lru_cache
def get_settings() -> Settings:
    limit = int(os.environ.get("MAX_IMPORT_FILE_SIZE_BYTES", "20971520"))
    if limit <= 0:
        raise ValueError("MAX_IMPORT_FILE_SIZE_BYTES must be positive")
    request_limit = int(os.environ.get("MAX_IMPORT_REQUEST_SIZE_BYTES", str(limit + 1048576)))
    if request_limit <= 0:
        raise ValueError("MAX_IMPORT_REQUEST_SIZE_BYTES must be positive")
    # URL.create safely handles passwords containing URL-reserved characters.
    return Settings(
        database_url=URL.create(
            "postgresql+psycopg",
            username=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ.get("POSTGRES_HOST", "db"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            database=os.environ["POSTGRES_DB"],
        ),
        frontend_origin=os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000"),
        max_import_file_size_bytes=limit,
        max_import_request_size_bytes=request_limit,
    )
