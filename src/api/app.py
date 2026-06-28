"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routers import indexing, papers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-load the VectorStore (embedding model + cross-encoder) at startup
    # so the first request doesn't pay the model-load penalty.
    logger.info("startup: warming VectorStore models ...")
    from src.indexing.vector_store import get_vector_store
    get_vector_store()
    logger.info("startup: VectorStore ready")
    yield


app = FastAPI(
    title="Research Paper RAG API",
    description="Ingest, index, and search arXiv papers via ChromaDB.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(papers.router)
app.include_router(indexing.router)


@app.get("/health")
def health():
    return {"status": "ok"}
