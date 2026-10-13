"""
12twenty Job Postings Scraper

Strategy:
  1. Use Playwright with persistent browser context (preserves login session across runs)
  2. Navigate to job listings → triggers the internal POST /Api/V2/job-postings/post-query XHR
  3. Intercept the request to learn the exact POST body format (filters, pagination, etc.)
  4. Replay the API call with modified page numbers via page.evaluate(fetch(...))
  5. For full details, try direct GET to /api/internal/core-job-postings/{id}
  6. Fall back to clicking each job in the list and intercepting the detail XHR
  7. Export everything to JSON files
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Page,
    Request,
    Response,
    async_playwright,
)
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

console = Console()

# ── URLs ──────────────────────────────────────────────────────────────────────
BASE_URL = "https://insead.12twenty.com"
JOB_LISTINGS_URL = f"{BASE_URL}/jobPostings#/jobPostings/index?viewId=1&tab=all"
POST_QUERY_URL = f"{BASE_URL}/Api/V2/job-postings/post-query"
DETAIL_URL_PREFIX = f"{BASE_URL}/api/internal/core-job-postings/"

# Pattern matching for XHR interception
POST_QUERY_PATTERN = "job-postings/post-query"
DETAIL_PATTERN = "core-job-postings/"

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SESSION_DIR = PROJECT_ROOT / ".session"
DATA_DIR = PROJECT_ROOT / "data"


class TwelveTwentyScraper:
    """Scraper for INSEAD's 12twenty job postings portal.

    Uses Playwright to maintain an authenticated browser session and intercept
    the internal XHR API calls that the 12twenty SPA makes. This gives us clean
    structured JSON without brittle DOM scraping.
    """

    def __init__(self) -> None:
        self._captured_request_body: dict | None = None
        self._captured_headers: dict[str, str] | None = None
        self._list_items: list[dict[str, Any]] = []
        self._details: dict[str, dict[str, Any]] = {}  # keyed by job ID (string)
        self._total_jobs: int = 0
        self._page_size: int = 50

    # ── Public Commands ───────────────────────────────────────────────────────

    async def login(self) -> None:
        """Open browser for manual login. Session cookies are persisted to disk."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)

        console.print("\n[bold green]🔐 Opening browser for login...[/]")
        console.print(
            "   Log in to the INSEAD 12twenty portal with your student credentials.\n"
            "   Once you reach the Job Postings page, press Enter here (or we'll auto-detect it).\n"
        )

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(BASE_URL)

            console.print("[yellow]Browser is open. Waiting for login... (press Enter when done)[/]")
            loop = asyncio.get_event_loop()
            enter_future = loop.run_in_executor(None, input)

            while not enter_future.done():
                try:
                    if "jobPostings" in page.url:
                        console.print("   [bold green]✓ Detected Job Postings page! Waiting 3s to persist session...[/]")
                        await page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)

            await context.close()

        console.print("[bold green]✓ Session saved to .session/[/]\n")

    async def scrape(
        self,
        with_details: bool = False,
        headless: bool = True,
        limit: int | None = None,
        delay: float = 1.5,
    ) -> list[dict[str, Any]]:
        """Scrape job postings from the portal with polite rate-limiting.

        Args:
            with_details: If True, also fetch the full detail page for each job.
            headless: If False, shows the browser window (useful for debugging).
            limit: Maximum number of jobs to fetch (e.g. 50).
            delay: Polite delay between requests in seconds (with jitter).

        Returns:
            List of job dictionaries, each containing 'list_data' and optionally 'detail_data'.
        """
        if not SESSION_DIR.exists():
            console.print("[bold red]❌ No saved session. Run 'login' first.[/]")
            return []

        console.print("\n[bold]🔍 MBA Jobs Scraper[/]")
        console.print(f"   Mode: {'with details' if with_details else 'list only'}")
        console.print(f"   Headless: {headless}")
        if limit:
            console.print(f"   Limit: [cyan]{limit}[/] jobs")
        console.print(f"   Polite delay: [cyan]{delay:.1f}s[/] (with jitter)\n")

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=headless,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # ── Step 1: Capture initial API call ──────────────────────────
                console.print("[bold]Step 1/4:[/] Loading portal & capturing initial API request...")
                first_response = await self._capture_initial_request(page)

                if first_response is None:
                    console.print("[bold red]❌ Failed to capture API response.[/]")
                    console.print("   Your session may be expired. Run [bold]login[/] again.")
                    return []

                self._total_jobs = first_response.get("Total", 0)
                self._page_size = first_response.get("PageSize", 50)
                page_items = first_response.get("Items", [])
                self._list_items.extend(page_items)

                console.print(f"   Found [bold cyan]{self._total_jobs}[/] total jobs in portal (page size: {self._page_size})")
                console.print(f"   Captured [green]{len(page_items)}[/] jobs from page 1")

                # Log a sample of fields so we can understand the data shape
                if page_items:
                    sample = page_items[0]
                    console.print(f"   Sample fields: {', '.join(sample.keys())}")

                # ── Step 2: Paginate (if needed and within limit) ─────────────
                total_target = min(self._total_jobs, limit) if limit else self._total_jobs
                if limit and len(self._list_items) >= limit:
                    self._list_items = self._list_items[:limit]
                    console.print(f"\n[bold]Step 2/4:[/] Target limit of {limit} jobs already satisfied by page 1. Skipping extra pages. ✓")
                else:
                    total_pages = math.ceil(total_target / self._page_size)
                    if total_pages > 1:
                        console.print(f"\n[bold]Step 2/4:[/] Fetching remaining {total_pages - 1} pages (target: {total_target} jobs, delay: {delay:.1f}s)...")
                        await self._paginate_via_fetch(page, total_pages, limit=limit, delay=delay)
                    else:
                        console.print(f"\n[bold]Step 2/4:[/] All requested jobs fit on one page. ✓")

                if limit and len(self._list_items) > limit:
                    self._list_items = self._list_items[:limit]

                console.print(f"   Total list items collected: [bold green]{len(self._list_items)}[/]")

                # ── Step 3: Fetch details (optional) ──────────────────────────
                if with_details:
                    console.print(f"\n[bold]Step 3/4:[/] Fetching details for {len(self._list_items)} jobs (polite delay: {delay:.1f}s with jitter)...")
                    await self._fetch_details(page, delay=delay)
                    console.print(f"   Details collected: [bold green]{len(self._details)}[/]")
                else:
                    console.print(f"\n[bold]Step 3/4:[/] Skipping details (use --with-details to include).")

                # ── Step 4: Export ────────────────────────────────────────────
                console.print(f"\n[bold]Step 4/4:[/] Exporting data...")
                jobs = self._export()

                console.print(f"\n[bold green]✓ Done![/] {len(jobs)} jobs exported.\n")
                return jobs

            finally:
                await context.close()

    async def explore(self) -> None:
        """Open browser with saved session and DevTools for API exploration."""
        if not SESSION_DIR.exists():
            console.print("[bold red]❌ No saved session. Run 'login' first.[/]")
            return

        console.print("\n[bold green]🔬 Opening browser for exploration...[/]")
        console.print("   DevTools will open automatically. Check the Network tab.")
        console.print("   Press Enter in this terminal to close.\n")

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
                viewport={"width": 1280, "height": 800},
                devtools=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(JOB_LISTINGS_URL)

            await asyncio.get_event_loop().run_in_executor(None, input)
            await context.close()

    # ── Private: API Capture ──────────────────────────────────────────────────

    async def _capture_initial_request(self, page: Page) -> dict[str, Any] | None:
        """Navigate to job listings and capture the first post-query request + response.

        We intercept both the request (to learn the POST body format) and the response
        (to get the first page of data and the total count).
        """
        captured: dict[str, Any] = {
            "response": None,
            "request_body": None,
            "request_headers": None,
        }

        async def on_request(request: Request) -> None:
            if POST_QUERY_PATTERN in request.url and request.method == "POST":
                captured["request_body"] = request.post_data
                captured["request_headers"] = dict(request.headers)

        async def on_response(response: Response) -> None:
            if POST_QUERY_PATTERN in response.url:
                try:
                    captured["response"] = await response.json()
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            await page.goto(JOB_LISTINGS_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            console.print(f"   [yellow]Navigation warning: {e}[/]")

        # Wait for the XHR to complete (up to 15 seconds)
        for _ in range(30):
            if captured["response"] is not None:
                break
            await page.wait_for_timeout(500)

        # Store the captured request format for replay
        if captured["request_body"]:
            try:
                self._captured_request_body = json.loads(captured["request_body"])
                console.print(f"   [dim]Captured POST body: {json.dumps(self._captured_request_body, indent=2)[:500]}[/]")
            except (json.JSONDecodeError, TypeError):
                console.print("   [yellow]Could not parse request body as JSON[/]")

        self._captured_headers = captured["request_headers"]

        # Clean up listeners
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)

        return captured["response"]

    # ── Private: Pagination ───────────────────────────────────────────────────

    async def _paginate_via_fetch(
        self,
        page: Page,
        total_pages: int,
        limit: int | None = None,
        delay: float = 1.5,
    ) -> None:
        """Fetch remaining pages by replaying the POST request via page.evaluate(fetch(...)).

        Using fetch() inside the browser context ensures we use the same cookies,
        CSRF tokens, and auth headers that the SPA uses natively.
        """
        if not self._captured_request_body:
            console.print("   [yellow]⚠ No captured request body — falling back to scroll pagination.[/]")
            await self._paginate_via_scroll(page, total_pages)
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("  Fetching pages...", total=total_pages - 1)

            for page_num in range(2, total_pages + 1):
                if limit and len(self._list_items) >= limit:
                    break

                try:
                    body = dict(self._captured_request_body)
                    body["PageNumber"] = page_num

                    result = await page.evaluate(
                        """async ({url, body}) => {
                            try {
                                const response = await fetch(url, {
                                    method: 'POST',
                                    headers: {'Content-Type': 'application/json'},
                                    body: JSON.stringify(body),
                                    credentials: 'same-origin',
                                });
                                if (!response.ok) {
                                    return {_error: true, status: response.status, statusText: response.statusText};
                                }
                                return await response.json();
                            } catch (e) {
                                return {_error: true, message: e.message};
                            }
                        }""",
                        {"url": POST_QUERY_URL, "body": body},
                    )

                    if isinstance(result, dict) and result.get("_error"):
                        if result.get("status") == 429:
                            console.print(f"\n   [yellow]⚠ Rate limited (HTTP 429) on page {page_num}. Pausing 10s...[/]")
                            await asyncio.sleep(10)
                        else:
                            console.print(f"\n   [red]Error on page {page_num}: {result}[/]")
                            console.print("   Falling back to scroll pagination for remaining pages...")
                            await self._paginate_via_scroll(page, total_pages, start_from=page_num)
                            return

                    items = result.get("Items", [])
                    self._list_items.extend(items)
                    progress.update(
                        task,
                        advance=1,
                        description=f"  Page {page_num}/{total_pages} (+{len(items)} jobs)",
                    )

                    if limit and len(self._list_items) >= limit:
                        break

                    # Polite jittered delay
                    jitter_ms = int(random.uniform(0.85, 1.25) * delay * 1000)
                    await page.wait_for_timeout(jitter_ms)

                except Exception as e:
                    console.print(f"\n   [red]Error on page {page_num}: {e}[/]")
                    break

    async def _paginate_via_scroll(
        self, page: Page, total_pages: int, start_from: int = 2
    ) -> None:
        """Fallback: trigger pagination by scrolling the page (for infinite scroll UIs)."""
        console.print("   [dim]Using scroll-based pagination...[/]")
        max_no_new_data = 5
        no_new_data_count = 0
        prev_count = len(self._list_items)

        while no_new_data_count < max_no_new_data and len(self._list_items) < self._total_jobs:
            new_items: list[dict] = []

            async def on_response(response: Response) -> None:
                if POST_QUERY_PATTERN in response.url:
                    try:
                        data = await response.json()
                        new_items.extend(data.get("Items", []))
                    except Exception:
                        pass

            page.on("response", on_response)

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            page.remove_listener("response", on_response)

            if new_items:
                self._list_items.extend(new_items)
                console.print(f"   Scroll: +{len(new_items)} jobs (total: {len(self._list_items)})")
                no_new_data_count = 0
            else:
                no_new_data_count += 1

    # ── Private: Detail Fetching ──────────────────────────────────────────────

    async def _fetch_details(self, page: Page, delay: float = 1.5) -> None:
        """Fetch full details for each job.

        Strategy:
          1. Try direct GET to the detail API endpoint (fast, with signature query if present)
          2. If that requires a signature we don't have, fall back to clicking
             each job in the browser and intercepting the detail XHR (slow, ~2s per job)
        """
        if not self._list_items:
            return

        # First, try the direct API approach with a sample job
        sample = self._list_items[0]
        sample_id = str(sample.get("Id", ""))
        sig = sample.get("Signature") or sample.get("signature") or ""
        query_param = f"?signature={sig}" if sig else ""
        direct_works = False

        if sample_id:
            console.print(f"   Testing direct API access (job ID: {sample_id})...")
            try:
                result = await page.evaluate(
                    """async (url) => {
                        try {
                            const r = await fetch(url, {credentials: 'same-origin'});
                            if (!r.ok) return {_error: true, status: r.status};
                            return await r.json();
                        } catch (e) {
                            return {_error: true, message: e.message};
                        }
                    }""",
                    f"{DETAIL_URL_PREFIX}{sample_id}{query_param}",
                )
                if isinstance(result, dict) and not result.get("_error"):
                    direct_works = True
                    self._details[sample_id] = result
                    console.print("   [green]✓ Direct API access works! Using fast mode.[/]")
                else:
                    console.print(f"   [yellow]Direct API returned: {result}[/]")
            except Exception as e:
                console.print(f"   [yellow]Direct API test failed: {e}[/]")

        if direct_works:
            await self._fetch_details_direct(page, delay=delay)
        else:
            console.print("   [yellow]Using browser click-through (slower but reliable)...[/]")
            await self._fetch_details_via_clicks(page, delay=delay)

    async def _fetch_details_direct(self, page: Page, delay: float = 1.5) -> None:
        """Fast path: GET each job's detail directly via the API with polite pacing."""
        # Skip the first one since we already fetched it in the test
        remaining = [
            item for item in self._list_items
            if str(item.get("Id", "")) not in self._details
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("  Fetching details...", total=len(remaining))

            for item in remaining:
                job_id = str(item.get("Id", ""))
                sig = item.get("Signature") or item.get("signature") or ""
                query_param = f"?signature={sig}" if sig else ""
                title = item.get("TitleDisplay", "?")[:40]

                try:
                    result = await page.evaluate(
                        """async (url) => {
                            try {
                                const r = await fetch(url, {credentials: 'same-origin'});
                                if (!r.ok) return {_error: true, status: r.status};
                                return await r.json();
                            } catch (e) {
                                return {_error: true, message: e.message};
                            }
                        }""",
                        f"{DETAIL_URL_PREFIX}{job_id}{query_param}",
                    )

                    if isinstance(result, dict) and not result.get("_error"):
                        self._details[job_id] = result
                    else:
                        if isinstance(result, dict) and result.get("status") == 429:
                            console.print("\n   [yellow]⚠ Rate limited (HTTP 429). Pausing 10s...[/]")
                            await asyncio.sleep(10)
                        else:
                            console.print(f"\n   [dim red]Failed: {title} → {result}[/]")

                except Exception as e:
                    console.print(f"\n   [dim red]Error for {title}: {e}[/]")

                progress.update(task, advance=1, description=f"  {title}")

                # Polite jittered delay
                jitter_ms = int(random.uniform(0.85, 1.25) * delay * 1000)
                await page.wait_for_timeout(jitter_ms)

    async def _fetch_details_via_clicks(self, page: Page, delay: float = 1.5) -> None:
        """Slow path: click each job in the list and intercept the detail XHR response.

        This handles cases where the detail endpoint requires a signed URL
        that only the frontend JS can generate.
        """
        # First, make sure we're on the job listings page
        if POST_QUERY_PATTERN not in page.url and "jobPostings" not in page.url:
            await page.goto(JOB_LISTINGS_URL, wait_until="networkidle")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("  Clicking through jobs...", total=len(self._list_items))
            fetched_count = 0

            # We need to handle pagination in the UI too
            page_num = 1
            items_per_page = self._page_size

            while fetched_count < len(self._list_items):
                # Find all clickable job rows on the current page
                job_rows = await page.query_selector_all(
                    "[class*='job-posting-row'], "
                    "[class*='jobPosting'], "
                    "tr[data-id], "
                    ".posting-item, "
                    "a[href*='jobPosting']"
                )

                if not job_rows:
                    # Try a more generic approach — look for job title links
                    job_rows = await page.query_selector_all(
                        "a[class*='title'], "
                        ".list-group-item"
                    )

                if not job_rows:
                    console.print(f"\n   [yellow]Could not find clickable job rows on page {page_num}[/]")
                    break

                for row in job_rows:
                    if fetched_count >= len(self._list_items):
                        break

                    detail_data: dict[str, Any] = {}

                    async def on_response(response: Response) -> None:
                        if DETAIL_PATTERN in response.url and POST_QUERY_PATTERN not in response.url:
                            try:
                                data = await response.json()
                                if isinstance(data, dict) and "Id" in data:
                                    detail_data["result"] = data
                            except Exception:
                                pass

                    page.on("response", on_response)

                    try:
                        await row.click()

                        # Wait for detail response (up to 5 seconds)
                        for _ in range(10):
                            if "result" in detail_data:
                                break
                            await page.wait_for_timeout(500)

                        if "result" in detail_data:
                            detail = detail_data["result"]
                            job_id = str(detail.get("Id", ""))
                            self._details[job_id] = detail
                            title = detail.get("JobTitle", "?")[:40]
                            progress.update(task, advance=1, description=f"  {title}")
                        else:
                            progress.update(task, advance=1, description="  [no detail response]")

                        # Close the detail modal
                        close_btn = await page.query_selector(
                            "[class*='close'], "
                            "button[aria-label='Close'], "
                            ".modal-close, "
                            "[class*='dismiss']"
                        )
                        if close_btn:
                            await close_btn.click()
                        else:
                            await page.keyboard.press("Escape")

                        # Polite delay with jitter
                        jitter_ms = int(random.uniform(0.85, 1.25) * delay * 1000)
                        await page.wait_for_timeout(jitter_ms)

                    except Exception as e:
                        console.print(f"\n   [dim red]Click error: {e}[/]")
                        progress.update(task, advance=1)

                    finally:
                        page.remove_listener("response", on_response)

                    fetched_count += 1

                # Try to go to next page if needed
                # (This depends on the UI — might be a "Next" button or infinite scroll)
                next_btn = await page.query_selector(
                    "[class*='next'], "
                    "a[aria-label='Next'], "
                    ".pagination-next"
                )
                if next_btn and fetched_count < len(self._list_items):
                    await next_btn.click()
                    await page.wait_for_timeout(2000)
                    page_num += 1
                else:
                    break

    # ── Private: Export ───────────────────────────────────────────────────────

    def _export(self) -> list[dict[str, Any]]:
        """Merge list items with detail data and save to JSON files."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        date_str = now.strftime("%Y-%m-%d")

        # Build merged job objects
        jobs: list[dict[str, Any]] = []
        for item in self._list_items:
            job_id = str(item.get("Id", ""))
            job: dict[str, Any] = {
                "id": job_id,
                "list_data": item,
                "detail_data": self._details.get(job_id),
                "scraped_at": now.isoformat(),
            }
            jobs.append(job)

        # ── Save per-run snapshot ─────────────────────────────────────────
        run_dir = DATA_DIR / "runs" / date_str
        run_dir.mkdir(parents=True, exist_ok=True)

        run_file = run_dir / f"scrape_{timestamp}.json"
        run_payload = {
            "scraped_at": now.isoformat(),
            "total_jobs": len(jobs),
            "total_with_details": sum(1 for j in jobs if j["detail_data"]),
            "captured_request_body": self._captured_request_body,
            "jobs": jobs,
        }
        run_file.write_text(json.dumps(run_payload, indent=2, default=str, ensure_ascii=False))
        console.print(f"   Run data → [link=file://{run_file}]{run_file.relative_to(PROJECT_ROOT)}[/]")

        # ── Save latest (always overwritten) ──────────────────────────────
        latest_file = DATA_DIR / "latest.json"
        latest_payload = {
            "scraped_at": now.isoformat(),
            "total_jobs": len(jobs),
            "jobs": jobs,
        }
        latest_file.write_text(json.dumps(latest_payload, indent=2, default=str, ensure_ascii=False))
        console.print(f"   Latest   → [link=file://{latest_file}]{latest_file.relative_to(PROJECT_ROOT)}[/]")

        # ── Also save the raw captured POST body for debugging ────────────
        if self._captured_request_body:
            debug_file = run_dir / "api_request_body.json"
            debug_file.write_text(json.dumps(self._captured_request_body, indent=2, ensure_ascii=False))
            console.print(f"   API body → [link=file://{debug_file}]{debug_file.relative_to(PROJECT_ROOT)}[/]")

        return jobs
