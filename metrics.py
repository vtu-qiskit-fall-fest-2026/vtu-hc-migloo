"""Read-only outcome metrics for ThermoRoute Q simulation runs.

Temperatures, completion times, energy, and assignment costs are simulated
estimates derived from ``simulation.py``. Only ``runtime_seconds`` is measured
wall-clock time on the computer running the algorithm.
"""

from copy import deepcopy
from math import isfinite
from time import perf_counter
from typing import Any, Callable, Mapping, TypeVar

from simulation import (
    SimulationState,
    assign_job,
    estimate_assignment_cost,
)


SIMULATED_THERMAL_LIMIT_C = 75.0
"""Illustrative simulated limit for counting hot virtual servers."""

_Result = TypeVar("_Result")


def is_assignment_valid(
    state: SimulationState,
    assignments: Mapping[str, str] | None = None,
) -> bool:
    """Return whether every job maps exactly once to a known server.

    If ``assignments`` is omitted, the function checks each job's
    ``assigned_server_id`` field. An empty job list is treated as invalid
    because it does not represent a completed scheduling result.
    """
    _validate_state(state)
    if not state.jobs:
        return False
    if assignments is None:
        assignments = {
            job.job_id: job.assigned_server_id
            for job in state.jobs
            if job.assigned_server_id is not None
        }
    if not isinstance(assignments, Mapping):
        return False
    known_jobs = {job.job_id for job in state.jobs}
    known_servers = {server.server_id for server in state.servers}
    return (
        len(assignments) == len(state.jobs)
        and set(assignments) == known_jobs
        and all(isinstance(server_id, str) and server_id in known_servers
                for server_id in assignments.values())
    )


def calculate_metrics(
    state: SimulationState,
    assignments: Mapping[str, str] | None = None,
    runtime_seconds: float | None = None,
    *,
    initial_state: SimulationState | None = None,
) -> dict[str, Any]:
    """Summarize a simulation without modifying its state.

    Makespan is the largest ``queued_workload / processing_capacity`` among
    servers, in simulated processing intervals. Assignment cost sums the
    existing per-server estimate once per job, using the final state as
    provided. If ``initial_state`` is supplied, its separate initial-state
    assignment objective uses the same per-job cost definition, before any
    jobs have been assigned. Cost metrics are ``None`` for invalid assignments.
    An empty job set has zero makespan and energy, but is marked invalid.
    """
    _validate_state(state)
    valid = is_assignment_valid(state, assignments)
    initial_assignment_cost: float | None = None
    if initial_state is not None:
        _validate_state(initial_state)
        if any(job.assigned_server_id is not None for job in initial_state.jobs):
            raise ValueError("initial_state jobs must be unassigned")
        if ({job.job_id for job in initial_state.jobs} != {job.job_id for job in state.jobs}
                or {server.server_id for server in initial_state.servers}
                != {server.server_id for server in state.servers}):
            raise ValueError("initial_state must contain the same jobs and servers")
    if runtime_seconds is not None and (
        isinstance(runtime_seconds, bool)
        or not isinstance(runtime_seconds, (int, float))
        or not isfinite(runtime_seconds)
        or runtime_seconds < 0
    ):
        raise ValueError("runtime_seconds must be a finite non-negative number")

    server_by_id = {server.server_id: server for server in state.servers}
    peak_temperature = max(server.temperature_c for server in state.servers)
    makespan = max(
        server.queued_workload / server.processing_capacity
        for server in state.servers
    )
    energy_total = sum(server.estimated_energy_kwh for server in state.servers)
    assignment_cost: float | None = None
    if valid:
        chosen = assignments
        if chosen is None:
            chosen = {job.job_id: job.assigned_server_id for job in state.jobs}
        assignment_cost = sum(
            estimate_assignment_cost(server_by_id[chosen[job.job_id]])
            for job in state.jobs
        )
        if initial_state is not None:
            initial_server_by_id = {server.server_id: server for server in initial_state.servers}
            initial_assignment_cost = sum(
                estimate_assignment_cost(initial_server_by_id[chosen[job.job_id]])
                for job in state.jobs
            )

    return {
        "peak_temperature_c": peak_temperature,
        "servers_over_thermal_limit": sum(
            server.temperature_c > SIMULATED_THERMAL_LIMIT_C for server in state.servers
        ),
        "thermal_limit_c": SIMULATED_THERMAL_LIMIT_C,
        "makespan_intervals": makespan,
        "total_estimated_energy_kwh": energy_total,
        "total_assignment_cost": assignment_cost,
        "initial_assignment_cost": initial_assignment_cost,
        "assignment_valid": valid,
        "runtime_seconds": runtime_seconds,
    }


def measure_runtime(function: Callable[..., _Result], *args: Any, **kwargs: Any) -> tuple[_Result, float]:
    """Run ``function`` and return its result plus measured wall-clock seconds."""
    if not callable(function):
        raise ValueError("function must be callable")
    started = perf_counter()
    result = function(*args, **kwargs)
    return result, perf_counter() - started


def compare_algorithms(
    algorithms: Mapping[str, Callable[[SimulationState], Any]],
    initial_state: SimulationState,
) -> dict[str, dict[str, Any]]:
    """Run algorithms on independent deep copies of identical starting state.

    Algorithms may return the scheduler assignment dictionary or a result
    object with ``success`` and ``assignments`` fields, as the QAOA optimizer
    does. If a successful algorithm returns assignments without mutating its
    copy, the simulator's ``assign_job`` applies them before metrics are read.
    """
    if not isinstance(algorithms, Mapping) or not algorithms:
        raise ValueError("algorithms must be a non-empty mapping")
    _validate_state(initial_state)
    if any(job.assigned_server_id is not None for job in initial_state.jobs):
        raise ValueError("initial_state jobs must be unassigned for algorithm comparison")
    output: dict[str, dict[str, Any]] = {}
    for name, algorithm in algorithms.items():
        if not isinstance(name, str) or not name or not callable(algorithm):
            raise ValueError("algorithm names must be non-empty and values callable")
        working_state = deepcopy(initial_state)
        result, elapsed = measure_runtime(algorithm, working_state)
        assignments = _extract_assignments(result)
        if assignments is not None and is_assignment_valid(working_state, assignments):
            # QuantumOptimizationResult returns a candidate but leaves state
            # untouched; apply it through the simulator's canonical function.
            if all(job.assigned_server_id is None for job in working_state.jobs):
                for job in working_state.jobs:
                    assign_job(working_state, job.job_id, assignments[job.job_id])
        output[name] = calculate_metrics(
            working_state, assignments, elapsed, initial_state=initial_state
        )
    return output


def _extract_assignments(result: Any) -> Mapping[str, str] | None:
    """Accept either scheduler mappings or successful optimizer results."""
    if isinstance(result, Mapping):
        return result
    if getattr(result, "success", False):
        assignments = getattr(result, "assignments", None)
        if isinstance(assignments, Mapping):
            return assignments
    return None


def _validate_state(state: SimulationState) -> None:
    """Validate metric inputs using the simulator's own server checks."""
    if not isinstance(state, SimulationState):
        raise ValueError("state must be a SimulationState")
    if not state.servers:
        raise ValueError("at least one server is required")
    server_ids = [server.server_id for server in state.servers]
    job_ids = [job.job_id for job in state.jobs]
    if (any(not isinstance(value, str) or not value for value in server_ids + job_ids)
            or len(set(server_ids)) != len(server_ids)
            or len(set(job_ids)) != len(job_ids)):
        raise ValueError("job and server IDs must be non-empty and unique")
    for server in state.servers:
        estimate_assignment_cost(server)
    for job in state.jobs:
        demand = job.processing_demand
        if (isinstance(demand, bool) or not isinstance(demand, (int, float))
                or not isfinite(demand) or demand <= 0):
            raise ValueError("job demands must be finite positive numbers")
