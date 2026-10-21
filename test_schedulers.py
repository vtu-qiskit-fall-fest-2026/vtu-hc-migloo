"""Unit tests for the classical ThermoRoute Q scheduling strategies."""

import copy
import unittest

from schedulers import (
    schedule_performance_first,
    schedule_round_robin,
    schedule_thermal_aware,
)
from simulation import SimulationState, create_servers, generate_jobs


class SchedulerTests(unittest.TestCase):
    def make_state(self):
        return SimulationState(create_servers(), generate_jobs(18, seed=314))

    def assert_valid_assignments(self, state, assignments):
        valid_server_ids = {server.server_id for server in state.servers}
        self.assertEqual(len(assignments), len(state.jobs))
        self.assertEqual(len(set(assignments)), len(state.jobs))
        for job in state.jobs:
            self.assertIn(job.job_id, assignments)
            self.assertIn(assignments[job.job_id], valid_server_ids)
            self.assertEqual(job.assigned_server_id, assignments[job.job_id])

    def test_each_scheduler_assigns_every_job_to_valid_server(self):
        for scheduler in (schedule_round_robin, schedule_performance_first,
                          schedule_thermal_aware):
            with self.subTest(scheduler=scheduler.__name__):
                state = self.make_state()
                assignments = scheduler(state)
                self.assert_valid_assignments(state, assignments)

    def test_all_schedulers_are_deterministic(self):
        for scheduler in (schedule_round_robin, schedule_performance_first,
                          schedule_thermal_aware):
            with self.subTest(scheduler=scheduler.__name__):
                first = self.make_state()
                second = self.make_state()
                self.assertEqual(scheduler(first), scheduler(second))
                self.assertEqual(first, second)

    def test_round_robin_rotates_in_server_order(self):
        state = SimulationState(create_servers(), generate_jobs(10, seed=9))
        assignments = schedule_round_robin(state)
        ids = [server.server_id for server in state.servers]
        self.assertEqual(
            [assignments[job.job_id] for job in state.jobs],
            [ids[index % len(ids)] for index in range(len(state.jobs))],
        )

    def test_scheduler_rejects_invalid_state_without_partial_assignment(self):
        state = self.make_state()
        state.jobs[3].processing_demand = 0
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            schedule_thermal_aware(state)
        self.assertEqual(state, before)

    def test_scheduler_rejects_preassigned_jobs(self):
        state = self.make_state()
        state.jobs[0].assigned_server_id = state.servers[0].server_id
        with self.assertRaises(ValueError):
            schedule_round_robin(state)


if __name__ == "__main__":
    unittest.main()
