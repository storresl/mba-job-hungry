"""Offline tests for scraper behavior that does not require a portal session."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mba_jobs_scraper.__main__ import polite_delay, positive_int
from mba_jobs_scraper.scraper import TwelveTwentyScraper


class ScraperTests(unittest.TestCase):
    def test_add_list_items_deduplicates_by_id(self) -> None:
        scraper = TwelveTwentyScraper()

        first_added = scraper._add_list_items([{"Id": 1}, {"Id": 2}, {"Id": 1}])
        second_added = scraper._add_list_items([{"Id": "2"}, {"Id": 3}, {}])

        self.assertEqual(first_added, 2)
        self.assertEqual(second_added, 1)
        self.assertEqual([item["Id"] for item in scraper._list_items], [1, 2, 3])

    def test_reset_run_state_clears_previous_results(self) -> None:
        scraper = TwelveTwentyScraper()
        scraper._captured_request_body = {"PageNumber": 1}
        scraper._list_items = [{"Id": 1}]
        scraper._details = {"1": {"Description": "Example"}}
        scraper._total_jobs = 1

        scraper._reset_run_state()

        self.assertIsNone(scraper._captured_request_body)
        self.assertEqual(scraper._list_items, [])
        self.assertEqual(scraper._details, {})
        self.assertEqual(scraper._total_jobs, 0)

    def test_retryable_statuses_are_limited_to_throttling_and_server_errors(self) -> None:
        self.assertTrue(TwelveTwentyScraper._is_retryable_status(429))
        self.assertTrue(TwelveTwentyScraper._is_retryable_status(503))
        self.assertFalse(TwelveTwentyScraper._is_retryable_status(401))
        self.assertFalse(TwelveTwentyScraper._is_retryable_status(None))

    def test_write_json_produces_valid_file_without_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jobs.json"

            TwelveTwentyScraper._write_json(output, {"jobs": [{"id": "1"}]})

            self.assertEqual(json.loads(output.read_text()), {"jobs": [{"id": "1"}]})
            self.assertFalse(output.with_suffix(".json.tmp").exists())

    def test_export_refuses_duplicate_ids(self) -> None:
        scraper = TwelveTwentyScraper()
        scraper._list_items = [{"Id": 1}, {"Id": 1}]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("mba_jobs_scraper.scraper.PROJECT_ROOT", root),
                patch("mba_jobs_scraper.scraper.DATA_DIR", root / "data"),
                self.assertRaisesRegex(RuntimeError, "duplicate job IDs"),
            ):
                scraper._export()


class CliValidationTests(unittest.TestCase):
    def test_positive_int(self) -> None:
        self.assertEqual(positive_int("5"), 5)
        with self.assertRaises(argparse.ArgumentTypeError):
            positive_int("0")

    def test_polite_delay(self) -> None:
        self.assertEqual(polite_delay("1.5"), 1.5)
        with self.assertRaises(argparse.ArgumentTypeError):
            polite_delay("0.5")
        with self.assertRaises(argparse.ArgumentTypeError):
            polite_delay("nan")


if __name__ == "__main__":
    unittest.main()
