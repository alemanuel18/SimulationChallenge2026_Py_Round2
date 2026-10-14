import main as _simulation_main  # noqa: F401 - preserve simulator import order

import pytest

from response_strategies.optimize_round2 import (
    _default_parameters,
    _environment_from_parameters,
    _loss_from_periods,
    _robust_score,
)


def test_optimizer_maps_every_current_general_parameter():
    environment = _environment_from_parameters(_default_parameters())

    assert environment["WSC_WAIT_WEIGHT"] == "1.0"
    assert environment["WSC_LEAD_HEADWAY_FACTOR"] == "1.5"
    assert environment["WSC_PORT_LEAD_HEADWAY_FACTOR"] == "0.25"
    assert environment["WSC_DETOUR_GAIN_RATIO"] == "5.0"
    assert not any(name.startswith("WSC_ENABLE_S") for name in environment)


def test_robust_score_penalizes_unstable_and_bad_worst_case():
    stable = _robust_score([10.0] * 10)
    unstable = _robust_score([0.0] * 9 + [20.0])

    assert stable == pytest.approx(10.0)
    assert unstable > 2.0


def test_loss_matches_period_weighted_competition_formula():
    loss = _loss_from_periods(
        baseline=[10.0, 10.0],
        disrupted=[20.0, 5.0],
        interval_days=5,
        simulation_days=10,
    )

    assert loss == pytest.approx(-2.5)
