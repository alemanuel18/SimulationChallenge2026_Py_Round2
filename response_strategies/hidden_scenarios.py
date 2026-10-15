"""Reproducible local stress scenarios for preparing the hidden round.

Generated case directories are ignored by Git. This module retains their
definitions so they can be recreated without changing official input tables
or the simulation engine.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from maritime_data_context import Berth, DisruptionPlan, Vessel
from scenario_builders.baseline_stable_scenario import BaselineStableScenario


CASE_ROOT = Path(__file__).resolve().parent / "hidden_round_cases"
SPEC_VERSION = 3

CASE_DEFINITIONS = (
    {
        "id": "case_01_long_ocean_detours",
        "description": "Long ocean-leg shocks on two corridors with alternatives.",
        "structure": {"route_start_shift_days": 1.4},
        "disruptions": [
            {"type": "leg", "route": "S1", "sequence": 4, "start": 28, "duration": 48, "multiplier": 4.0},
            {"type": "leg", "route": "S4", "sequence": 2, "start": 172, "duration": 35, "multiplier": 6.0},
        ],
    },
    {
        "id": "case_02_central_hub_closure",
        "description": "A central transshipment hub closes, followed by a nearby leg shock.",
        "structure": {"demand_scale": 1.10, "demand_port_multipliers": {"Singapore": 1.35}},
        "disruptions": [
            {"type": "port", "port": "Singapore", "start": 75, "duration": 18},
            {"type": "leg", "route": "S7", "sequence": 2, "start": 88, "duration": 30, "multiplier": 3.5},
        ],
    },
    {
        "id": "case_03_scarce_fleet_high_demand",
        "description": "Reduced fleet and high demand under overlapping disruptions.",
        "structure": {"demand_scale": 1.40, "fleet_scale": 0.72, "capacity_scale": 0.90},
        "disruptions": [
            {"type": "leg", "route": "S5", "sequence": 4, "start": 42, "duration": 42, "multiplier": 3.0},
            {"type": "port", "port": "New Jersey", "start": 58, "duration": 14},
            {"type": "leg", "route": "S9", "sequence": 3, "start": 61, "duration": 27, "multiplier": 4.0},
        ],
    },
    {
        "id": "case_05_overlapping_same_service",
        "description": "Two simultaneous blocked legs on one service plus a closure.",
        "structure": {"distance_scale": 1.08},
        "disruptions": [
            {"type": "leg", "route": "S1", "sequence": 4, "start": 92, "duration": 44, "multiplier": 5.0},
            {"type": "leg", "route": "S1", "sequence": 6, "start": 104, "duration": 25, "multiplier": 4.0},
            {"type": "port", "port": "Piraeus", "start": 110, "duration": 11},
        ],
    },
    {
        "id": "case_06_changed_topology",
        "description": "One transpacific service is absent and the remaining corridor is disrupted.",
        "structure": {"remove_routes": ["S4"], "demand_port_multipliers": {"Los Angeles": 1.25}},
        "disruptions": [
            {"type": "leg", "route": "S9", "sequence": 3, "start": 48, "duration": 55, "multiplier": 4.5},
            {"type": "port", "port": "Busan", "start": 190, "duration": 16},
        ],
    },
    {
        "id": "case_07_renamed_slower_network",
        "description": "Unknown route identifiers, slower ships and shifted schedules.",
        "structure": {"route_id_prefix": "HIDDEN-", "speed_scale": 0.82, "route_start_shift_days": 3.2, "distance_scale": 1.12},
        "disruptions": [
            {"type": "leg", "route": "S2", "sequence": 6, "start": 20, "duration": 22, "multiplier": 7.0},
            {"type": "port", "port": "Tianjin", "start": 155, "duration": 20},
        ],
    },
    {
        "id": "case_08_rapid_staggered_shocks",
        "description": "Many short shocks test reaction speed without advance specialization.",
        "structure": {"fleet_scale": 0.90},
        "disruptions": [
            {"type": "leg", "route": "S3", "sequence": 1, "start": 18, "duration": 7, "multiplier": 5.0},
            {"type": "leg", "route": "S6", "sequence": 3, "start": 82, "duration": 9, "multiplier": 5.5},
            {"type": "port", "port": "Kaohsiung", "start": 149, "duration": 6},
            {"type": "leg", "route": "S7", "sequence": 3, "start": 221, "duration": 8, "multiplier": 8.0},
            {"type": "port", "port": "Cartagena", "start": 305, "duration": 7},
        ],
    },
    {
        "id": "case_09_asymmetric_regional_demand",
        "description": "Demand moves toward peripheral ports while feeder links are disturbed.",
        "structure": {"demand_scale": 0.90, "demand_port_multipliers": {"Jakarta": 2.4, "Laem Chabang": 1.8, "Cartagena": 1.7}, "route_fleet_counts": {"S8": 2, "S3": 1}},
        "disruptions": [
            {"type": "port", "port": "Jakarta", "start": 64, "duration": 13},
            {"type": "leg", "route": "S3", "sequence": 2, "start": 170, "duration": 33, "multiplier": 4.0},
            {"type": "port", "port": "Cartagena", "start": 274, "duration": 15},
        ],
    },
    {
        "id": "case_10_compound_late_crisis",
        "description": "A quiet first half followed by simultaneous late network shocks.",
        "structure": {"demand_scale": 1.18, "capacity_scale": 0.85, "berth_counts": {"Colombo": 1, "New Jersey": 1}},
        "disruptions": [
            {"type": "leg", "route": "S5", "sequence": 4, "start": 205, "duration": 70, "multiplier": 5.0},
            {"type": "port", "port": "Colombo", "start": 216, "duration": 24},
            {"type": "leg", "route": "S6", "sequence": 6, "start": 225, "duration": 45, "multiplier": 4.0},
            {"type": "port", "port": "New Jersey", "start": 252, "duration": 18},
        ],
    },
)


def prepare_case_directories(case_root=CASE_ROOT, overwrite=False):
    """Materialize one identifiable directory and manifest per stress case."""
    root = Path(case_root)
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for definition in CASE_DEFINITIONS:
        directory = root / definition["id"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "results").mkdir(exist_ok=True)
        manifest = directory / "scenario.json"
        rendered = json.dumps(
            {"spec_version": SPEC_VERSION, **definition}, indent=2, sort_keys=True
        ) + "\n"
        if overwrite or not manifest.exists() or manifest.read_text(encoding="utf-8") != rendered:
            manifest.write_text(rendered, encoding="utf-8")
        paths.append(manifest)
    return paths


def load_case_definitions(case_root=CASE_ROOT):
    prepare_case_directories(case_root)
    definitions = []
    for manifest in sorted(Path(case_root).glob("case_*/scenario.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("spec_version") != SPEC_VERSION:
            raise ValueError(f"Unsupported scenario version in {manifest}")
        definitions.append(data)
    if len(definitions) != len(CASE_DEFINITIONS):
        raise ValueError(f"Expected {len(CASE_DEFINITIONS)} cases, found {len(definitions)}")
    return definitions


def create_context(case_definition, include_disruptions=True, warm_up_days=140):
    """Build an isolated context for one case from the official input data."""
    context = BaselineStableScenario.create()
    _apply_structure(context, copy.deepcopy(case_definition).get("structure", {}))
    if include_disruptions:
        for event in case_definition.get("disruptions", ()):
            _add_disruption(context, event, warm_up_days)
    return context


def _apply_structure(context, structure):
    demand_scale = _positive(structure.get("demand_scale", 1.0), "demand_scale")
    port_multipliers = structure.get("demand_port_multipliers", {})
    for demand in context.demands:
        multiplier = demand_scale
        multiplier *= float(port_multipliers.get(demand.origin_port.name, 1.0))
        multiplier *= float(port_multipliers.get(demand.destination_port.name, 1.0))
        demand.annual_teus = max(1, int(round(demand.annual_teus * multiplier)))

    distance_scale = _positive(structure.get("distance_scale", 1.0), "distance_scale")
    for leg in context.legs:
        leg.sailing_distance *= distance_scale

    speed_scale = _positive(structure.get("speed_scale", 1.0), "speed_scale")
    capacity_scale = _positive(structure.get("capacity_scale", 1.0), "capacity_scale")
    for vessel_class in context.vessel_classes:
        vessel_class.sailing_speed *= speed_scale
        vessel_class.teu_capacity = max(1, int(round(vessel_class.teu_capacity * capacity_scale)))

    for port_name, count in structure.get("berth_counts", {}).items():
        port = _require_port(context, port_name)
        count = int(count)
        if count < 1:
            raise ValueError(f"Port {port_name!r} must keep at least one berth")
        port.berths[:] = [Berth(index=index, port=port) for index in range(count)]

    for route_id in set(structure.get("remove_routes", ())):
        _remove_route(context, _require_route(context, route_id))

    fleet_scale = _positive(structure.get("fleet_scale", 1.0), "fleet_scale")
    requested_counts = structure.get("route_fleet_counts", {})
    for route in list(context.initial_service_routes):
        desired = requested_counts.get(route.id)
        if desired is None:
            desired = max(1, int(round(len(route.deployed_vessels) * fleet_scale)))
        _resize_route_fleet(context, route, int(desired))

    shift = float(structure.get("route_start_shift_days", 0.0))
    for route in context.initial_service_routes:
        route.start_day_of_week = (route.start_day_of_week + shift) % 7.0

    prefix = str(structure.get("route_id_prefix", ""))
    if prefix:
        for route in context.initial_service_routes:
            route.id = prefix + route.id


def _remove_route(context, route):
    for vessel in list(route.deployed_vessels):
        context.vessels.remove(vessel)
        vessel.vessel_class.vessels.remove(vessel)
    route.deployed_vessels.clear()
    context.service_routes.remove(route)
    context.initial_service_routes.remove(route)
    for segment in list(route.segments):
        if segment in context.partial_service_routes:
            context.partial_service_routes.remove(segment)
        if segment in segment.associated_leg.segments:
            segment.associated_leg.segments.remove(segment)


def _resize_route_fleet(context, route, desired):
    if desired < 1:
        raise ValueError(f"Route {route.id!r} must keep at least one vessel")
    current = len(route.deployed_vessels)
    if desired < current:
        for vessel in list(route.deployed_vessels[desired:]):
            route.deployed_vessels.remove(vessel)
            context.vessels.remove(vessel)
            vessel.vessel_class.vessels.remove(vessel)
    elif desired > current:
        vessel_class = route.deployed_vessels[0].vessel_class
        next_index = max((v.index for v in context.vessels), default=0) + 1
        for index in range(next_index, next_index + desired - current):
            vessel = Vessel(index, vessel_class, route)
            route.deployed_vessels.append(vessel)
            vessel_class.vessels.append(vessel)
            context.vessels.append(vessel)


def _add_disruption(context, event, warm_up_days):
    start = float(event["start"]) + warm_up_days
    duration = _positive(event["duration"], "duration")
    if event["type"] == "leg":
        route = _require_route(context, event["route"], allow_prefixed=True)
        sequence = int(event["sequence"])
        segment = next((s for s in route.segments if s.sequence_index == sequence), None)
        if segment is None:
            raise ValueError(f"Route {route.id!r} has no segment {sequence}")
        context.disruption_plans.append(
            DisruptionPlan(
                target_leg=segment.associated_leg,
                start_offset_days=start,
                duration_days=duration,
                multiplier=_positive(event["multiplier"], "multiplier"),
            )
        )
    elif event["type"] == "port":
        port = _require_port(context, event["port"])
        for berth in port.berths:
            context.disruption_plans.append(
                DisruptionPlan(
                    target_berth=berth,
                    start_offset_days=start,
                    duration_days=duration,
                    close_berth=True,
                )
            )
    else:
        raise ValueError(f"Unknown disruption type: {event['type']!r}")


def _require_port(context, name):
    port = next((item for item in context.ports if item.name == name), None)
    if port is None:
        raise ValueError(f"Unknown port: {name!r}")
    return port


def _require_route(context, route_id, allow_prefixed=False):
    route = next((item for item in context.initial_service_routes if item.id == route_id), None)
    if route is None and allow_prefixed:
        route = next((item for item in context.initial_service_routes if item.id.endswith(route_id)), None)
    if route is None:
        raise ValueError(f"Unknown route: {route_id!r}")
    return route


def _positive(value, name):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return number
