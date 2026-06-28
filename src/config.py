from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Celery / message broker
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # Local storage for downloaded PDFs
    PAPERS_STORAGE_PATH: Path = Path("/Volumes/Extreme SSD/Personal/datasets/papers")

    # SQLite database
    SQLITE_DB_PATH: Path = Path("/Volumes/Extreme SSD/Personal/datasets/papers.db")

    # arXiv API
    ARXIV_MAX_RESULTS_PER_QUERY: int = 100
    ARXIV_RATE_LIMIT_SECONDS: float = 3.0  # arXiv asks for <= 1 req / 3 sec

    # ChromaDB HTTP server
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
