import main as _simulation_main  # noqa: F401 - preserve simulator import order

import pytest

from response_strategies.optimize_round2 import (
    STARTUP_TRIALS,
    _default_parameters,
    _environment_from_parameters,
    _loss_from_periods,
    parse_arguments,
    _robust_score,
    _recover_interrupted_trials,
    _write_case_result,
)


def test_optimizer_maps_every_current_general_parameter():
    environment = _environment_from_parameters(_default_parameters())

    assert environment["WSC_WAIT_WEIGHT"] == "1.5294118095553806"
    assert environment["WSC_LEAD_HEADWAY_FACTOR"] == "2.641254353015926"
    assert environment["WSC_PORT_LEAD_HEADWAY_FACTOR"] == "1.2655109081440026"
    assert environment["WSC_DETOUR_GAIN_RATIO"] == "0.510671938639319"
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


def test_case_result_is_persisted_before_aggregate_score_exists(tmp_path):
    case_directory = tmp_path / "case_01"
    (case_directory / "results").mkdir(parents=True)

    _write_case_result(
        tmp_path,
        {"case": "case_01", "loss": 2.5},
        "trial_000001",
        _default_parameters(),
    )

    saved = case_directory / "results" / "trial_000001.json"
    assert saved.is_file()
    assert "robust_score" not in saved.read_text(encoding="utf-8")


def test_default_case_timeout_is_fifty_minutes():
    arguments = parse_arguments([])

    assert arguments.case_timeout_seconds == 3_000
    assert arguments.workers == 7


def test_adaptive_sampler_starts_after_five_trials():
    assert STARTUP_TRIALS == 5


def test_interrupted_trial_is_failed_and_requeued():
    import optuna

    study = optuna.create_study()
    running = study.ask(
        fixed_distributions={
            "wait_fraction": optuna.distributions.FloatDistribution(0.1, 1.5)
        }
    )
    running.suggest_float("wait_fraction", 0.1, 1.5)

    _recover_interrupted_trials(optuna, study)

    states = [trial.state for trial in study.trials]
    assert states == [
        optuna.trial.TrialState.FAIL,
        optuna.trial.TrialState.WAITING,
    ]
