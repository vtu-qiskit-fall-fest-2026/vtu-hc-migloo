"""Small, deterministic simulator for ThermoRoute Q's virtual servers.

All temperatures, queue values, and energy figures in this module are
illustrative estimates. They are not hardware telemetry or measured energy.
"""

from dataclasses import asdict, dataclass
import math
import random
from typing import Any


@dataclass
class Server:
    """One virtual server and its simulated operating state."""

    server_id: str
    temperature_c: float
    processing_capacity: float
    queued_workload: float = 0.0
    estimated_energy_kwh: float = 0.0


@dataclass
class Job:
    """A generated job whose demand is measured in simulated work units."""

    job_id: str
    processing_demand: float
    assigned_server_id: str | None = None


@dataclass
class SimulationState:
    """Collection of servers and jobs for use by other project modules."""

    servers: list[Server]
    jobs: list[Job]


def create_servers() -> list[Server]:
    """Create eight servers with stable, varied simulated starting values.

    Capacities are work units per simulation interval. Initial temperatures
    are between 38 and 57 C and have no connection to real equipment.
    """
    temperatures = (38.0, 41.5, 45.0, 48.5, 52.0, 55.0, 43.0, 50.0)
    capacities = (120.0, 135.0, 150.0, 165.0, 180.0, 195.0, 145.0, 175.0)
    return [
        Server(f"server-{index + 1}", temperatures[index], capacities[index])
        for index in range(8)
    ]


def generate_jobs(count: int, seed: int) -> list[Job]:
    """Generate ``count`` reproducible jobs with demands from 10 to 80 units."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("count must be a non-negative integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    return [Job(f"job-{index + 1}", float(rng.randint(10, 80))) for index in range(count)]


def estimate_assignment_cost(server: Server) -> float:
    """Return a dimensionless cost from normalized thermal, queue, and energy.

    The three components have equal weight. Thermal stress maps 20..100 C
    to 0..1, queue delay maps 0..one capacity interval to 0..1, and energy
    maps 0..5 simulated kWh to 0..1. Each component is clamped to that range.
    """
    _validate_server(server)
    thermal = _clamp((server.temperature_c - 20.0) / 80.0)
    queue = _clamp(server.queued_workload / server.processing_capacity)
    energy = _clamp(server.estimated_energy_kwh / 5.0)
    return (thermal + queue + energy) / 3.0


def assign_job(state: SimulationState, job_id: str, server_id: str) -> None:
    """Assign an existing unassigned job and update simulated server estimates.

    Queue grows by the job demand. Temperature rises by up to 4 C per job
    depending on demand relative to capacity. Estimated energy adds 0.02 kWh
    per demand unit, scaled by utilization. These are simple simulation rules.
    """
    server = next((item for item in state.servers if item.server_id == server_id), None)
    if server is None:
        raise ValueError(f"unknown server ID: {server_id}")
    job = next((item for item in state.jobs if item.job_id == job_id), None)
    if job is None:
        raise ValueError(f"unknown job ID: {job_id}")
    _validate_demand(job.processing_demand)
    _validate_server(server)
    if job.assigned_server_id is not None:
        raise ValueError(f"job {job_id} has already been assigned")

    utilization = job.processing_demand / server.processing_capacity
    server.queued_workload += job.processing_demand
    server.temperature_c += min(4.0, utilization * 4.0)
    server.estimated_energy_kwh += job.processing_demand * 0.02 * min(1.0, utilization)
    job.assigned_server_id = server_id


def state_to_dict(state: SimulationState) -> dict[str, Any]:
    """Return a plain-dictionary snapshot of a simulation state."""
    return {"servers": [asdict(server) for server in state.servers],
            "jobs": [asdict(job) for job in state.jobs]}


def _validate_demand(demand: float) -> None:
    if isinstance(demand, bool) or not isinstance(demand, (int, float)) or not math.isfinite(demand) or demand <= 0:
        raise ValueError("processing demand must be a finite positive number")


def _validate_server(server: Server) -> None:
    values = (server.temperature_c, server.processing_capacity,
              server.queued_workload, server.estimated_energy_kwh)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in values):
        raise ValueError("server values must be finite numbers")
    if server.processing_capacity <= 0 or server.queued_workload < 0 or server.estimated_energy_kwh < 0:
        raise ValueError("capacity must be positive and queue/energy cannot be negative")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
