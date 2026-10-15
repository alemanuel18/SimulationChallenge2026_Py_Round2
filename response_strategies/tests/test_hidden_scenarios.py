import main as _simulation_main  # noqa: F401 - preserve simulator import order

from response_strategies.hidden_scenarios import (
    CASE_DEFINITIONS,
    create_context,
    load_case_definitions,
    prepare_case_directories,
)


def test_prepares_ten_separate_ignored_case_directories(tmp_path):
    manifests = prepare_case_directories(tmp_path)

    assert len(manifests) == 10
    assert len({path.parent for path in manifests}) == 10
    assert all((path.parent / "results").is_dir() for path in manifests)
    assert [item["id"] for item in load_case_definitions(tmp_path)] == [
        item["id"] for item in CASE_DEFINITIONS
    ]


def test_every_case_builds_paired_baseline_and_disrupted_context():
    for definition in CASE_DEFINITIONS:
        baseline = create_context(definition, include_disruptions=False)
        disrupted = create_context(definition, include_disruptions=True)

        assert not baseline.disruption_plans
        assert disrupted.disruption_plans
        assert len(baseline.initial_service_routes) == len(disrupted.initial_service_routes)
        assert len(baseline.vessels) == len(disrupted.vessels)


def test_renamed_routes_and_topology_variation_are_material():
    changed_topology = create_context(CASE_DEFINITIONS[5], include_disruptions=True)
    renamed = create_context(CASE_DEFINITIONS[6], include_disruptions=True)

    assert "S4" not in {route.id for route in changed_topology.initial_service_routes}
    assert all(route.id.startswith("HIDDEN-") for route in renamed.initial_service_routes)
    assert renamed.disruption_plans


def test_expensive_cases_keep_useful_but_bounded_pressure():
    scarce_fleet = CASE_DEFINITIONS[2]
    berth_pressure = CASE_DEFINITIONS[3]
    late_crisis = CASE_DEFINITIONS[9]

    assert scarce_fleet["structure"]["demand_scale"] == 1.40
    assert berth_pressure["id"] == "case_04_moderate_berth_pressure"
    assert berth_pressure["structure"]["fleet_scale"] == 1.10
    assert berth_pressure["structure"]["berth_counts"] == {
        "Shanghai": 2,
        "Rotterdam": 2,
        "Los Angeles": 1,
    }
    assert late_crisis["structure"]["demand_scale"] == 1.18
