"""ThermoRoute Q hackathon dashboard for comparing simulated schedulers."""

from copy import deepcopy

import plotly.express as px
import streamlit as st

from metrics import calculate_metrics, measure_runtime
from schedulers import (
    schedule_performance_first,
    schedule_round_robin,
    schedule_thermal_aware,
)
from simulation import SimulationState, assign_job, create_servers, generate_jobs
from csv_preview import CSVValidationError, load_csv_preview


st.set_page_config(
    page_title="ThermoRoute Q",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { color-scheme: dark; }
    .stApp { background: #071521; color: #e6f4f7; }
    [data-testid="stSidebar"] { background: #0b1d2b; border-right: 1px solid #17394a; }
    h1, h2, h3 { color: #e6f4f7; }
    [data-testid="stMetric"] { background: #102637; border: 1px solid #1c4354;
      padding: 14px 16px; border-radius: 12px; }
    [data-testid="stMetricValue"] { color: #36d6c4; }
    .stButton > button { background: #12a99e; color: #041719; border: 0;
      border-radius: 9px; font-weight: 700; }
    .stButton > button:hover { background: #36d6c4; color: #041719; }
    </style>
    """,
    unsafe_allow_html=True,
)


def make_initial_state(job_count: int, seed: int) -> SimulationState:
    """Create identical, reproducible starting conditions for a run."""
    return SimulationState(create_servers(), generate_jobs(job_count, seed))


def run_classical(algorithm, initial_state: SimulationState) -> dict:
    """Run one mutating scheduler on its own copy and collect its metrics."""
    state = deepcopy(initial_state)
    assignments, elapsed = measure_runtime(algorithm, state)
    return {
        "assignments": assignments,
        "metrics": calculate_metrics(
            state, assignments, elapsed, initial_state=initial_state
        ),
        "message": "Completed",
        "state": state,
    }


def run_qaoa(initial_state: SimulationState) -> dict:
    """Run the existing QAOA interface and apply a successful candidate locally."""
    state = deepcopy(initial_state)
    # Import inside the handler so a missing optional Qiskit install does not
    # prevent the classical dashboard from loading.
    from quantum_optimizer import optimize_assignments

    result, elapsed = measure_runtime(optimize_assignments, state)
    assignments = result.assignments if result.success else {}
    if result.success:
        # QAOA returns a candidate without changing state. Apply through the
        # simulation's canonical assignment function for comparable outcomes.
        for job in state.jobs:
            assign_job(state, job.job_id, assignments[job.job_id])
    return {
        "assignments": assignments,
        "metrics": calculate_metrics(
            state, assignments, elapsed, initial_state=initial_state
        ),
        "message": result.message,
        "counts": result.counts,
        "state": state,
    }


st.title("ThermoRoute Q")
st.caption("Thermal-aware scheduling for simulated AI workloads")
st.markdown(
    "Temperatures and energy below are **simulated estimates**. Runtime is "
    "measured on this computer. QAOA is a heuristic and is not guaranteed to "
    "beat classical scheduling strategies."
)

with st.sidebar:
    app_mode = st.radio(
        "Project mode",
        ("Generated demo", "CSV validation preview"),
        index=0,
    )

if app_mode == "CSV validation preview":
    st.subheader("Member 2 CSV data — validation and preview only")
    st.markdown(
        "This mode checks the supplied records and displays their original values. "
        "It does not convert CPU or memory units, run schedulers, or produce benchmark results."
    )
    try:
        csv_servers, csv_jobs = load_csv_preview()
    except CSVValidationError as error:
        st.error(f"CSV validation failed: {error}")
    else:
        st.success("Both CSV files passed validation.")
        server_column, job_column = st.columns(2)
        with server_column:
            st.markdown("#### Server records (CSV units)")
            st.dataframe(csv_servers, hide_index=True, use_container_width=True)
        with job_column:
            st.markdown("#### AI-job records (CSV units)")
            st.dataframe(csv_jobs, hide_index=True, use_container_width=True)
        st.info(
            "These records are not yet compatible with the simulator's abstract "
            "processing-work units. No scheduling comparison was run."
        )
    st.stop()

with st.sidebar:
    st.header("Workload")
    job_count = st.slider("Number of AI jobs", min_value=1, max_value=32, value=2)
    seed = st.number_input("Random seed", min_value=0, max_value=2_147_483_647,
                           value=42, step=1)
    st.divider()
    st.header("Algorithms")
    use_round_robin = st.checkbox("Round Robin", value=True)
    use_performance = st.checkbox("Performance-first", value=True)
    use_thermal = st.checkbox("Thermal-aware", value=True)
    initial_state = make_initial_state(job_count, int(seed))
    qaoa_variables = len(initial_state.jobs) * len(initial_state.servers)
    qaoa_allowed = qaoa_variables <= 16
    use_qaoa = st.checkbox(
        "QAOA (Qiskit Aer)", value=qaoa_allowed, disabled=not qaoa_allowed
    )
    st.caption(f"QAOA assignment variables: {qaoa_variables} / 16")
    if not qaoa_allowed:
        st.info(
            f"QAOA is unavailable for this workload: {job_count} jobs × "
            f"{len(initial_state.servers)} servers = {qaoa_variables} variables. "
            "Reduce the job count to 2 or fewer; the workload will not be changed automatically."
        )

st.subheader("Starting workload")
server_rows = [
    {
        "Server": server.server_id,
        "Temperature (simulated °C)": server.temperature_c,
        "Capacity (work units / interval)": server.processing_capacity,
        "Queued work": server.queued_workload,
        "Estimated energy (simulated kWh)": server.estimated_energy_kwh,
    }
    for server in initial_state.servers
]
job_rows = [
    {"Job": job.job_id, "Processing demand (work units)": job.processing_demand}
    for job in initial_state.jobs
]
servers_col, jobs_col = st.columns([1.15, 1])
with servers_col:
    st.markdown("#### Eight virtual servers")
    st.dataframe(server_rows, hide_index=True, use_container_width=True)
with jobs_col:
    st.markdown("#### Generated jobs")
    st.dataframe(job_rows, hide_index=True, use_container_width=True)

selected_algorithms = []
if use_round_robin:
    selected_algorithms.append(("Round Robin", schedule_round_robin))
if use_performance:
    selected_algorithms.append(("Performance-first", schedule_performance_first))
if use_thermal:
    selected_algorithms.append(("Thermal-aware", schedule_thermal_aware))

signature = (int(seed), job_count, tuple(name for name, _ in selected_algorithms), use_qaoa)
if st.session_state.get("run_signature") != signature:
    st.session_state.pop("run_results", None)

if st.button("Run scheduling comparison", type="primary", use_container_width=True):
    if not selected_algorithms and not use_qaoa:
        st.warning("Select at least one scheduling strategy to run.")
    else:
        results = {}
        for name, algorithm in selected_algorithms:
            try:
                results[name] = run_classical(algorithm, initial_state)
            except Exception as exc:
                results[name] = {"error": str(exc)}
        if use_qaoa and qaoa_allowed:
            try:
                results["QAOA"] = run_qaoa(initial_state)
            except Exception as exc:
                # Keep classical outcomes visible when the quantum path fails.
                results["QAOA"] = {"error": f"QAOA could not complete: {exc}"}
        st.session_state["run_results"] = results
        st.session_state["run_signature"] = signature

results = st.session_state.get("run_results")
if results:
    st.divider()
    st.subheader("Scheduling results")
    successful = {name: result for name, result in results.items() if "metrics" in result}
    for name, result in results.items():
        if "error" in result:
            st.error(f"{name}: {result['error']}")
        elif name == "QAOA" and not result["metrics"]["assignment_valid"]:
            st.warning(f"QAOA: {result['message']} No valid schedule was reported.")
        elif name == "QAOA":
            st.success(f"QAOA: {result['message']}")

    if successful:
        metric_rows = []
        for name, result in successful.items():
            metrics = result["metrics"]
            metric_rows.append({
                "Algorithm": name,
                "Valid assignment": "Yes" if metrics["assignment_valid"] else "No",
                "Peak temperature (°C)": metrics["peak_temperature_c"],
                "Servers over thermal limit": metrics["servers_over_thermal_limit"],
                "Makespan (simulated intervals)": metrics["makespan_intervals"],
                "Estimated energy (kWh)": metrics["total_estimated_energy_kwh"],
                "Initial-state assignment objective": (
                    metrics["initial_assignment_cost"]
                    if metrics["initial_assignment_cost"] is not None
                    else "N/A (invalid assignment)"
                ),
                "Final-state assignment cost": (
                    metrics["total_assignment_cost"]
                    if metrics["total_assignment_cost"] is not None
                    else "N/A (invalid assignment)"
                ),
                "Measured runtime (seconds)": metrics["runtime_seconds"],
            })

        st.markdown("#### Outcome metrics")
        st.dataframe(metric_rows, hide_index=True, use_container_width=True)

        card_columns = st.columns(len(successful))
        for column, (name, result) in zip(card_columns, successful.items()):
            metrics = result["metrics"]
            with column:
                st.markdown(f"#### {name}")
                st.metric("Peak simulated temperature", f"{metrics['peak_temperature_c']:.1f} °C")
                st.metric("Estimated makespan", f"{metrics['makespan_intervals']:.3f} intervals")
                st.metric("Measured runtime", f"{metrics['runtime_seconds']:.4f} s")

        st.markdown("#### Simulated outcome comparison")
        chart_definitions = (
            ("Peak temperature", "Peak temperature (°C)", "°C"),
            ("Estimated energy", "Estimated energy (kWh)", "kWh"),
            ("Estimated makespan", "Makespan (simulated intervals)", "intervals"),
        )
        outcome_columns = st.columns(3)
        for column, (title, value_column, unit) in zip(outcome_columns, chart_definitions):
            with column:
                chart = px.bar(
                    metric_rows,
                    x="Algorithm",
                    y=value_column,
                    color="Algorithm",
                    labels={value_column: unit},
                    color_discrete_sequence=["#23c9be", "#65aefc", "#f3bd5b", "#be8cff"],
                    template="plotly_dark",
                    title=title,
                )
                chart.update_layout(
                    height=350,
                    paper_bgcolor="#071521",
                    plot_bgcolor="#0b1d2b",
                    showlegend=False,
                    margin=dict(l=15, r=15, t=50, b=20),
                )
                chart.update_yaxes(rangemode="tozero")
                st.plotly_chart(chart, use_container_width=True)

        st.markdown("#### Measured algorithm runtime")
        runtime_chart = px.bar(
            metric_rows,
            x="Algorithm",
            y="Measured runtime (seconds)",
            color="Algorithm",
            color_discrete_sequence=["#23c9be", "#65aefc", "#f3bd5b", "#be8cff"],
            template="plotly_dark",
        )
        runtime_chart.update_layout(
            height=350,
            paper_bgcolor="#071521",
            plot_bgcolor="#0b1d2b",
            showlegend=False,
            margin=dict(l=20, r=20, t=30, b=20),
        )
        runtime_chart.update_yaxes(rangemode="tozero")
        st.plotly_chart(runtime_chart, use_container_width=True)

        st.markdown("#### Job assignments")
        assignment_columns = st.columns(min(3, len(successful)))
        for index, (name, result) in enumerate(successful.items()):
            assignments = result["assignments"]
            with assignment_columns[index % len(assignment_columns)]:
                st.markdown(f"**{name}**")
                st.dataframe(
                    [{"Job": job_id, "Assigned server": server_id}
                     for job_id, server_id in assignments.items()],
                    hide_index=True,
                    use_container_width=True,
                )

st.caption(
    "All server temperatures, energy values, and completion intervals are model estimates. "
    "Only algorithm runtime is measured; QAOA runs on a local simulator."
)
