"""Read-only validation and preview helpers for the supplied CSV datasets."""

import csv
import math
from pathlib import Path


SERVER_COLUMNS = (
    "server_id",
    "cpu_capacity",
    "memory_capacity_gb",
    "initial_temp_c",
    "thermal_limit_c",
    "idle_power_w",
    "max_power_w",
)
JOB_COLUMNS = (
    "job_id",
    "cpu_demand",
    "memory_demand_gb",
    "estimated_runtime_min",
    "priority",
)
VALID_PRIORITIES = {"high", "medium", "low"}


class CSVValidationError(ValueError):
    """Raised when an input CSV is missing or fails validation."""


def load_csv_preview(
    project_root: str | Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Load and validate the project CSVs without converting their units.

    By default paths are rooted at this module's project directory, not the
    process's current working directory. Returned fields remain CSV strings so
    this preview cannot accidentally feed CPU values into abstract work units.
    """
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parent
    errors: list[str] = []
    servers: list[dict[str, str]] = []
    jobs: list[dict[str, str]] = []
    try:
        servers = _read_and_validate(
            root / "data" / "servers.csv",
            SERVER_COLUMNS,
            "server_id",
            8,
            "servers",
        )
    except CSVValidationError as error:
        errors.append(str(error))
    try:
        jobs = _read_and_validate(
            root / "data" / "jobs.csv",
            JOB_COLUMNS,
            "job_id",
            12,
            "jobs",
        )
    except CSVValidationError as error:
        errors.append(str(error))
    if errors:
        raise CSVValidationError(" ".join(errors))
    return servers, jobs


def _read_and_validate(
    path: Path,
    required_columns: tuple[str, ...],
    id_column: str,
    expected_records: int,
    dataset_name: str,
) -> list[dict[str, str]]:
    """Read one CSV, check its schema and values, and return trimmed rows."""
    if not path.is_file():
        raise CSVValidationError(f"Missing {dataset_name} CSV: {path}")
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            columns = reader.fieldnames
            if columns is None:
                raise CSVValidationError(f"{path.name} is empty or has no header row.")
            if len(columns) != len(set(columns)):
                raise CSVValidationError(f"{path.name} has duplicate column names.")
            missing_columns = [name for name in required_columns if name not in columns]
            if missing_columns:
                raise CSVValidationError(
                    f"{path.name} is missing required columns: {', '.join(missing_columns)}."
                )
            raw_rows = list(reader)
    except UnicodeDecodeError as error:
        raise CSVValidationError(f"{path.name} is not valid UTF-8 text.") from error
    except csv.Error as error:
        raise CSVValidationError(f"Could not read {path.name}: {error}") from error

    if len(raw_rows) != expected_records:
        raise CSVValidationError(
            f"{path.name} must contain exactly {expected_records} records; found {len(raw_rows)}."
        )

    rows: list[dict[str, str]] = []
    for row_number, raw in enumerate(raw_rows, start=2):
        if None in raw:
            raise CSVValidationError(f"{path.name}, row {row_number}, has extra values.")
        row = {key: (value or "").strip() for key, value in raw.items() if key is not None}
        # Check every declared CSV column, including any additional fields.
        missing_values = [name for name in row if not row.get(name)]
        if missing_values:
            raise CSVValidationError(
                f"{path.name}, row {row_number}, has missing values in: "
                f"{', '.join(missing_values)}."
            )
        rows.append(row)

    ids = [row[id_column] for row in rows]
    if len(ids) != len(set(ids)):
        raise CSVValidationError(f"{path.name} contains duplicate {id_column} values.")

    numeric_columns = (
        ("cpu_capacity", "memory_capacity_gb", "initial_temp_c", "thermal_limit_c",
         "idle_power_w", "max_power_w")
        if dataset_name == "servers"
        else ("cpu_demand", "memory_demand_gb", "estimated_runtime_min")
    )
    parsed: dict[str, list[float]] = {column: [] for column in numeric_columns}
    for row_number, row in enumerate(rows, start=2):
        for column in numeric_columns:
            try:
                value = float(row[column])
            except (TypeError, ValueError) as error:
                raise CSVValidationError(
                    f"{path.name}, row {row_number}, has an invalid number in {column}."
                ) from error
            if not math.isfinite(value):
                raise CSVValidationError(
                    f"{path.name}, row {row_number}, has a non-finite number in {column}."
                )
            parsed[column].append(value)

    if dataset_name == "servers":
        if any(value <= 0 for value in parsed["cpu_capacity"]):
            raise CSVValidationError("servers.csv CPU capacities must be positive.")
        if any(value <= 0 for value in parsed["memory_capacity_gb"]):
            raise CSVValidationError("servers.csv memory capacities must be positive.")
        if any(value < -273.15 for value in parsed["initial_temp_c"]):
            raise CSVValidationError("servers.csv temperatures cannot be below absolute zero (-273.15 C).")
        if any(value <= 0 for value in parsed["thermal_limit_c"]):
            raise CSVValidationError("servers.csv thermal limits must be positive temperatures.")
        if any(value < 0 for value in parsed["idle_power_w"] + parsed["max_power_w"]):
            raise CSVValidationError("servers.csv power values cannot be negative.")
        if any(maximum < idle for idle, maximum in zip(
                parsed["idle_power_w"], parsed["max_power_w"])):
            raise CSVValidationError("servers.csv max_power_w cannot be below idle_power_w.")
    else:
        for column in ("cpu_demand", "memory_demand_gb", "estimated_runtime_min"):
            if any(value <= 0 for value in parsed[column]):
                raise CSVValidationError(f"jobs.csv {column} values must be positive.")
        unexpected_priorities = sorted(
            {row["priority"] for row in rows if row["priority"] not in VALID_PRIORITIES}
        )
        if unexpected_priorities:
            raise CSVValidationError(
                "jobs.csv priority values must be high, medium, or low; found: "
                + ", ".join(unexpected_priorities)
                + "."
            )
    return rows
