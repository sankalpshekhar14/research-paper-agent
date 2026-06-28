"""Celery tasks for daily arXiv paper ingestion."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.arxiv_client import ArxivAPIClient
from src.categories import ArxivCategory
from src.celery_app import celery_app
from src.config import settings
from src.storage.db_client import get_db_client
from src.storage.local_storage import LocalStorage

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    queue="arxiv_fetch",
)
def fetch_papers_for_category(
    self,
    category_value: str,
    date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch, download and store papers for a single arXiv category.

    Args:
        category_value: e.g. ``"cs.AI"``
        date_str: ``"YYYY-MM-DD"``. Defaults to yesterday (UTC).

    Returns:
        A dict summarising how many papers were fetched and stored.
    """
    # ------------------------------------------------------------------
    # Resolve inputs
    # ------------------------------------------------------------------
    try:
        category = ArxivCategory.from_str(category_value)
    except ValueError as exc:
        raise self.retry(exc=exc, countdown=10)

    if date_str is None:
        target_date = datetime.utcnow() - timedelta(days=1)
    else:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")

    logger.info("[%s] Fetching papers for %s on %s", category_value, category_value, target_date.date())

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    arxiv_client = ArxivAPIClient(max_results=settings.ARXIV_MAX_RESULTS_PER_QUERY)
    storage = LocalStorage(base_path=settings.PAPERS_STORAGE_PATH)
    db_client = get_db_client()

    # ------------------------------------------------------------------
    # Fetch from arXiv (paginated)
    # ------------------------------------------------------------------
    try:
        papers = arxiv_client.fetch_papers_by_category_and_date(
            category, target_date
        )
    except Exception as exc:
        logger.error("[%s] arXiv API failed: %s", category_value, exc)
        raise self.retry(exc=exc)

    logger.info("[%s] API returned %d papers", category_value, len(papers))

    # ------------------------------------------------------------------
    # Download PDFs + persist metadata
    # ------------------------------------------------------------------
    stored_count = 0
    for paper in papers:
        paper_id = paper["id"]

        # Skip duplicates
        if db_client.paper_exists(paper_id):
            logger.debug("[%s] Skipping duplicate %s", category_value, paper_id)
            continue

        # Download PDF
        if paper.get("pdf_url"):
            try:
                filepath = storage.save_paper(
                    paper_id=paper_id,
                    pdf_url=paper["pdf_url"],
                    category=category_value,
                )
                paper["local_pdf_path"] = filepath
                logger.debug("[%s] Downloaded PDF for %s -> %s", category_value, paper_id, filepath)
            except Exception as exc:
                logger.warning("[%s] PDF download failed for %s: %s", category_value, paper_id, exc)
                paper["local_pdf_path"] = None
        else:
            paper["local_pdf_path"] = None

        # Store metadata
        try:
            db_client.store_paper_metadata(paper)
            stored_count += 1
            logger.debug("[%s] Stored metadata for %s", category_value, paper_id)
        except Exception as exc:
            logger.error("[%s] DB store failed for %s: %s", category_value, paper_id, exc)
            continue

        # Kick off vector indexing asynchronously
        if paper.get("local_pdf_path"):
            from src.tasks.index_papers import index_paper  # avoid circular import
            index_paper.delay(paper_id)
            logger.debug("[%s] Queued index_paper for %s", category_value, paper_id)

    logger.info("[%s] Done. Fetched=%d Stored=%d", category_value, len(papers), stored_count)

    return {
        "category": category_value,
        "date": target_date.strftime("%Y-%m-%d"),
        "fetched": len(papers),
        "stored": stored_count,
    }


@celery_app.task(queue="arxiv_schedule")
def fetch_all_categories_daily(date_str: Optional[str] = None) -> Dict[str, Any]:
    """
    Beat-scheduled task that fans-out one sub-task per category.

    This task itself is cheap; it simply dispatches ``fetch_papers_for_category``
    jobs so that each category is processed independently.
    """
    if date_str is None:
        date_str = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    dispatched = []
    for category in ArxivCategory:
        result = fetch_papers_for_category.delay(category.value, date_str)
        dispatched.append({"category": category.value, "task_id": result.id})

    return {
        "date": date_str,
        "dispatched_tasks": dispatched,
    }
