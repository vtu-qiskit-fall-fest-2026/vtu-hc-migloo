"""Built-in unit tests for the virtual server simulator."""

import unittest

from simulation import SimulationState, assign_job, create_servers, generate_jobs


class SimulationTests(unittest.TestCase):
    def test_creates_eight_distinct_servers(self):
        servers = create_servers()
        self.assertEqual(len(servers), 8)
        self.assertEqual(len({server.server_id for server in servers}), 8)

    def test_job_workload_is_reproducible(self):
        first = generate_jobs(12, seed=27)
        second = generate_jobs(12, seed=27)
        self.assertEqual(first, second)

    def test_assignment_updates_job_and_server(self):
        server = create_servers()[0]
        job = generate_jobs(1, seed=3)[0]
        initial_queue = server.queued_workload
        state = SimulationState([server], [job])
        assign_job(state, job.job_id, server.server_id)
        self.assertEqual(job.assigned_server_id, server.server_id)
        self.assertEqual(server.queued_workload, initial_queue + job.processing_demand)
        self.assertGreater(server.temperature_c, 38.0)
        self.assertGreater(server.estimated_energy_kwh, 0.0)

    def test_invalid_inputs_raise_value_error(self):
        with self.assertRaises(ValueError):
            generate_jobs(-1, seed=1)
        with self.assertRaises(ValueError):
            generate_jobs(1, seed="not-an-integer")
        state = SimulationState(create_servers(), generate_jobs(1, seed=1))
        with self.assertRaises(ValueError):
            assign_job(state, state.jobs[0].job_id, "missing-server")
        with self.assertRaises(ValueError):
            assign_job(state, "missing-job", state.servers[0].server_id)

    def test_invalid_job_demand_is_rejected(self):
        state = SimulationState(create_servers(), generate_jobs(1, seed=1))
        state.jobs[0].processing_demand = 0
        with self.assertRaises(ValueError):
            assign_job(state, state.jobs[0].job_id, state.servers[0].server_id)


if __name__ == "__main__":
    unittest.main()
