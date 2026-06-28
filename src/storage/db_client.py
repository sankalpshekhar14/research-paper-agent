"""SQLite database client for paper metadata."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.config import settings


class SQLiteDatabaseClient:
    """SQLite-backed client for persisting paper metadata."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the papers table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    abstract TEXT,
                    published_date TIMESTAMP,
                    updated_date TIMESTAMP,
                    categories TEXT,
                    pdf_url TEXT,
                    filepath TEXT,
                    version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def store_paper_metadata(self, paper_metadata: Dict[str, Any]) -> None:
        """Insert or replace paper metadata in the database."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO papers
                (id, title, abstract, published_date, updated_date, categories,
                 pdf_url, filepath, version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_metadata["id"],
                    paper_metadata.get("title"),
                    paper_metadata.get("abstract"),
                    paper_metadata.get("published"),
                    paper_metadata.get("updated"),
                    ",".join(paper_metadata.get("categories", [])),
                    paper_metadata.get("pdf_url"),
                    paper_metadata.get("local_pdf_path"),
                    paper_metadata.get("version"),
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()

    def paper_exists(self, arxiv_id: str) -> bool:
        """Return True if a paper with the given arXiv ID already exists."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM papers WHERE id = ? LIMIT 1", (arxiv_id,)
            )
            return cursor.fetchone() is not None

    def get_paper_by_id(self, arxiv_id: str) -> Dict[str, Any] | None:
        """Fetch a single paper record by its arXiv ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM papers WHERE id = ?", (arxiv_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)


# Singleton accessor — modules should call ``get_db_client()`` rather than
# constructing clients directly so you can swap the implementation centrally.
_db_client: SQLiteDatabaseClient = SQLiteDatabaseClient()


def get_db_client() -> SQLiteDatabaseClient:
    return _db_client


def set_db_client(client: SQLiteDatabaseClient) -> None:
    global _db_client
    _db_client = client
