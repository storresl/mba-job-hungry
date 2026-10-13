"""CLI entry point for the MBA Jobs Scraper.

Usage:
    python -m mba_jobs_scraper login                    # Save browser session
    python -m mba_jobs_scraper scrape                   # Scrape job listings
    python -m mba_jobs_scraper scrape --with-details    # Include full job details
    python -m mba_jobs_scraper scrape --visible          # Show browser window
    python -m mba_jobs_scraper explore                  # Open browser + DevTools
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console

from .scraper import TwelveTwentyScraper

console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mba_jobs_scraper",
        description="Scrape job postings from INSEAD's 12twenty portal.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── login ─────────────────────────────────────────────────────────────
    subparsers.add_parser(
        "login",
        help="Open a browser window to log in. Session is saved for future scrapes.",
    )

    # ── scrape ────────────────────────────────────────────────────────────
    scrape_parser = subparsers.add_parser(
        "scrape",
        help="Scrape all job postings from the portal.",
    )
    scrape_parser.add_argument(
        "--with-details",
        action="store_true",
        help="Also fetch full details for each job (description, salary, etc.). Slower.",
    )
    scrape_parser.add_argument(
        "--visible",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    scrape_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Limit the number of jobs to fetch (e.g. 50).",
    )
    scrape_parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Polite delay between requests in seconds (default: 1.5s with jitter).",
    )

    # ── explore ───────────────────────────────────────────────────────────
    subparsers.add_parser(
        "explore",
        help="Open a browser with DevTools for manual API exploration.",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    scraper = TwelveTwentyScraper()

    if args.command == "login":
        asyncio.run(scraper.login())

    elif args.command == "scrape":
        jobs = asyncio.run(
            scraper.scrape(
                with_details=args.with_details,
                headless=not args.visible,
                limit=args.limit,
                delay=args.delay,
            )
        )

        if jobs:
            # Print a quick summary
            console.print("\n[bold]📊 Summary[/]")
            companies = {}
            locations = {}
            for job in jobs:
                ld = job.get("list_data", {})
                company = ld.get("CompanyName", "Unknown")
                location = ld.get("LocationDisplay", "Unknown")
                companies[company] = companies.get(company, 0) + 1
                locations[location] = locations.get(location, 0) + 1

            console.print(f"   Unique companies: [cyan]{len(companies)}[/]")
            console.print(f"   Unique locations: [cyan]{len(locations)}[/]")

            # Top 5 companies
            top_companies = sorted(companies.items(), key=lambda x: x[1], reverse=True)[:5]
            console.print("\n   [bold]Top companies:[/]")
            for name, count in top_companies:
                console.print(f"   • {name} ({count} jobs)")

            # Top 5 locations
            top_locations = sorted(locations.items(), key=lambda x: x[1], reverse=True)[:5]
            console.print("\n   [bold]Top locations:[/]")
            for loc, count in top_locations:
                console.print(f"   • {loc} ({count} jobs)")

            console.print()

    elif args.command == "explore":
        asyncio.run(scraper.explore())


if __name__ == "__main__":
    main()
