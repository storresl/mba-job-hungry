"""
12twenty Job Postings Scraper

Strategy:
  1. Use Playwright with persistent browser context (preserves login session across runs)
  2. Navigate to job listings → triggers the internal POST /Api/V2/job-postings/post-query XHR
  3. Intercept the request to learn the exact POST body format (filters, pagination, etc.)
  4. Replay the API call with modified page numbers via page.evaluate(fetch(...))
  5. For full details, fetch the portal's OCI and core job-posting endpoints
  6. Fall back to clicking each job in the list and intercepting the detail XHR
  7. Export everything to JSON files
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Page,
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

# Pattern matching for XHR interception
POST_QUERY_PATTERN = "job-postings/post-query"
DETAIL_PATTERN = "core-job-postings/"

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SESSION_DIR = PROJECT_ROOT / ".session"
DATA_DIR = PROJECT_ROOT / "data"

MIN_DELAY_SECONDS = 1.0
MAX_REQUEST_ATTEMPTS = 3
RATE_LIMIT_WAIT_SECONDS = 10.0


class TwelveTwentyScraper:
    """Scraper for INSEAD's 12twenty job postings portal.

    Uses Playwright to maintain an authenticated browser session and intercept
    the internal XHR API calls that the 12twenty SPA makes. This gives us clean
    structured JSON without brittle DOM scraping.
    """

    def __init__(self) -> None:
        self._captured_request_body: dict[str, Any] | None = None
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

            console.print(
                "[yellow]Browser is open. Waiting for login... (press Enter when done)[/]"
            )
            loop = asyncio.get_running_loop()
            enter_future = loop.run_in_executor(None, input)

            while not enter_future.done():
                try:
                    if "jobPostings" in page.url:
                        console.print(
                            "   [bold green]✓ Detected Job Postings page! "
                            "Waiting 3s to persist session...[/]"
                        )
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
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than zero")
        if not math.isfinite(delay) or delay < MIN_DELAY_SECONDS:
            raise ValueError(
                f"delay must be at least {MIN_DELAY_SECONDS:.1f} seconds "
                "to avoid overloading the website"
            )

        if not SESSION_DIR.exists():
            console.print("[bold red]❌ No saved session. Run 'login' first.[/]")
            return []

        self._reset_run_state()

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
                console.print(
                    "[bold]Step 1/4:[/] Loading portal & capturing initial API request..."
                )
                first_response = await self._capture_initial_request(page)

                if first_response is None:
                    console.print("[bold red]❌ Failed to capture API response.[/]")
                    console.print("   Your session may be expired. Run [bold]login[/] again.")
                    return []

                page_items = first_response.get("Items") or []
                self._total_jobs = int(first_response.get("Total") or 0)
                self._page_size = int(first_response.get("PageSize") or 50)
                self._add_list_items(page_items)

                # If portal didn't calculate total count (ShouldCalculateTotal was False), query it
                if not self._total_jobs and self._captured_request_body:
                    await self._polite_wait(page, delay)
                    first_page_number = int(self._captured_request_body.get("PageNumber") or 1)
                    total_response = await self._fetch_list_page(
                        page, first_page_number, calculate_total=True
                    )
                    self._total_jobs = int(total_response.get("Total") or 0)

                if not self._total_jobs:
                    self._total_jobs = len(page_items)

                console.print(
                    f"   Found [bold cyan]{self._total_jobs}[/] total jobs in portal "
                    f"(page size: {self._page_size})"
                )
                console.print(f"   Captured [green]{len(page_items)}[/] jobs from page 1")

                # Log a sample of fields so we can understand the data shape
                if page_items:
                    sample = page_items[0]
                    console.print(f"   Sample fields: {', '.join(sample.keys())}")

                # ── Step 2: Paginate (if needed and within limit) ─────────────
                total_target = min(self._total_jobs, limit) if limit else self._total_jobs
                if limit and len(self._list_items) >= limit:
                    self._list_items = self._list_items[:limit]
                    console.print(
                        f"\n[bold]Step 2/4:[/] Target limit of {limit} jobs already "
                        "satisfied by page 1. Skipping extra pages. ✓"
                    )
                else:
                    total_pages = math.ceil(total_target / self._page_size)
                    if total_pages > 1:
                        console.print(
                            f"\n[bold]Step 2/4:[/] Fetching remaining {total_pages - 1} "
                            f"pages (target: {total_target} jobs, delay: {delay:.1f}s)..."
                        )
                        await self._paginate_via_fetch(page, total_pages, limit=limit, delay=delay)
                    else:
                        console.print("\n[bold]Step 2/4:[/] All requested jobs fit on one page. ✓")

                if limit and len(self._list_items) > limit:
                    self._list_items = self._list_items[:limit]

                console.print(
                    f"   Total list items collected: [bold green]{len(self._list_items)}[/]"
                )

                # ── Step 3: Fetch details (optional) ──────────────────────────
                if with_details:
                    console.print(
                        f"\n[bold]Step 3/4:[/] Fetching details for "
                        f"{len(self._list_items)} jobs "
                        f"(polite delay: {delay:.1f}s with jitter)..."
                    )
                    await self._fetch_details(page, delay=delay)
                    console.print(f"   Details collected: [bold green]{len(self._details)}[/]")
                else:
                    console.print(
                        "\n[bold]Step 3/4:[/] Skipping details (use --with-details to include)."
                    )

                # ── Step 4: Export ────────────────────────────────────────────
                console.print("\n[bold]Step 4/4:[/] Exporting data...")
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
                args=[
                    "--auto-open-devtools-for-tabs",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(JOB_LISTINGS_URL)

            await asyncio.get_running_loop().run_in_executor(None, input)
            await context.close()

    def _reset_run_state(self) -> None:
        """Clear state so one scraper instance can safely perform multiple runs."""
        self._captured_request_body = None
        self._list_items.clear()
        self._details.clear()
        self._total_jobs = 0
        self._page_size = 50

    # ── Private: API Capture ──────────────────────────────────────────────────

    async def _capture_initial_request(self, page: Page) -> dict[str, Any] | None:
        """Navigate to job listings and capture the first post-query request + response.

        We intercept both the request (to learn the POST body format) and the response
        (to get the first page of data and the total count).
        """
        captured: dict[str, Any] = {
            "response": None,
            "request_body": None,
        }

        async def on_response(response: Response) -> None:
            if POST_QUERY_PATTERN in response.url and response.request.method == "POST":
                try:
                    body_text = response.request.post_data or "{}"
                    data = json.loads(body_text)
                    # Ignore the small, unrelated recommended-jobs widget query.
                    if data.get("IsRecommended"):
                        return
                    res_json = await response.json()
                    if isinstance(res_json, dict) and "Items" in res_json:
                        captured["response"] = res_json
                        captured["request_body"] = body_text
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(JOB_LISTINGS_URL, wait_until="networkidle", timeout=30000)
        except Exception as e:
            console.print(f"   [yellow]Navigation warning: {e}[/]")

        # Wait for the main query XHR to complete (up to 15 seconds)
        for _ in range(30):
            if captured["response"] is not None:
                break
            await page.wait_for_timeout(500)

        # Store the captured request format for replay
        if captured["request_body"]:
            try:
                self._captured_request_body = json.loads(captured["request_body"])
                request_preview = json.dumps(self._captured_request_body, indent=2)[:500]
                console.print(f"   [dim]Captured POST body: {request_preview}[/]")
            except (json.JSONDecodeError, TypeError):
                console.print("   [yellow]Could not parse request body as JSON[/]")

        # Clean up listener
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
            console.print(
                "   [yellow]⚠ No captured request body — falling back to scroll pagination.[/]"
            )
            await self._paginate_via_scroll(page)
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
                    result = await self._fetch_list_page(page, page_num)
                    if result.get("_error"):
                        console.print(f"\n   [red]Error on page {page_num}: {result}[/]")
                        console.print("   Falling back to scroll pagination...")
                        await self._paginate_via_scroll(page)
                        return

                    items = result.get("Items") or []
                    added = self._add_list_items(items)
                    progress.update(
                        task,
                        advance=1,
                        description=f"  Page {page_num}/{total_pages} (+{added} jobs)",
                    )

                    if limit and len(self._list_items) >= limit:
                        break

                    await self._polite_wait(page, delay)

                except Exception as e:
                    console.print(f"\n   [red]Error on page {page_num}: {e}[/]")
                    break

    async def _fetch_list_page(
        self, page: Page, page_num: int, *, calculate_total: bool = False
    ) -> dict[str, Any]:
        """Fetch one listing page, retrying transient failures with backoff."""
        if self._captured_request_body is None:
            return {"_error": True, "message": "missing request body"}

        body = dict(self._captured_request_body)
        body["PageNumber"] = page_num
        if calculate_total:
            body["ShouldCalculateTotal"] = True

        result: dict[str, Any] = {"_error": True, "message": "request not attempted"}
        for attempt in range(MAX_REQUEST_ATTEMPTS):
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
                            return {
                                _error: true,
                                status: response.status,
                                statusText: response.statusText,
                            };
                        }
                        return await response.json();
                    } catch (error) {
                        return {_error: true, message: error.message};
                    }
                }""",
                {"url": POST_QUERY_URL, "body": body},
            )

            status = result.get("status")
            if not result.get("_error") or not self._is_retryable_status(status):
                return result

            if attempt + 1 == MAX_REQUEST_ATTEMPTS:
                return result

            wait_seconds = self._backoff_seconds(attempt)
            console.print(
                f"\n   [yellow]⚠ Request throttled or unavailable (HTTP {status}) "
                f"on page {page_num}. Retrying in {wait_seconds:.1f}s...[/]"
            )
            await asyncio.sleep(wait_seconds)

        return result

    async def _paginate_via_scroll(self, page: Page) -> None:
        """Fallback: trigger pagination by scrolling the page (for infinite scroll UIs)."""
        console.print("   [dim]Using scroll-based pagination...[/]")
        max_no_new_data = 5
        no_new_data_count = 0
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
                added = self._add_list_items(new_items)
                console.print(f"   Scroll: +{added} jobs (total: {len(self._list_items)})")
                no_new_data_count = 0 if added else no_new_data_count + 1
            else:
                no_new_data_count += 1

    @staticmethod
    def _is_retryable_status(status: Any) -> bool:
        return status == 429 or isinstance(status, int) and status >= 500

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        return RATE_LIMIT_WAIT_SECONDS * (2**attempt) + random.uniform(0.0, 1.0)

    @staticmethod
    async def _polite_wait(page: Page, delay: float) -> None:
        jitter_ms = int(random.uniform(0.85, 1.25) * delay * 1000)
        await page.wait_for_timeout(jitter_ms)

    def _add_list_items(self, items: list[dict[str, Any]]) -> int:
        """Add new items to _list_items, skipping any duplicate IDs."""
        existing_ids = {str(item.get("Id", "")) for item in self._list_items}
        added = 0
        for item in items:
            item_id = str(item.get("Id", ""))
            if item_id and item_id not in existing_ids:
                self._list_items.append(item)
                existing_ids.add(item_id)
                added += 1
        return added

    # ── Private: Detail Fetching & Caching ─────────────────────────────────────

    def _load_cached_details(self) -> dict[str, tuple[str | None, dict[str, Any]]]:
        """Load previously scraped job details from latest.json and recent run files.

        Returns:
            Dictionary mapping job_id (str) -> (ModifyDate, detail_data).
        """
        cache: dict[str, tuple[str | None, dict[str, Any]]] = {}

        candidate_files: list[Path] = []
        latest_file = DATA_DIR / "latest.json"
        if latest_file.exists():
            candidate_files.append(latest_file)

        runs_dir = DATA_DIR / "runs"
        if runs_dir.exists():
            run_files = sorted(runs_dir.glob("*/*.json"), reverse=True)
            candidate_files.extend(f for f in run_files if f.name != "api_request_body.json")

        for filepath in candidate_files:
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                for job in data.get("jobs", []):
                    job_id = str(job.get("id") or "")
                    detail_data = job.get("detail_data")
                    if not job_id or not detail_data:
                        continue
                    if job_id not in cache:
                        list_data = job.get("list_data") or {}
                        modify_date = list_data.get("ModifyDate")
                        cache[job_id] = (modify_date, detail_data)
            except Exception:
                continue

        return cache

    async def _fetch_details(self, page: Page, delay: float = 1.5) -> None:
        """Fetch full details for each job, reusing cached details where ModifyDate is unchanged.

        Strategy:
          1. Load previously scraped details from data/latest.json (and recent run files).
          2. Reuse details when the job's ModifyDate is unchanged.
          3. Fetch new or modified jobs from the OCI and core job-posting APIs.
          4. Fall back to UI clicks only if direct API access fails.
        """
        if not self._list_items:
            return

        # 1. Load cached details
        cached = self._load_cached_details()
        cached_count = 0

        for item in self._list_items:
            job_id = str(item.get("Id", ""))
            current_modify_date = item.get("ModifyDate")

            if job_id in cached:
                cached_modify_date, cached_detail = cached[job_id]
                if (
                    cached_detail
                    and current_modify_date is not None
                    and cached_modify_date == current_modify_date
                ):
                    self._details[job_id] = cached_detail
                    cached_count += 1

        if cached_count > 0:
            console.print(
                f"   [bold green]✓ Reusing cached details for "
                f"{cached_count}/{len(self._list_items)} jobs[/] "
                f"(ModifyDate unchanged since last scrape)."
            )

        # 2. Filter remaining jobs that need detail fetching
        remaining = [
            item for item in self._list_items if str(item.get("Id", "")) not in self._details
        ]

        if not remaining:
            console.print(
                "   [bold green]✓ All jobs have up-to-date cached details. "
                "Skipping network fetch.[/]"
            )
            return

        console.print(
            f"   Fetching details for [cyan]{len(remaining)}[/] new/modified jobs "
            f"(delay: {delay:.1f}s)..."
        )

        failed = await self._fetch_details_direct(page, remaining=remaining, delay=delay)
        if failed:
            console.print(
                f"   [yellow]Using browser click-through fallback for {len(failed)} jobs...[/]"
            )
            await self._fetch_details_via_clicks(page, remaining=failed, delay=delay)

    async def _fetch_details_direct(
        self, page: Page, remaining: list[dict[str, Any]], delay: float = 1.5
    ) -> list[dict[str, Any]]:
        """Fast path: GET each job's details directly via the internal API with polite pacing."""
        failed: list[dict[str, Any]] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("  Fetching details...", total=len(remaining))

            for index, item in enumerate(remaining):
                job_id = str(item.get("Id", ""))
                title = item.get("TitleDisplay", "?")[:40]

                try:
                    result = await self._fetch_detail(page, job_id, title)
                    if not result.get("_error"):
                        self._details[job_id] = result
                    else:
                        failed.append(item)
                        console.print(f"\n   [dim red]Failed: {title} → {result}[/]")
                        if index == 0:
                            failed.extend(remaining[1:])
                            break

                except Exception as e:
                    failed.append(item)
                    console.print(f"\n   [dim red]Error for {title}: {e}[/]")

                progress.update(task, advance=1, description=f"  {title}")

                await self._polite_wait(page, delay)

        return failed

    async def _fetch_detail(self, page: Page, job_id: str, title: str) -> dict[str, Any]:
        """Fetch one job detail, with bounded retries for throttling and server errors."""
        result: dict[str, Any] = {"_error": True, "message": "request not attempted"}

        for attempt in range(MAX_REQUEST_ATTEMPTS):
            result = await page.evaluate(
                """async (jobId) => {
                    try {
                        const ociUrl =
                            '/Api/V2/OciContainer/' + jobId +
                            '?isInitialLoad=true&isPromoted=false';
                        const options = {credentials: 'same-origin'};
                        const ociResponse = await fetch(ociUrl, options);
                        if (!ociResponse.ok) {
                            return {_error: true, status: ociResponse.status};
                        }
                        const oci = await ociResponse.json();

                        const jobPosting = oci.JobPosting || {};
                        const coreId = jobPosting.ExternalJobPostingSourceId;
                        const signature = encodeURIComponent(
                            jobPosting.CoreJobPostingSignature || ''
                        );
                        let core = null;
                        if (coreId && signature) {
                            const coreUrl =
                                '/api/internal/core-job-postings/' + coreId +
                                '?signature=' + signature;
                            const coreResponse = await fetch(coreUrl, options);
                            if (
                                coreResponse.status === 429 ||
                                coreResponse.status >= 500
                            ) {
                                return {_error: true, status: coreResponse.status};
                            }
                            if (coreResponse.ok) {
                                core = await coreResponse.json();
                            }
                        }
                        return {
                            oci: oci,
                            core: core,
                            job_posting: jobPosting,
                            description: core
                                ? core.Description
                                : (jobPosting.JobDescription || null),
                        };
                    } catch (error) {
                        return {_error: true, message: error.message};
                    }
                }""",
                job_id,
            )

            status = result.get("status")
            if not result.get("_error") or not self._is_retryable_status(status):
                return result

            if attempt + 1 == MAX_REQUEST_ATTEMPTS:
                return result

            wait_seconds = self._backoff_seconds(attempt)
            console.print(
                f"\n   [yellow]⚠ Request throttled or unavailable (HTTP {status}) "
                f"for {title}. Retrying in {wait_seconds:.1f}s...[/]"
            )
            await asyncio.sleep(wait_seconds)

        return result

    async def _fetch_details_via_clicks(
        self, page: Page, remaining: list[dict[str, Any]] | None = None, delay: float = 1.5
    ) -> None:
        """Slow path: click each job in the list and intercept the detail XHR response."""
        target_items = remaining if remaining is not None else self._list_items
        if not target_items:
            return

        remaining_ids = {str(item.get("Id", "")) for item in target_items}
        remaining_ids.discard("")
        if not remaining_ids:
            return

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
            task = progress.add_task("  Clicking through jobs...", total=len(remaining_ids))
            pages_visited = 0
            max_pages = max(1, math.ceil(self._total_jobs / self._page_size))

            while remaining_ids and pages_visited < max_pages:
                pages_visited += 1
                job_rows = await page.query_selector_all(
                    "[class*='job-posting-row'], "
                    "[class*='jobPosting'], "
                    "tr[data-id], "
                    ".posting-item, "
                    "a[href*='jobPosting']"
                )

                if not job_rows:
                    job_rows = await page.query_selector_all("a[class*='title'], .list-group-item")

                if not job_rows:
                    console.print("\n   [yellow]Could not find clickable job rows[/]")
                    break

                for row in job_rows:
                    if not remaining_ids:
                        break

                    detail_data: dict[str, Any] = {}

                    async def on_response(response: Response) -> None:
                        if (
                            DETAIL_PATTERN in response.url
                            and POST_QUERY_PATTERN not in response.url
                        ):
                            try:
                                data = await response.json()
                                if isinstance(data, dict) and "Id" in data:
                                    detail_data["result"] = data
                            except Exception:
                                pass

                    page.on("response", on_response)

                    try:
                        await row.click()
                        for _ in range(10):
                            if "result" in detail_data:
                                break
                            await page.wait_for_timeout(500)

                        if "result" in detail_data:
                            detail = detail_data["result"]
                            job_id = str(detail.get("Id", ""))
                            if job_id in remaining_ids:
                                self._details[job_id] = detail
                                remaining_ids.remove(job_id)
                                title = detail.get("JobTitle", "?")[:40]
                                progress.update(task, advance=1, description=f"  {title}")

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

                        await self._polite_wait(page, delay)

                    except Exception as e:
                        console.print(f"\n   [dim red]Click error: {e}[/]")

                    finally:
                        page.remove_listener("response", on_response)

                next_btn = await page.query_selector(
                    "[class*='next'], a[aria-label='Next'], .pagination-next"
                )
                if next_btn and remaining_ids and await next_btn.is_enabled():
                    await next_btn.click()
                    await page.wait_for_timeout(2000)
                else:
                    break

        if remaining_ids:
            console.print(f"   [yellow]Could not fetch details for {len(remaining_ids)} jobs.[/]")

    # ── Private: Export ───────────────────────────────────────────────────────

    def _export(self) -> list[dict[str, Any]]:
        """Merge list items with detail data and save to JSON files."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        now = datetime.now(UTC)
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%S-%f")
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

        job_ids = [job["id"] for job in jobs]
        if len(job_ids) != len(set(job_ids)):
            raise RuntimeError("refusing to export duplicate job IDs")

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
        self._write_json(run_file, run_payload)
        console.print(
            f"   Run data → [link=file://{run_file}]{run_file.relative_to(PROJECT_ROOT)}[/]"
        )

        # ── Save latest (always overwritten) ──────────────────────────────
        latest_file = DATA_DIR / "latest.json"
        latest_payload = {
            "scraped_at": now.isoformat(),
            "total_jobs": len(jobs),
            "total_with_details": sum(1 for j in jobs if j.get("detail_data")),
            "jobs": jobs,
        }
        self._write_json(latest_file, latest_payload)
        console.print(
            f"   Latest   → [link=file://{latest_file}]{latest_file.relative_to(PROJECT_ROOT)}[/]"
        )

        # ── Also save the raw captured POST body for debugging ────────────
        if self._captured_request_body:
            debug_file = run_dir / "api_request_body.json"
            self._write_json(debug_file, self._captured_request_body)
            console.print(
                f"   API body → [link=file://{debug_file}]{debug_file.relative_to(PROJECT_ROOT)}[/]"
            )

        return jobs

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        """Atomically replace a JSON file so interrupted runs cannot corrupt it."""
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        serialized = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
        temporary_path.write_text(f"{serialized}\n", encoding="utf-8")
        temporary_path.replace(path)
