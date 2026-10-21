"""A small QAOA job-to-server assignment optimizer using Qiskit Aer.

This is a software simulation of QAOA. It does not control quantum hardware.
The binary model has one bit per job/server pair. Its objective applies each
valid assignment to a copied simulation state, then sums the selected servers'
estimated costs in that projected final state. Invalid assignments receive a
penalty larger than any valid total cost.
"""

from dataclasses import dataclass
from copy import deepcopy
import math
from typing import Any

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import DiagonalGate
from qiskit_aer import AerSimulator
from scipy.optimize import minimize

from simulation import SimulationState, assign_job, estimate_assignment_cost


_INVALID_ASSIGNMENT_PENALTY = 5.0
_MAX_QUBITS = 16  # Keep the first version small enough for local statevector runs.


@dataclass
class QuantumOptimizationResult:
    """Result of a QAOA run, including a safe no-solution outcome."""

    success: bool
    assignments: dict[str, str]
    objective_value: float | None
    message: str
    counts: dict[str, int]


def optimize_assignments(
    state: SimulationState,
    *,
    shots: int = 512,
    reps: int = 1,
    seed: int = 7,
) -> QuantumOptimizationResult:
    """Use QAOA on Aer to sample job-to-server assignments.

    The one-hot constraint penalty is greater than the maximum possible valid
    total cost. QAOA angles are tuned with a small classical COBYLA search over
    exact Aer statevector expectations; the reported candidate itself always
    comes from Aer shots.
    Inputs are intentionally capped at 16 binary variables for local use.
    The provided state is only read and is never modified.
    """
    _validate_inputs(state, shots, reps, seed)
    if not state.jobs:
        return QuantumOptimizationResult(False, {}, None, "No jobs were provided.", {})

    servers = state.servers
    jobs = state.jobs
    qubit_count = len(servers) * len(jobs)
    if qubit_count > _MAX_QUBITS:
        raise ValueError(
            f"problem has {qubit_count} assignment variables; maximum is {_MAX_QUBITS}"
        )

    energies = _make_energy_table(state)
    backend = AerSimulator(method="statevector", seed_simulator=seed)

    def circuit_for(gammas: np.ndarray, betas: np.ndarray, measure: bool = False) -> QuantumCircuit:
        circuit = QuantumCircuit(qubit_count, qubit_count if measure else 0)
        circuit.h(range(qubit_count))
        for layer in range(reps):
            # The diagonal phase applies the complete assignment objective,
            # including the one-server-per-job penalty.
            phases = np.exp(-1j * gammas[layer] * energies)
            circuit.append(DiagonalGate(phases), range(qubit_count))
            for qubit in range(qubit_count):
                circuit.rx(2.0 * betas[layer], qubit)
        if measure:
            circuit.measure(range(qubit_count), range(qubit_count))
        else:
            circuit.save_statevector()
        return circuit

    def expected_energy(parameters: np.ndarray) -> float:
        gammas = parameters[:reps]
        betas = parameters[reps:]
        circuit = transpile(circuit_for(gammas, betas), backend)
        statevector = backend.run(circuit, shots=1).result().get_statevector()
        probabilities = np.abs(np.asarray(statevector)) ** 2
        return float(np.dot(probabilities, energies))

    rng = np.random.default_rng(seed)
    initial = rng.uniform(0.1, 0.9, size=2 * reps)
    search = minimize(
        expected_energy,
        initial,
        method="COBYLA",
        options={"maxiter": 20, "rhobeg": 0.3, "tol": 0.03},
    )
    gammas = search.x[:reps]
    betas = search.x[reps:]

    measured = transpile(circuit_for(gammas, betas, measure=True), backend)
    counts: dict[str, int] = backend.run(measured, shots=shots).result().get_counts()
    candidates = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    valid_candidates: list[tuple[float, int, str, dict[str, int]]] = []
    for bitstring, frequency in candidates:
        assignments = _decode_candidate(bitstring, jobs, servers)
        if assignments is not None and _is_valid_candidate(assignments, state):
            # Qiskit displays measured bits most-significant first, so parsing
            # the displayed string gives the little-endian basis-state index.
            cost = float(energies[int(bitstring, 2)])
            valid_candidates.append((float(cost), -frequency, bitstring, assignments))

    if valid_candidates:
        # Among samples QAOA actually produced, return the lowest-cost valid one.
        cost, _negative_frequency, _bitstring, assignment_indices = min(valid_candidates)
        return QuantumOptimizationResult(
            True,
            {job.job_id: servers[assignment_indices[job.job_id]].server_id for job in jobs},
            cost,
            "Valid assignment sampled by QAOA.",
            counts,
        )

    return QuantumOptimizationResult(
        False, {}, None,
        "QAOA did not sample a valid one-server-per-job assignment.",
        counts,
    )


def _make_energy_table(state: SimulationState) -> np.ndarray:
    """Build projected-final-state cost for valid one-hot basis assignments.

    Qubit ``job_index * server_count + server_index`` represents a job/server
    choice. In an integer basis index, that qubit is stored in the same
    position as a little-endian bit: ``(basis >> qubit) & 1``. Invalid
    bitstrings receive a penalty greater than the maximum valid cost: each
    per-job server cost is at most 1, so ``job_count + 5`` is strictly higher
    than every valid assignment's possible cost.
    """
    job_count = len(state.jobs)
    server_count = len(state.servers)
    variable_count = job_count * server_count
    values = np.zeros(1 << variable_count, dtype=float)
    for basis in range(len(values)):
        selected_servers: list[int] = []
        is_valid = True
        for job_index in range(job_count):
            selected = [
                server_index
                for server_index in range(server_count)
                if (basis >> (job_index * server_count + server_index)) & 1
            ]
            if len(selected) != 1:
                is_valid = False
                break
            selected_servers.append(selected[0])

        if not is_valid:
            values[basis] = job_count + _INVALID_ASSIGNMENT_PENALTY
            continue

        # Each valid basis state gets an independent copy so simulated queue,
        # temperature, and energy updates cannot leak into the input or peers.
        projected_state = deepcopy(state)
        for job, server_index in zip(state.jobs, selected_servers):
            assign_job(
                projected_state,
                job.job_id,
                projected_state.servers[server_index].server_id,
            )
        values[basis] = sum(
            estimate_assignment_cost(projected_state.servers[server_index])
            for server_index in selected_servers
        )
    return values


def _decode_candidate(
    bitstring: str, jobs: list[Any], servers: list[Any]
) -> dict[str, int] | None:
    """Decode one Qiskit measurement string; None means it violates one-hot."""
    assignments: dict[str, int] = {}
    variable_count = len(jobs) * len(servers)
    if len(bitstring) != variable_count:
        return None
    for job_index, job in enumerate(jobs):
        selected = [
            server_index
            for server_index in range(len(servers))
            if bitstring[variable_count - 1 - (job_index * len(servers) + server_index)] == "1"
        ]
        if len(selected) != 1:
            return None
        assignments[job.job_id] = selected[0]
    return assignments


def _is_valid_candidate(assignments: dict[str, int], state: SimulationState) -> bool:
    """Classically check every job and selected server before returning it."""
    if len(assignments) != len(state.jobs):
        return False
    known_jobs = {job.job_id for job in state.jobs}
    return (
        set(assignments) == known_jobs
        and all(isinstance(index, int) and 0 <= index < len(state.servers)
                for index in assignments.values())
        and all(job.assigned_server_id is None for job in state.jobs)
    )


def _validate_inputs(state: SimulationState, shots: int, reps: int, seed: int) -> None:
    """Validate state and run settings before starting an Aer simulation."""
    if not isinstance(state, SimulationState):
        raise ValueError("state must be a SimulationState")
    if not state.servers:
        raise ValueError("at least one server is required")
    if any(job.assigned_server_id is not None for job in state.jobs):
        raise ValueError("all jobs must be unassigned before optimization")
    job_ids = [job.job_id for job in state.jobs]
    server_ids = [server.server_id for server in state.servers]
    if (any(not isinstance(value, str) or not value for value in job_ids + server_ids)
            or len(set(job_ids)) != len(job_ids)
            or len(set(server_ids)) != len(server_ids)):
        raise ValueError("job and server IDs must be non-empty and unique")
    for job in state.jobs:
        demand = job.processing_demand
        if (isinstance(demand, bool) or not isinstance(demand, (int, float))
                or not math.isfinite(demand) or demand <= 0):
            raise ValueError("job demands must be finite positive numbers")
    # The existing simulator function checks server numeric fields and ranges.
    for server in state.servers:
        estimate_assignment_cost(server)
    if isinstance(shots, bool) or not isinstance(shots, int) or shots <= 0:
        raise ValueError("shots must be a positive integer")
    if isinstance(reps, bool) or not isinstance(reps, int) or reps <= 0:
        raise ValueError("reps must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
