"""Focused tests for read-only CSV validation and preview loading."""

import csv
import os
from pathlib import Path
import tempfile
import unittest

from csv_preview import (
    JOB_COLUMNS,
    SERVER_COLUMNS,
    CSVValidationError,
    load_csv_preview,
)

PROJECT_ROOT = Path(__file__).resolve().parent


def valid_server_rows():
    return [
        {
            "server_id": f"S{index + 1}",
            "cpu_capacity": "8",
            "memory_capacity_gb": "32",
            "initial_temp_c": "45",
            "thermal_limit_c": "80",
            "idle_power_w": "50",
            "max_power_w": "100",
        }
        for index in range(8)
    ]


def valid_job_rows():
    priorities = ("high", "medium", "low")
    return [
        {
            "job_id": f"J{index + 1}",
            "cpu_demand": "2",
            "memory_demand_gb": "4",
            "estimated_runtime_min": "10",
            "priority": priorities[index % len(priorities)],
        }
        for index in range(12)
    ]


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_datasets(
    root: Path,
    servers: list[dict[str, str]] | None = None,
    jobs: list[dict[str, str]] | None = None,
    server_columns: tuple[str, ...] = SERVER_COLUMNS,
    job_columns: tuple[str, ...] = JOB_COLUMNS,
) -> None:
    data_dir = root / "data"
    write_csv(data_dir / "servers.csv", server_columns,
              valid_server_rows() if servers is None else servers)
    write_csv(data_dir / "jobs.csv", job_columns,
              valid_job_rows() if jobs is None else jobs)


class CSVPreviewTests(unittest.TestCase):
    def test_project_datasets_load_independent_of_current_directory(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            os.chdir(temporary)
            try:
                servers, jobs = load_csv_preview()
            finally:
                os.chdir(original_cwd)
        self.assertEqual(len(servers), 8)
        self.assertEqual(len(jobs), 12)
        self.assertEqual(servers[0]["cpu_capacity"], "16")
        self.assertEqual(jobs[0]["priority"], "high")

    def test_missing_files_are_reported_clearly(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            with self.assertRaisesRegex(CSVValidationError, "Missing servers CSV") as error:
                load_csv_preview(temporary)
            self.assertIn("Missing jobs CSV", str(error.exception))

    def test_wrong_record_count_and_missing_column_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            write_datasets(root, servers=valid_server_rows()[:-1])
            with self.assertRaisesRegex(CSVValidationError, "exactly 8 records"):
                load_csv_preview(root)

        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            write_datasets(root, server_columns=SERVER_COLUMNS[:-1])
            with self.assertRaisesRegex(CSVValidationError, "max_power_w"):
                load_csv_preview(root)

    def test_missing_values_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            rows = valid_server_rows()
            rows[0]["server_id"] = ""
            write_datasets(root, servers=rows)
            with self.assertRaisesRegex(CSVValidationError, "missing values"):
                load_csv_preview(root)

        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            rows = valid_job_rows()
            rows[1]["job_id"] = rows[0]["job_id"]
            write_datasets(root, jobs=rows)
            with self.assertRaisesRegex(CSVValidationError, "duplicate job_id"):
                load_csv_preview(root)

    def test_invalid_numbers_nonpositive_resources_and_temperature_are_rejected(self):
        invalid_cases = (
            ("cpu_capacity", "not-a-number", "invalid number"),
            ("cpu_capacity", "0", "CPU capacities must be positive"),
            ("memory_capacity_gb", "0", "memory capacities must be positive"),
            ("initial_temp_c", "-300", "below absolute zero"),
        )
        for field, value, message in invalid_cases:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
                root = Path(temporary)
                rows = valid_server_rows()
                rows[0][field] = value
                write_datasets(root, servers=rows)
                with self.assertRaisesRegex(CSVValidationError, message):
                    load_csv_preview(root)

        for field, value, message in (
            ("cpu_demand", "0", "cpu_demand values must be positive"),
            ("memory_demand_gb", "-1", "memory_demand_gb values must be positive"),
            ("estimated_runtime_min", "NaN", "non-finite number"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
                root = Path(temporary)
                rows = valid_job_rows()
                rows[0][field] = value
                write_datasets(root, jobs=rows)
                with self.assertRaisesRegex(CSVValidationError, message):
                    load_csv_preview(root)

    def test_unexpected_priority_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temporary:
            root = Path(temporary)
            rows = valid_job_rows()
            rows[0]["priority"] = "urgent"
            write_datasets(root, jobs=rows)
            with self.assertRaisesRegex(CSVValidationError, "high, medium, or low"):
                load_csv_preview(root)


if __name__ == "__main__":
    unittest.main()
