"""Classical scheduling strategies for the ThermoRoute Q simulator."""

from simulation import SimulationState, assign_job, estimate_assignment_cost


def schedule_round_robin(state: SimulationState) -> dict[str, str]:
    """Assign jobs to servers in a rotating order and return job-to-server IDs."""
    _validate_state(state)
    assignments: dict[str, str] = {}
    server_count = len(state.servers)
    for index, job in enumerate(state.jobs):
        server = state.servers[index % server_count]
        assign_job(state, job.job_id, server.server_id)
        assignments[job.job_id] = server.server_id
    return assignments


def schedule_performance_first(state: SimulationState) -> dict[str, str]:
    """Prefer high-capacity servers, accounting for work already queued.

    For each job, choose the server with the lowest projected completion
    interval: (queued workload + job demand) / processing capacity. Stable
    server list order breaks ties, keeping outcomes deterministic.
    """
    _validate_state(state)
    assignments: dict[str, str] = {}
    for job in state.jobs:
        server = min(
            state.servers,
            key=lambda item: (
                (item.queued_workload + job.processing_demand) / item.processing_capacity
            ),
        )
        assign_job(state, job.job_id, server.server_id)
        assignments[job.job_id] = server.server_id
    return assignments


def schedule_thermal_aware(state: SimulationState) -> dict[str, str]:
    """Choose the server with the lowest existing simulated assignment cost."""
    _validate_state(state)
    assignments: dict[str, str] = {}
    for job in state.jobs:
        server = min(state.servers, key=estimate_assignment_cost)
        assign_job(state, job.job_id, server.server_id)
        assignments[job.job_id] = server.server_id
    return assignments


def _validate_state(state: SimulationState) -> None:
    """Reject states that cannot be scheduled safely and deterministically."""
    if not isinstance(state, SimulationState):
        raise ValueError("state must be a SimulationState")
    if not state.servers:
        raise ValueError("at least one server is required")
    server_ids = [server.server_id for server in state.servers]
    if any(not isinstance(server_id, str) or not server_id for server_id in server_ids):
        raise ValueError("every server must have a non-empty string ID")
    if len(set(server_ids)) != len(server_ids):
        raise ValueError("server IDs must be unique")
    job_ids = [job.job_id for job in state.jobs]
    if any(not isinstance(job_id, str) or not job_id for job_id in job_ids):
        raise ValueError("every job must have a non-empty string ID")
    if len(set(job_ids)) != len(job_ids):
        raise ValueError("job IDs must be unique")
    if any(job.assigned_server_id is not None for job in state.jobs):
        raise ValueError("all jobs must be unassigned before scheduling")
    # The assignment function performs detailed demand and server value checks;
    # validate all entries before making any changes to avoid partial schedules.
    for job in state.jobs:
        if (isinstance(job.processing_demand, bool)
                or not isinstance(job.processing_demand, (int, float))
                or job.processing_demand <= 0):
            raise ValueError("job processing demand must be a positive number")
    for server in state.servers:
        estimate_assignment_cost(server)  # Applies the simulator's server validation.
