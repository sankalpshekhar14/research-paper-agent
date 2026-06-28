"""Paper metadata and vector search endpoints."""

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.indexing.vector_store import get_vector_store
from src.storage.db_client import get_db_client

router = APIRouter(prefix="/papers", tags=["papers"])


class SearchResult(BaseModel):
    text: str
    metadata: Dict[str, Any]
    distance: float
    rerank_score: Optional[float] = None


@router.get("/")
def list_papers(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    category: Optional[str] = Query(None, description="Filter by category e.g. cs.AI"),
):
    """List papers stored in SQLite with optional category filter."""
    db = get_db_client()
    with db._connect() as conn:
        if category:
            rows = conn.execute(
                "SELECT id, title, categories, published_date, filepath FROM papers "
                "WHERE categories LIKE ? LIMIT ? OFFSET ?",
                (f"%{category}%", limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, categories, published_date, filepath FROM papers "
                "LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

    return [dict(r) for r in rows]


@router.get("/{paper_id}")
def get_paper(paper_id: str):
    """Fetch full metadata for a single paper."""
    db = get_db_client()
    paper = db.get_paper_by_id(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"Paper {paper_id!r} not found")
    return paper


@router.get("/search/semantic")
def semantic_search(
    q: str = Query(..., description="Free-text query"),
    n: int = Query(5, ge=1, le=50, description="Number of results"),
    category: Optional[str] = Query(None, description="Filter chunks by category"),
    mode: Literal["vector", "hybrid"] = Query(
        "hybrid", description="Search mode: 'vector' (pure embedding) or 'hybrid' (BM25 + vector + reranker)"
    ),
    rerank: bool = Query(True, description="Apply cross-encoder reranking (hybrid mode only)"),
) -> List[SearchResult]:
    """
    Search over indexed paper chunks.

    - **vector**: pure cosine similarity over chunk embeddings
    - **hybrid**: BM25 + vector fused via Reciprocal Rank Fusion, then reranked
      with a cross-encoder (``cross-encoder/ms-marco-MiniLM-L-6-v2``)
    """
    vs = get_vector_store()
    where = {"categories": {"$contains": category}} if category else None

    if mode == "hybrid":
        hits = vs.hybrid_query(query_text=q, n_results=n, where=where, rerank=rerank)
    else:
        hits = vs.query(query_text=q, n_results=n, where=where)

    return [SearchResult(**h) for h in hits]
