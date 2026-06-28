"""Indexing endpoints — trigger PDF parsing and ChromaDB upsert."""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from src.indexing.vector_store import get_vector_store
from src.storage.db_client import get_db_client
from src.tasks.index_papers import index_paper, reindex_all_papers

router = APIRouter(prefix="/index", tags=["indexing"])


class IndexPaperResponse(BaseModel):
    paper_id: str
    status: str
    chunks: Optional[int] = None


class ReindexResponse(BaseModel):
    dispatched: int
    skipped: int


@router.post("/paper/{paper_id}", response_model=IndexPaperResponse)
def index_single_paper(paper_id: str):
    """
    Parse and index a single paper by its arXiv ID (e.g. ``arxiv:2401.12345``).
    Runs synchronously — returns when indexing is complete.
    """
    db = get_db_client()
    if not db.paper_exists(paper_id):
        raise HTTPException(status_code=404, detail=f"Paper {paper_id!r} not found in DB")

    result = index_paper.run(paper_id)
    return IndexPaperResponse(**result)


@router.post("/reindex", response_model=ReindexResponse)
def reindex_all(background_tasks: BackgroundTasks):
    """
    Backfill — index every paper in SQLite that has a local PDF and is not yet
    in ChromaDB. Runs in the background; returns immediately with counts.
    """
    db = get_db_client()
    vs = get_vector_store()

    logger.info("reindex_all: scanning DB for papers to index")

    with db._connect() as conn:
        rows = conn.execute(
            "SELECT id FROM papers WHERE filepath IS NOT NULL"
        ).fetchall()

    from pathlib import Path

    to_index = []
    skipped = 0
    for row in rows:
        pid = row["id"]
        paper = db.get_paper_by_id(pid)
        fp = paper.get("filepath") if paper else None
        if not fp or not Path(fp).exists():
            skipped += 1
            continue
        if vs.paper_is_indexed(pid):
            skipped += 1
            continue
        to_index.append(pid)

    logger.info("reindex_all: dispatching %d indexing tasks, skipping %d", len(to_index), skipped)

    def _run():
        for i, pid in enumerate(to_index, start=1):
            logger.info("reindex_all: background [%d/%d] indexing %s", i, len(to_index), pid)
            index_paper.run(pid)
        logger.info("reindex_all: background batch finished")

    background_tasks.add_task(_run)

    return ReindexResponse(dispatched=len(to_index), skipped=skipped)


@router.get("/status/{paper_id}")
def index_status(paper_id: str):
    """Check whether a paper is already indexed in ChromaDB."""
    db = get_db_client()
    if not db.paper_exists(paper_id):
        raise HTTPException(status_code=404, detail=f"Paper {paper_id!r} not found in DB")

    vs = get_vector_store()
    indexed = vs.paper_is_indexed(paper_id)
    return {"paper_id": paper_id, "indexed": indexed}


@router.delete("/paper/{paper_id}")
def delete_paper_index(paper_id: str):
    """Remove all ChromaDB chunks for a paper (does not touch SQLite or the PDF)."""
    vs = get_vector_store()
    if not vs.paper_is_indexed(paper_id):
        raise HTTPException(status_code=404, detail=f"No indexed chunks found for {paper_id!r}")
    vs.delete_paper(paper_id)
    return {"paper_id": paper_id, "status": "deleted"}
