# CLAUDE.md — Research Paper RAG Agent

## Project Overview

A Celery-backed ingestion pipeline that fetches arXiv papers daily, persists metadata to SQLite, stores PDFs on local disk, and exposes a LangGraph/LangChain agent layer for querying the corpus.

## Tech Stack

- **Orchestration:** Celery + Celery Beat (periodic tasks)
- **Broker:** Redis (assumed; configurable via env)
- **Database:** SQLite (local file on external SSD)
- **PDF Storage:** Local filesystem
- **API:** FastAPI + Uvicorn
- **Agent Framework:** LangGraph / LangChain (requirements present; agent layer TBD)
- **Embedding/Vector:** ChromaDB (HTTP server mode) + sentence-transformers (`all-MiniLM-L6-v2`)
- **PDF → Markdown:** pymupdf4llm

## Directory Structure

```
src/
  __init__.py
  config.py                   # Pydantic-settings; all paths & broker URLs
  categories.py               # ArxivCategory enum (cs.AI, cs.LG, etc.)
  celery_app.py               # Celery app, Beat schedule, queue routing
  arxiv_client.py             # Atom API client with pagination & id parsing
  tasks/
    __init__.py
    fetch_papers.py           # Core ingestion Celery tasks
    index_papers.py           # Celery tasks: index_paper, reindex_all_papers
  storage/
    __init__.py
    local_storage.py          # PDF download & filesystem layout
    db_client.py              # SQLite client (singleton)
  indexing/
    __init__.py
    pdf_parser.py             # PDF → markdown + section-based chunking
    vector_store.py           # ChromaDB HTTP client wrapper (singleton)
  api/
    __init__.py
    app.py                    # FastAPI app entry point
    routers/
      __init__.py
      indexing.py             # POST /index/paper/{id}, POST /index/reindex, etc.
      papers.py               # GET /papers/, GET /papers/{id}, GET /papers/search/semantic
scripts/
  fetch_on_demand.py          # Synchronous single-category fetch (logs to stdout)
  fetch_all_on_demand.py      # Synchronous all-category fetch (logs to stdout)
  inspect_vectordb.py         # Tabulate ChromaDB contents in the terminal
```

## Key Conventions

### Paper ID Format
- **Canonical ID:** `arxiv:2401.12345` (version stripped, `arxiv:` prefix)
- **Version:** stored separately in DB (`version` column)
- **Filename:** `arxiv_2401.12345.pdf` (colon replaced with underscore)

### Date Handling
- Default fetch date is **yesterday UTC** (`datetime.utcnow() - timedelta(days=1)`)
- arXiv API `submittedDate` range format: `[YYYYMMDD0000 TO YYYYMMDD2359]`
- **Critical:** use literal spaces inside the brackets, not `+` signs. `requests` encodes spaces as `+` in the query string correctly.

### Database Schema (`papers` table)

```sql
id TEXT PRIMARY KEY,          -- e.g. "arxiv:2401.12345"
title TEXT,
abstract TEXT,
published_date TIMESTAMP,     -- arXiv announcement date
updated_date TIMESTAMP,       -- last update
categories TEXT,              -- comma-separated (cs.AI,cs.LG)
pdf_url TEXT,
filepath TEXT,                -- local PDF path on SSD
version TEXT,
created_at TIMESTAMP
```

### Storage Layout

```
/Volumes/Extreme SSD/Personal/datasets/
  papers.db                   # SQLite DB
  papers/
    cs_AI/
      arxiv_2401.12345.pdf
    cs_LG/
      ...
```

### Queue Design
- `arxiv_schedule` — Beat dispatcher (`fetch_all_categories_daily`)
- `arxiv_fetch` — actual ingestion workers
- `arxiv_index` — PDF parsing + ChromaDB upsert workers
- **Run fetch workers with `--concurrency=1`** to respect arXiv's 1-request-every-3-seconds rate limit.

### Chunking Strategy
- PDFs are converted to markdown via `pymupdf4llm`
- Split on markdown headings (`#` / `##` / `###`) into sections
- Sections over **1500 tokens** (~6000 chars) are sub-chunked with **150-token overlap**
- Each chunk carries metadata: `paper_id`, `title`, `categories`, `published_date`, `section`

### ChromaDB
- Collection name: `papers`
- Embedding model: `all-MiniLM-L6-v2` (via `sentence-transformers`)
- Distance metric: cosine
- Chunk ID format: `arxiv:2401.12345::chunk::0`

## Running Things

### On-demand (no broker needed)

```bash
source venv/bin/activate

# Single category — logs stream to terminal
python scripts/fetch_on_demand.py cs.AI --date 2024-01-01

# All categories
python scripts/fetch_all_on_demand.py --date 2024-01-01

# Verbose (DEBUG logs)
python scripts/fetch_on_demand.py cs.AI --date 2024-01-01 -v
```

These use `.run()` which executes the task function directly in the current process.

### Celery pipeline (production)

```bash
# Terminal 1 — Redis
redis-server

# Terminal 2 — worker (concurrency=1 for rate limiting)
celery -A src.celery_app worker -Q arxiv_fetch --concurrency=1 --loglevel=info

# Terminal 3 — beat scheduler
celery -A src.celery_app beat --loglevel=info
```

### FastAPI server

```bash
venv/bin/uvicorn src.api.app:app --reload --port 8080
```

Swagger UI available at `http://localhost:8080/docs`.

### Indexing (no broker needed)

```bash
# Index a single paper synchronously
venv/bin/python -c "from src.tasks.index_papers import index_paper; index_paper.run('arxiv:2401.12345')"

# Backfill all papers with local PDFs
venv/bin/python -c "from src.tasks.index_papers import reindex_all_papers; reindex_all_papers.run()"

# Inspect ChromaDB contents
python scripts/inspect_vectordb.py
python scripts/inspect_vectordb.py --paper-id arxiv:2401.12345  # chunk detail
```

### Quick Python test

```python
from src.tasks.fetch_papers import fetch_papers_for_category
result = fetch_papers_for_category.run("cs.AI", "2024-01-01")
print(result)
```

## Configuration

All settings live in `src/config.py` and can be overridden via `.env`:

```bash
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
PAPERS_STORAGE_PATH=/Volumes/Extreme SSD/Personal/datasets/papers
SQLITE_DB_PATH=/Volumes/Extreme SSD/Personal/datasets/papers.db
ARXIV_MAX_RESULTS_PER_QUERY=100
ARXIV_RATE_LIMIT_SECONDS=3.0
CHROMA_HOST=localhost
CHROMA_PORT=8000
```

## Extending the DB Client

`src/storage/db_client.py` uses a singleton pattern. To swap SQLite for Postgres later:

1. Implement a new class matching the interface (`store_paper_metadata`, `paper_exists`)
2. Call `set_db_client(MyPostgresClient())` at app startup

## Adding a New arXiv Category

1. Add the member to `ArxivCategory` in `src/categories.py`
2. That's it — the Beat schedule and on-demand scripts iterate the enum automatically

## Common Issues

- **Empty results for a date:** Some dates have 0 submissions in a narrow category. Try a broader category or different date.
- **arXiv 500 errors:** Almost always caused by `+` signs inside `submittedDate` brackets. Use spaces instead.
- **Rate limited:** Ensure the `arxiv_fetch` queue worker runs with `--concurrency=1`.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/papers/` | List papers (supports `limit`, `offset`, `category`) |
| GET | `/papers/{paper_id}` | Full metadata for one paper |
| GET | `/papers/search/semantic?q=...&n=5` | Semantic search over chunks |
| POST | `/index/paper/{paper_id}` | Index a single paper (synchronous) |
| POST | `/index/reindex` | Backfill all un-indexed papers (background) |
| GET | `/index/status/{paper_id}` | Check if a paper is indexed |
| DELETE | `/index/paper/{paper_id}` | Remove all chunks for a paper |

## What's Not Built Yet

- LangGraph agent layer for query answering
- Postgres migration (SQLite is placeholder)
- Tests
