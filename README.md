# MBA Jobs

A job workspace for the INSEAD community. The Python scraper downloads job offers
from the authenticated 12twenty portal to local JSON. A Next.js web app now provides
the initial UI shell; its data and authentication integrations are the next steps.

## Project Structure

```
mba-jobs/
├── scraper/              # Python — 12twenty scraper
│   ├── pyproject.toml
│   ├── tests/
│   └── src/
│       └── mba_jobs_scraper/
├── web/                  # Next.js, TypeScript, Tailwind, shadcn/ui
├── data/                 # Scraped data (gitignored)
│   ├── runs/             # Raw data per scrape run
│   └── latest.json       # Most recent scrape
└── README.md
```

## Web app

Install Node.js 20.18.1 or newer, then run:

```bash
cd web
npm install
npm run dev
```

The shell is available at [http://localhost:3000](http://localhost:3000).
It has no job data or authentication yet and should not be deployed as a protected
job board. The next access milestone is a verified email OTP for `@insead.edu`;
institutional SSO can follow later. The three planned KPIs are job offers first
seen in the rolling last 24 hours, first seen in the rolling last 168 hours,
and total current offers. They show empty values until the database is connected.

## Scraper quick start

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

# Fetch at most 50 jobs
python -m mba_jobs_scraper scrape --limit 50

# Increase the delay between requests (minimum: 1 second; default: 1.5 seconds)
python -m mba_jobs_scraper scrape --delay 2.5

# Run visibly (non-headless) to debug
python -m mba_jobs_scraper scrape --visible
```

Each run writes a timestamped snapshot under `data/runs/YYYY-MM-DD/` and atomically
updates `data/latest.json`. When details are requested, unchanged details from earlier
runs are reused so the scraper makes fewer requests.

If the portal responds with HTTP 429 or a temporary server error, the scraper uses
bounded exponential backoff. It does not retry authentication or other client errors.

### 4. Explore the API (optional)

```bash
python -m mba_jobs_scraper explore
```

Opens a browser with DevTools for manual API exploration.

## Development checks

```bash
cd scraper
ruff check .
ruff format --check .
mypy src
python -m unittest discover -s tests
```

## Technology

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Scraper | Python + Playwright | Browser automation, XHR interception |
| Output | JSON | Local timestamped snapshots and latest result |
| Web | Next.js + shadcn/ui | UI shell (authentication and data pending) |
| CLI | Rich | Scraper progress and summaries |
