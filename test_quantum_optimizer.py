"""Tests for the small Qiskit QAOA optimizer."""

from copy import deepcopy
import unittest

from quantum_optimizer import _decode_candidate, _make_energy_table, optimize_assignments
from simulation import (
    Job,
    Server,
    SimulationState,
    assign_job,
    estimate_assignment_cost,
)


def small_state():
    """Use a tiny 2-job/2-server problem for a quick Aer simulation."""
    return SimulationState(
        servers=[
            Server("cool-server", 35.0, 100.0),
            Server("warm-server", 65.0, 120.0),
        ],
        jobs=[Job("job-a", 25.0), Job("job-b", 40.0)],
    )


class QuantumOptimizerTests(unittest.TestCase):
    def test_energy_table_matches_projected_final_state_and_preserves_input(self):
        state = small_state()
        original = deepcopy(state)
        selected_server_indices = [1, 0]

        # Qubits are indexed job-major and stored little-endian in the basis
        # integer, matching the optimizer's Qiskit measurement decoding.
        basis = sum(
            1 << (job_index * len(state.servers) + server_index)
            for job_index, server_index in enumerate(selected_server_indices)
        )
        energy_table = _make_energy_table(state)
        bitstring = format(basis, f"0{len(state.jobs) * len(state.servers)}b")
        self.assertEqual(
            _decode_candidate(bitstring, state.jobs, state.servers),
            {"job-a": 1, "job-b": 0},
        )

        projected = deepcopy(state)
        for job, server_index in zip(state.jobs, selected_server_indices):
            assign_job(projected, job.job_id, projected.servers[server_index].server_id)
        expected = sum(
            estimate_assignment_cost(projected.servers[server_index])
            for server_index in selected_server_indices
        )

        self.assertAlmostEqual(energy_table[basis], expected)
        self.assertEqual(state, original)

    def test_result_has_expected_structure(self):
        result = optimize_assignments(small_state(), shots=256, seed=23)
        self.assertIsInstance(result.success, bool)
        self.assertIsInstance(result.assignments, dict)
        self.assertIsInstance(result.message, str)
        self.assertIsInstance(result.counts, dict)
        if result.success:
            self.assertIsInstance(result.objective_value, float)
        else:
            self.assertIsNone(result.objective_value)

    def test_returned_solution_assigns_each_job_once_to_known_server(self):
        state = small_state()
        result = optimize_assignments(state, shots=512, seed=23)
        if result.success:
            self.assertEqual(set(result.assignments), {job.job_id for job in state.jobs})
            server_ids = {server.server_id for server in state.servers}
            self.assertTrue(all(server_id in server_ids for server_id in result.assignments.values()))
            self.assertTrue(all(job.assigned_server_id is None for job in state.jobs))
            projected = deepcopy(state)
            for job in projected.jobs:
                assign_job(projected, job.job_id, result.assignments[job.job_id])
            servers_by_id = {server.server_id: server for server in projected.servers}
            expected_objective = sum(
                estimate_assignment_cost(servers_by_id[result.assignments[job.job_id]])
                for job in projected.jobs
            )
            self.assertAlmostEqual(result.objective_value, expected_objective)

    def test_invalid_settings_and_state_raise_clear_errors(self):
        with self.assertRaisesRegex(ValueError, "shots"):
            optimize_assignments(small_state(), shots=0)
        with self.assertRaisesRegex(ValueError, "demands"):
            state = small_state()
            state.jobs[0].processing_demand = float("nan")
            optimize_assignments(state)
        with self.assertRaisesRegex(ValueError, "maximum"):
            state = SimulationState(
                servers=[Server(f"s{i}", 40.0, 100.0) for i in range(4)],
                jobs=[Job(f"j{i}", 10.0) for i in range(5)],
            )
            optimize_assignments(state)


if __name__ == "__main__":
    unittest.main()
