"""Built-in unit tests for non-mutating simulation metrics."""

from copy import deepcopy
import unittest

from metrics import (
    SIMULATED_THERMAL_LIMIT_C,
    calculate_metrics,
    compare_algorithms,
    is_assignment_valid,
    measure_runtime,
)
from schedulers import schedule_round_robin
from simulation import Job, Server, SimulationState, estimate_assignment_cost


def sample_state():
    return SimulationState(
        servers=[
            Server("s1", 50.0, 100.0, queued_workload=20.0, estimated_energy_kwh=0.5),
            Server("s2", 80.0, 200.0, queued_workload=30.0, estimated_energy_kwh=0.7),
        ],
        jobs=[Job("j1", 20.0, "s1"), Job("j2", 30.0, "s2")],
    )


class MetricsTests(unittest.TestCase):
    def test_calculates_metrics_without_mutating_state(self):
        state = sample_state()
        before = deepcopy(state)
        results = calculate_metrics(state)
        self.assertEqual(state, before)
        self.assertEqual(results["peak_temperature_c"], 80.0)
        self.assertEqual(results["servers_over_thermal_limit"], 1)
        self.assertEqual(results["thermal_limit_c"], SIMULATED_THERMAL_LIMIT_C)
        self.assertAlmostEqual(results["makespan_intervals"], 0.2)
        self.assertAlmostEqual(results["total_estimated_energy_kwh"], 1.2)
        self.assertTrue(results["assignment_valid"])
        self.assertIsNotNone(results["total_assignment_cost"])

    def test_initial_and_final_assignment_costs_use_their_own_server_states(self):
        final_state = sample_state()
        initial_state = deepcopy(final_state)
        for server, initial_temperature in zip(initial_state.servers, (42.0, 55.0)):
            server.temperature_c = initial_temperature
            server.queued_workload = 0.0
            server.estimated_energy_kwh = 0.0
        for job in initial_state.jobs:
            job.assigned_server_id = None
        before_initial = deepcopy(initial_state)
        before_final = deepcopy(final_state)

        metrics = calculate_metrics(final_state, initial_state=initial_state)

        expected_initial = sum(
            estimate_assignment_cost(server) for server in initial_state.servers
        )
        expected_final = sum(
            estimate_assignment_cost(server) for server in final_state.servers
        )
        self.assertAlmostEqual(metrics["initial_assignment_cost"], expected_initial)
        self.assertAlmostEqual(metrics["total_assignment_cost"], expected_final)
        self.assertNotEqual(metrics["initial_assignment_cost"], metrics["total_assignment_cost"])
        self.assertEqual(initial_state, before_initial)
        self.assertEqual(final_state, before_final)

    def test_invalid_assignment_has_no_initial_or_final_assignment_cost(self):
        initial_state = sample_state()
        for job in initial_state.jobs:
            job.assigned_server_id = None
        metrics = calculate_metrics(
            sample_state(), {"j1": "s1"}, initial_state=initial_state
        )
        self.assertFalse(metrics["assignment_valid"])
        self.assertIsNone(metrics["initial_assignment_cost"])
        self.assertIsNone(metrics["total_assignment_cost"])

    def test_assignment_validation_handles_bad_and_empty_assignments(self):
        state = sample_state()
        self.assertFalse(is_assignment_valid(state, {"j1": "s1"}))
        self.assertFalse(is_assignment_valid(state, {"j1": "unknown", "j2": "s2"}))
        self.assertFalse(is_assignment_valid(SimulationState(state.servers, []), {}))
        state.jobs[1].assigned_server_id = None
        self.assertFalse(is_assignment_valid(state))

    def test_empty_jobs_report_invalid_and_zero_work_metrics(self):
        state = SimulationState([Server("s1", 40.0, 100.0)], [])
        metrics = calculate_metrics(state)
        self.assertFalse(metrics["assignment_valid"])
        self.assertIsNone(metrics["total_assignment_cost"])
        self.assertEqual(metrics["makespan_intervals"], 0.0)
        self.assertEqual(metrics["total_estimated_energy_kwh"], 0.0)

    def test_runtime_helper_measures_callable(self):
        result, seconds = measure_runtime(sum, [1, 2, 3])
        self.assertEqual(result, 6)
        self.assertGreaterEqual(seconds, 0.0)

    def test_invalid_inputs_raise_clear_errors(self):
        with self.assertRaisesRegex(ValueError, "runtime_seconds"):
            calculate_metrics(sample_state(), runtime_seconds=-1)
        with self.assertRaisesRegex(ValueError, "SimulationState"):
            calculate_metrics(None)
        with self.assertRaisesRegex(ValueError, "non-empty mapping"):
            compare_algorithms({}, sample_state())

    def test_comparison_uses_independent_identical_starting_copies(self):
        initial = sample_state()
        for job in initial.jobs:
            job.assigned_server_id = None
        before = deepcopy(initial)
        results = compare_algorithms({"round_robin": schedule_round_robin}, initial)
        self.assertEqual(initial, before)
        self.assertTrue(results["round_robin"]["assignment_valid"])
        self.assertGreaterEqual(results["round_robin"]["runtime_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
