"""Celery application configuration."""

from celery import Celery

from src.config import settings

celery_app = Celery(
    "research_paper_agent",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["src.tasks.fetch_papers", "src.tasks.index_papers"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,          # 30 min hard limit per task
    task_soft_time_limit=1200,     # 20 min soft limit
    worker_prefetch_multiplier=1,  # fetch one task at a time (helps rate-limiting)
    beat_schedule={
        "fetch-all-categories-daily": {
            "task": "src.tasks.fetch_papers.fetch_all_categories_daily",
            "schedule": 86400.0,  # once every 24 hours
            # Or use crontab for a specific wall-clock time, e.g.:
            # "schedule": crontab(hour=6, minute=0),
        },
    },
)

# Route fetch tasks to a dedicated queue so you can run a single-concurrency
# worker that respects arXiv's 1-request-every-3-seconds rule.
celery_app.conf.task_routes = {
    "src.tasks.fetch_papers.fetch_papers_for_category": {"queue": "arxiv_fetch"},
    "src.tasks.fetch_papers.fetch_all_categories_daily": {"queue": "arxiv_schedule"},
    "src.tasks.index_papers.index_paper": {"queue": "arxiv_index"},
    "src.tasks.index_papers.reindex_all_papers": {"queue": "arxiv_index"},
}
