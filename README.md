# MBA Jobs Tracker

A personal job search tool for MBA students. Scrapes job postings from INSEAD's 12twenty portal, stores them locally, and provides full-text search and filtering.

## Architecture

```
┌─────────────────────┐     JSON files     ┌─────────────────────┐
│   Python Scraper    │ ─────────────────→  │   Rust Backend      │
│   (Playwright)      │                     │   (axum + tantivy)  │
│                     │                     │                     │
│ • Session mgmt      │                     │ • Ingest & dedupe   │
│ • XHR interception   │                     │ • SQLite storage    │
│ • Pagination        │                     │ • Full-text search  │
│ • Daily cron        │                     │ • REST API          │
└─────────────────────┘                     └─────────────────────┘
```

## Project Structure

```
mba-jobs/
├── scraper/              # Python — 12twenty scraper
│   ├── pyproject.toml
│   └── src/
│       └── mba_jobs_scraper/
├── backend/              # Rust — API, storage, search (Phase 2)
├── data/                 # Scraped data (gitignored)
│   ├── runs/             # Raw data per scrape run
│   └── latest.json       # Most recent scrape
└── README.md
```

## Quick Start

### 1. Install the scraper

```bash
cd scraper
pip install -e ".[dev]"
playwright install chromium
```

### 2. Login to 12twenty (one-time)

```bash
python -m mba_jobs_scraper login
```

This opens a browser window. Log in to the INSEAD portal, then press Enter in the terminal.

### 3. Scrape jobs

```bash
# List only (fast — just the job listing data)
python -m mba_jobs_scraper scrape

# With full details for each job (slower — fetches description, salary, etc.)
python -m mba_jobs_scraper scrape --with-details

# Run visibly (non-headless) to debug
python -m mba_jobs_scraper scrape --visible
```

### 4. Explore the API (optional)

```bash
python -m mba_jobs_scraper explore
```

Opens a browser with DevTools for manual API exploration.

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Scraper | Python + Playwright | Browser automation, XHR interception |
| Backend | Rust + axum | REST API server |
| Storage | SQLite + sqlx | Structured job data |
| Search | tantivy | Full-text search engine |
| Scheduler | tokio-cron-scheduler | Daily automation |
