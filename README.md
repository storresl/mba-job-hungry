# MBA Job Hungry

A job workspace for the INSEAD community. The Python scraper downloads job offers
from the authenticated 12twenty portal to local JSON. The Next.js dashboard reads
that local archive for job counts and recent offers.

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
│   ├── runs/             # New offers found in each run
│   ├── latest.json       # New offers from the most recent run
│   └── jobs.json         # All unique offers ever seen
└── README.md
```

## Web app

Install Node.js 20.18.1 or newer, then run:

```bash
cd web
npm install
npm run dev
```

The dashboard is available at [http://localhost:3000](http://localhost:3000)
in development. It reads `data/jobs.json` on each request, counts offers published
in the rolling last 24 and 168 hours, and shows the total unique offers in the
archive. Recent offers are ordered by the portal's `PostedDate` and shown six at
a time. The portal timestamps have no timezone; the app interprets them as UTC.

The local archive contains private portal data. The dashboard sends only the
fields needed for the cards and stays unavailable in production until verified
`@insead.edu` sign-in and server-side authorization are implemented.

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
# Save only offers not found in previous JSON files
python -m mba_jobs_scraper scrape

# Fetch descriptions and other details for new offers only
python -m mba_jobs_scraper scrape --with-details

# Check only the first 50 portal listings (may miss newer offers beyond them)
python -m mba_jobs_scraper scrape --limit 50

# Increase the delay between requests (minimum: 1 second; default: 1.5 seconds)
python -m mba_jobs_scraper scrape --delay 2.5

# Run visibly (non-headless) to debug
python -m mba_jobs_scraper scrape --visible
```

The scraper checks portal listing pages against IDs in your saved JSON. Each run writes
only newly discovered offers to a timestamped file under `data/runs/YYYY-MM-DD/` and
atomically updates `data/latest.json` with that new batch (which can be empty).
`data/jobs.json` is the deduplicated archive of every offer ever seen, including offers
that may no longer appear in the portal. On the first run after this change, existing
`data/latest.json` and older run snapshots seed the archive,
so those jobs are not fetched again. Full details are requested only for new offers.
The listing pages still have to be checked to discover new IDs; omit `--limit` to check
all available portal listings.

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
| Output | JSON | New-offer batches and a unique cumulative archive |
| Web | Next.js + shadcn/ui | UI shell (authentication and data pending) |
| CLI | Rich | Scraper progress and summaries |
