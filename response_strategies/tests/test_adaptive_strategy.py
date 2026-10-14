import datetime as dt

# This test belongs to the submitted strategy package and changes no simulator code.
# Preserve the simulator's normal import order and avoid package cycles.
import main as _simulation_main  # noqa: F401

from maritime_data_context import (
    Berth,
    Demand,
    DisruptionPlan,
    Leg,
    MaritimeDataContext,
    Port,
    Segment,
    ServiceRoute,
    Shipment,
    Vessel,
    VesselClass,
)
from response_strategies.round2_strategy import (
    _closed_port_wait_days,
    _has_actionable_strategy,
    _leg_detour_is_beneficial,
    _unique_closed_port_events,
    assign_bookings,
    manage_service_routes,
    supports_adaptive_strategy,
)
from response_strategies.strategy_validation import (
    capture_alternative_route_strategy_state,
    validate_alternative_route_strategy_result,
)


def test_strategy_supports_arbitrary_topology_and_route_ids():
    context, _, ports, _ = _network(multiplier=6.0)
    shipment = Shipment(
        index=1,
        teu_size=2,
        demand=Demand(origin_port=ports[0], destination_port=ports[2]),
    )

    assert supports_adaptive_strategy(context)
    assert assign_bookings(context, dt.datetime.min, shipment)
    assert shipment.associated_bookings
    assert shipment.associated_bookings[0].service_route.id == "PACIFIC-ALPHA"


def test_detour_decision_uses_gain_instead_of_route_name():
    high_impact, route, _, event = _network(multiplier=6.0)
    marginal, marginal_route, _, marginal_event = _network(multiplier=1.1)

    assert _leg_detour_is_beneficial(high_impact, route, event)
    assert not _leg_detour_is_beneficial(
        marginal, marginal_route, marginal_event
    )
    assert _has_actionable_strategy(high_impact)
    assert not _has_actionable_strategy(marginal)


def test_non_actionable_context_delegates_to_default_strategy():
    context, _, ports, _ = _network(multiplier=1.1)
    shipment = Shipment(
        index=2,
        teu_size=1,
        demand=Demand(origin_port=ports[0], destination_port=ports[2]),
    )

    assert manage_service_routes(context, dt.datetime.min) is None
    assert assign_bookings(context, dt.datetime.min, shipment) is None


def test_manage_routes_is_idempotent_and_preserves_model_invariants():
    context, source_route, _, event = _network(multiplier=6.0)
    now = dt.datetime.min + dt.timedelta(days=event.start_offset_days - 1)

    first_snapshot = capture_alternative_route_strategy_state(context)
    assert manage_service_routes(context, now)
    validate_alternative_route_strategy_result(context, first_snapshot)
    route_count = len(context.service_routes)
    alternatives = [
        route
        for route in context.service_routes
        if getattr(route, "_round2_source_route", None) is source_route
    ]
    assert len(alternatives) == 1
    assert alternatives[0]._round2_active

    second_snapshot = capture_alternative_route_strategy_state(context)
    assert manage_service_routes(context, now)
    validate_alternative_route_strategy_result(context, second_snapshot)
    assert len(context.service_routes) == route_count
    assert alternatives[0]._round2_active


def test_overlapping_events_keep_only_one_alternative_active():
    context, source_route, _, event = _network(multiplier=6.0)
    context.disruption_plans.append(
        DisruptionPlan(
            target_leg=event.target_leg,
            start_offset_days=event.start_offset_days,
            duration_days=event.duration_days,
            multiplier=8.0,
        )
    )
    now = dt.datetime.min + dt.timedelta(days=event.start_offset_days - 1)

    assert manage_service_routes(context, now)
    alternatives = [
        route
        for route in context.service_routes
        if getattr(route, "_round2_source_route", None) is source_route
    ]
    assert len(alternatives) == 2
    assert sum(route._round2_active for route in alternatives) == 1

    route_count = len(context.service_routes)
    assert manage_service_routes(context, now)
    assert len(context.service_routes) == route_count
    assert sum(route._round2_active for route in alternatives) == 1


def test_partial_berth_closure_is_not_treated_as_closed_port():
    context, _, ports, _ = _network(multiplier=1.0)
    port = ports[1]
    berth_a = Berth(index=1, port=port)
    berth_b = Berth(index=2, port=port)
    port.berths.extend([berth_a, berth_b])
    context.disruption_plans = [
        DisruptionPlan(
            target_berth=berth_a,
            start_offset_days=10,
            duration_days=5,
            close_berth=True,
        )
    ]
    when = dt.datetime.min + dt.timedelta(days=11)

    assert _closed_port_wait_days(context, port, when) == 0
    assert _unique_closed_port_events(context) == []

    context.disruption_plans.append(
        DisruptionPlan(
            target_berth=berth_b,
            start_offset_days=10,
            duration_days=5,
            close_berth=True,
        )
    )
    assert _closed_port_wait_days(context, port, when) == 4
    assert len(_unique_closed_port_events(context)) == 1


def _network(multiplier):
    context = MaritimeDataContext()
    port_a = Port(name="Aurora")
    port_b = Port(name="Borealis")
    port_c = Port(name="Cygnus")
    port_d = Port(name="Draco")
    ports = [port_a, port_b, port_c, port_d]
    context.ports.extend(ports)

    direct = Leg(port_a, port_b, 1_000)
    onward = Leg(port_b, port_c, 100)
    returning = Leg(port_c, port_a, 100)
    detour_a = Leg(port_a, port_d, 600)
    detour_b = Leg(port_d, port_b, 600)
    context.legs.extend([direct, onward, returning, detour_a, detour_b])

    route = ServiceRoute(id="PACIFIC-ALPHA", name="Arbitrary Service")
    for index, leg in enumerate([direct, onward, returning], start=1):
        segment = Segment(index, leg, route)
        route.segments.append(segment)
        leg.segments.append(segment)
        context.partial_service_routes.append(segment)
    context.service_routes.append(route)
    context.initial_service_routes.append(route)

    vessel_class = VesselClass(
        name="Synthetic",
        teu_capacity=8_000,
        sailing_speed=20,
    )
    vessel = Vessel(index=1, vessel_class=vessel_class, assigned_service_route=route)
    vessel_class.vessels.append(vessel)
    route.deployed_vessels.append(vessel)
    context.vessel_classes.append(vessel_class)
    context.vessels.append(vessel)

    event = DisruptionPlan(
        target_leg=direct,
        start_offset_days=20,
        duration_days=10,
        multiplier=multiplier,
    )
    if multiplier > 1:
        context.disruption_plans.append(event)
    return context, route, ports, event
