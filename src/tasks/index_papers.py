"""Celery tasks for parsing PDFs and indexing chunks into ChromaDB."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.celery_app import celery_app
from src.indexing.pdf_parser import chunk_paper
from src.indexing.vector_store import get_vector_store
from src.storage.db_client import get_db_client

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="arxiv_index",
)
def index_paper(self, paper_id: str) -> Dict[str, Any]:
    """
    Parse a single paper PDF and upsert its chunks into ChromaDB.

    Skips papers that have no local PDF path or are already indexed.
    """
    db = get_db_client()
    paper = db.get_paper_by_id(paper_id)

    if paper is None:
        logger.warning("index_paper: paper %s not found in DB", paper_id)
        return {"paper_id": paper_id, "status": "not_found"}

    filepath = paper.get("filepath")
    if not filepath or not Path(filepath).exists():
        logger.warning("index_paper: no PDF on disk for %s (path=%s)", paper_id, filepath)
        return {"paper_id": paper_id, "status": "no_pdf"}

    vs = get_vector_store()

    if vs.paper_is_indexed(paper_id):
        logger.debug("index_paper: %s already indexed, skipping", paper_id)
        return {"paper_id": paper_id, "status": "already_indexed"}

    try:
        chunks = chunk_paper(
            pdf_path=filepath,
            paper_id=paper_id,
            extra_metadata={
                "title": paper.get("title", ""),
                "categories": paper.get("categories", ""),
                "published_date": str(paper.get("published_date", "")),
            },
        )
        vs.index_chunks(chunks)
        logger.info("index_paper: indexed %d chunks for %s", len(chunks), paper_id)
        return {"paper_id": paper_id, "status": "indexed", "chunks": len(chunks)}
    except Exception as exc:
        logger.error("index_paper: failed for %s: %s", paper_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(queue="arxiv_index")
def reindex_all_papers() -> Dict[str, Any]:
    """
    Backfill task — iterates all papers in SQLite with a local PDF and
    dispatches an index_paper sub-task for each one not yet indexed.
    """
    start_time = time.time()
    db = get_db_client()
    vs = get_vector_store()

    logger.info("reindex_all_papers: starting backfill")

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id, filepath FROM papers WHERE filepath IS NOT NULL"
        ).fetchall()

    total_rows = len(rows)
    logger.info("reindex_all_papers: found %d papers with filepath in DB", total_rows)

    dispatched: List[str] = []
    skipped_missing: int = 0
    skipped_indexed: int = 0

    for i, row in enumerate(rows, start=1):
        pid, filepath = row["id"], row["filepath"]
        logger.info("reindex_all_papers: [%d/%d] processing %s", i, total_rows, pid)

        if not filepath or not Path(filepath).exists():
            logger.info("reindex_all_papers: skipping %s — PDF not found (%s)", pid, filepath)
            skipped_missing += 1
            continue

        if vs.paper_is_indexed(pid):
            logger.info("reindex_all_papers: skipping %s — already indexed", pid)
            skipped_indexed += 1
            continue

        try:
            result = index_paper.run(pid)
            logger.info(
                "reindex_all_papers: indexed %s — status=%s chunks=%s",
                pid,
                result.get("status"),
                result.get("chunks"),
            )
            dispatched.append(pid)
        except Exception as exc:
            logger.error("reindex_all_papers: failed to index %s: %s", pid, exc)
            raise

    elapsed = time.time() - start_time
    skipped = skipped_missing + skipped_indexed
    logger.info(
        "reindex_all_papers: finished — dispatched=%d skipped=%d "
        "(missing_pdf=%d already_indexed=%d) elapsed=%.2fs",
        len(dispatched),
        skipped,
        skipped_missing,
        skipped_indexed,
        elapsed,
    )
    return {
        "dispatched": len(dispatched),
        "skipped": skipped,
        "skipped_missing_pdf": skipped_missing,
        "skipped_already_indexed": skipped_indexed,
        "elapsed_seconds": elapsed,
    }
