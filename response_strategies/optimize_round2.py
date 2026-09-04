"""Persistent, resumable Optuna search for the Round 2 response strategy.

Run indefinitely in the background from the project root::

    .venv/bin/python response_strategies/optimize_round2.py --daemon

Inspect it with ``--status``.  The SQLite study, log, PID and best-parameter
JSON are stored under ``response_strategies/optuna_state`` and ignored by Git.
Stop a foreground worker with Ctrl+C.  A daemon can be stopped with ``--stop``.
Use ``--run-best`` or ``--run-trial N`` to materialize a selected combination
through ``main.py``: this writes the normal Output/ and Logs/ and opens the
dashboard.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
STATE_DIRECTORY = Path(__file__).resolve().parent / "optuna_state"
DATABASE_PATH = STATE_DIRECTORY / "round2.db"
BEST_PATH = STATE_DIRECTORY / "best.json"
LOG_PATH = STATE_DIRECTORY / "optimizer.log"
PID_PATH = STATE_DIRECTORY / "optimizer.pid"
BASELINE_PATH = PROJECT_ROOT / "Output" / "Baseline_ATT_By_Statistics_Interval.csv"
STUDY_NAME = "wsc_round2_loss"
KNOWN_BEST_LOSS = 12.395073988811255


def _require_optuna():
    try:
        import optuna
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Optuna is not installed in this venv. Run: "
            ".venv/bin/python -m pip install optuna"
        ) from exc
    return optuna


def _storage_url() -> str:
    return f"sqlite:///{DATABASE_PATH}"


def _load_baseline_periods():
    if not BASELINE_PATH.is_file():
        raise FileNotFoundError(f"Baseline ATT not found: {BASELINE_PATH}")
    periods = []
    with BASELINE_PATH.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if not row.get("PeriodIndex"):
                continue
            periods.append(
                {
                    "index": int(row["PeriodIndex"]),
                    "start": int(row["StartDay"]),
                    "end": int(row["EndDay"]),
                    "att": float(row["AverageTransportTime"]),
                }
            )
    if not periods:
        raise ValueError(f"Baseline ATT has no periods: {BASELINE_PATH}")
    return periods


def _suggest_parameters(trial):
    return {
        "wait_fraction": trial.suggest_float("wait_fraction", 0.10, 1.00),
        "berth_call_days": trial.suggest_float("berth_call_days", 0.00, 0.35),
        "lead_margin_s5": trial.suggest_float("lead_margin_s5", 0.0, 10.0),
        "lead_margin_s4": trial.suggest_float("lead_margin_s4", 0.0, 5.0),
        "lead_margin_s9": trial.suggest_float("lead_margin_s9", 0.0, 5.0),
        "port_lead_margin_s7": trial.suggest_float(
            "port_lead_margin_s7", 0.0, 5.0
        ),
        "port_lead_margin_s1": trial.suggest_float(
            "port_lead_margin_s1", 0.0, 5.0
        ),
        "berth_wait_weight": trial.suggest_float(
            "berth_wait_weight", 0.0, 30_000.0
        ),
        "enable_s4_detour": trial.suggest_categorical(
            "enable_s4_detour", [True, False]
        ),
        "enable_s9_detour": trial.suggest_categorical(
            "enable_s9_detour", [True, False]
        ),
        "enable_s7_skip": trial.suggest_categorical(
            "enable_s7_skip", [True, False]
        ),
        "enable_s1_bypass": trial.suggest_categorical(
            "enable_s1_bypass", [False, True]
        ),
    }


def _apply_parameters(parameters):
    environment = {
        "WSC_ROUND2_MODE": "detour",
        "WSC_WAIT_FRACTION": parameters.get("wait_fraction", 0.5),
        "WSC_ESTIMATED_BERTH_CALL_DAYS": parameters.get(
            "berth_call_days", 0.125
        ),
        "WSC_LEAD_MARGIN_S5": parameters.get("lead_margin_s5", 1.0),
        "WSC_LEAD_MARGIN_S4": parameters.get("lead_margin_s4", 1.0),
        "WSC_LEAD_MARGIN_S9": parameters.get("lead_margin_s9", 1.0),
        "WSC_PORT_LEAD_MARGIN_S7": parameters.get("port_lead_margin_s7", 1.0),
        "WSC_PORT_LEAD_MARGIN_S1": parameters.get("port_lead_margin_s1", 1.0),
        "WSC_BERTH_WAIT_WEIGHT": parameters.get("berth_wait_weight", 10_000.0),
        # S5's 75-day avoided delay makes its detour non-negotiable.
        "WSC_ENABLE_S5_DETOUR": True,
        "WSC_ENABLE_S4_DETOUR": parameters.get("enable_s4_detour", True),
        "WSC_ENABLE_S9_DETOUR": parameters.get("enable_s9_detour", True),
        "WSC_ENABLE_S7_SKIP": parameters.get("enable_s7_skip", True),
        "WSC_ENABLE_S1_BYPASS": parameters.get("enable_s1_bypass", False),
    }
    for name, value in environment.items():
        os.environ[name] = "1" if value is True else "0" if value is False else str(value)
    return environment


def _objective_factory(optuna, baseline_periods):
    # Imports are delayed so --status and --daemon remain fast.
    from config.simulation_config import (
        STATISTICS_INTERVAL_DAYS,
        WARM_UP_DAYS,
    )
    from scenario_builders import create_with_disruption
    from simulation_model import Model

    def objective(trial):
        parameters = _suggest_parameters(trial)
        environment = _apply_parameters(parameters)
        trial.set_user_attr("environment", environment)
        started = time.perf_counter()

        sim = Model(create_with_disruption(), seed=2026)
        sim.warmup(period=dt.timedelta(days=WARM_UP_DAYS))
        cumulative_loss = 0.0
        period_start_time = sim.clock_time

        for period in baseline_periods:
            expected_days = period["end"] - period["start"] + 1
            if expected_days != STATISTICS_INTERVAL_DAYS:
                raise ValueError(
                    f"Unexpected baseline interval {period['index']}: {expected_days} days"
                )
            sim.run(duration=dt.timedelta(days=expected_days))
            raw_att_days = (
                sim.get_teu_weighted_average_transport_time_hours(
                    period_start_time, sim.clock_time
                )
                / 24.0
            )
            # Match write_att_by_period/dashboard precision exactly.
            disruption_att = float(f"{raw_att_days:.2f}")
            baseline_att = period["att"]
            ratio = (
                1.0
                if disruption_att <= 0 and baseline_att <= 0
                else 0.0
                if disruption_att <= 0
                else baseline_att / disruption_att
            )
            cumulative_loss += (1.0 - ratio) * expected_days
            period_start_time = sim.clock_time

            trial.report(cumulative_loss, step=period["index"])
            if period["index"] % 12 == 0:
                elapsed = time.perf_counter() - started
                print(
                    f"trial={trial.number} day={period['end']} "
                    f"partial_loss={cumulative_loss:.6f} elapsed={elapsed:.1f}s",
                    flush=True,
                )
            if trial.should_prune():
                raise optuna.TrialPruned(
                    f"pruned at day {period['end']} with loss {cumulative_loss:.6f}"
                )

        trial.set_user_attr("runtime_seconds", time.perf_counter() - started)
        return cumulative_loss

    return objective


def _known_parameters():
    return {
        "wait_fraction": 0.5,
        "berth_call_days": 0.125,
        "lead_margin_s5": 1.0,
        "lead_margin_s4": 1.0,
        "lead_margin_s9": 1.0,
        "port_lead_margin_s7": 1.0,
        "port_lead_margin_s1": 1.0,
        "berth_wait_weight": 10_000.0,
        "enable_s4_detour": True,
        "enable_s9_detour": True,
        "enable_s7_skip": True,
        "enable_s1_bypass": False,
    }


def _ensure_known_best(optuna, study):
    if study.trials:
        return
    distributions = {
        "wait_fraction": optuna.distributions.FloatDistribution(0.10, 1.00),
        "berth_call_days": optuna.distributions.FloatDistribution(0.00, 0.35),
        "lead_margin_s5": optuna.distributions.FloatDistribution(0.0, 10.0),
        "lead_margin_s4": optuna.distributions.FloatDistribution(0.0, 5.0),
        "lead_margin_s9": optuna.distributions.FloatDistribution(0.0, 5.0),
        "port_lead_margin_s7": optuna.distributions.FloatDistribution(0.0, 5.0),
        "port_lead_margin_s1": optuna.distributions.FloatDistribution(0.0, 5.0),
        "berth_wait_weight": optuna.distributions.FloatDistribution(
            0.0, 30_000.0
        ),
        "enable_s4_detour": optuna.distributions.CategoricalDistribution(
            [True, False]
        ),
        "enable_s9_detour": optuna.distributions.CategoricalDistribution(
            [True, False]
        ),
        "enable_s7_skip": optuna.distributions.CategoricalDistribution(
            [True, False]
        ),
        "enable_s1_bypass": optuna.distributions.CategoricalDistribution(
            [False, True]
        ),
    }
    study.add_trial(
        optuna.trial.create_trial(
            params=_known_parameters(),
            distributions=distributions,
            value=KNOWN_BEST_LOSS,
            user_attrs={"source": "validated deterministic run"},
        )
    )
    # Resume the interrupted high-value structural experiment first.
    s1_trial = dict(_known_parameters())
    s1_trial["enable_s1_bypass"] = True
    study.enqueue_trial(s1_trial, user_attrs={"source": "queued S1 comparison"})


def _recover_interrupted_trials(optuna, study):
    """Fail and requeue trials left RUNNING after an interrupted process."""
    running = study.get_trials(
        deepcopy=False,
        states=(optuna.trial.TrialState.RUNNING,),
    )
    for frozen_trial in running:
        study.tell(frozen_trial.number, state=optuna.trial.TrialState.FAIL)
        if frozen_trial.params:
            study.enqueue_trial(
                frozen_trial.params,
                user_attrs={"source": f"recovered interrupted trial {frozen_trial.number}"},
            )
        print(f"Recovered interrupted trial {frozen_trial.number}.", flush=True)


def _write_best(study, trial=None):
    try:
        best = study.best_trial
    except ValueError:
        return
    payload = {
        "study": study.study_name,
        "trial": best.number,
        "loss": best.value,
        "parameters": best.params,
        "environment": best.user_attrs.get("environment")
        or _environment_from_parameters(best.params),
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = BEST_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(BEST_PATH)
    print(
        f"best trial={best.number} loss={best.value:.6f} params={best.params}",
        flush=True,
    )


def _environment_from_parameters(parameters):
    environment = {}
    original = dict(os.environ)
    try:
        environment = _apply_parameters(parameters)
    finally:
        os.environ.clear()
        os.environ.update(original)
    return environment


def _create_study(optuna):
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name=STUDY_NAME,
        storage=_storage_url(),
        direction="minimize",
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(
            seed=2026,
            multivariate=True,
            n_startup_trials=10,
        ),
        pruner=optuna.pruners.MedianPruner(
            n_startup_trials=10,
            n_warmup_steps=24,
            interval_steps=6,
        ),
    )
    _recover_interrupted_trials(optuna, study)
    _ensure_known_best(optuna, study)
    _write_best(study)
    return study


def run_worker(max_trials=None):
    current_pid = os.getpid()
    existing_pid = _read_pid()
    if existing_pid != current_pid and _pid_is_running(existing_pid):
        raise SystemExit(f"Optimizer is already running with PID {existing_pid}.")
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(f"{current_pid}\n", encoding="utf-8")

    optuna = _require_optuna()
    baseline_periods = _load_baseline_periods()
    study = _create_study(optuna)
    print(
        f"Starting study {STUDY_NAME!r}; trials={max_trials or 'unlimited'}; "
        f"storage={DATABASE_PATH}",
        flush=True,
    )
    try:
        study.optimize(
            _objective_factory(optuna, baseline_periods),
            n_trials=max_trials,
            callbacks=[_write_best],
            catch=(Exception,),
            gc_after_trial=True,
        )
    finally:
        if _read_pid() == current_pid:
            PID_PATH.unlink(missing_ok=True)


def _read_pid():
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, TypeError, ValueError):
        return None


def _pid_is_running(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def launch_daemon(max_trials=None):
    existing_pid = _read_pid()
    if _pid_is_running(existing_pid):
        print(f"Optimizer is already running with PID {existing_pid}.")
        return
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    # Execute this file directly.  Importing it with ``-m`` first evaluates
    # response_strategies/__init__.py, whose existing simulator imports form a
    # circular dependency before this standalone runner gets control.
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    if max_trials is not None:
        command.extend(["--trials", str(max_trials)])
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    with LOG_PATH.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")
    print(f"Optimizer started with PID {process.pid}.")
    print(f"Log: {LOG_PATH}")
    print(f"Best result: {BEST_PATH}")


def show_status():
    pid = _read_pid()
    print(f"PID: {pid or '-'}")
    print(f"Running: {'yes' if _pid_is_running(pid) else 'no'}")
    if BEST_PATH.is_file():
        print(BEST_PATH.read_text(encoding="utf-8").rstrip())
    else:
        print("Best result: not available yet")
    print(f"Log: {LOG_PATH}")


def _load_existing_study(optuna):
    if not DATABASE_PATH.is_file():
        raise SystemExit(
            f"Optuna study not found: {DATABASE_PATH}. Start the optimizer first."
        )
    try:
        return optuna.load_study(
            study_name=STUDY_NAME,
            storage=_storage_url(),
        )
    except KeyError as exc:
        raise SystemExit(
            f"Study {STUDY_NAME!r} does not exist in {DATABASE_PATH}."
        ) from exc


def _find_trial(study, trial_number):
    for trial in study.get_trials(deepcopy=False):
        if trial.number == trial_number:
            return trial
    raise SystemExit(
        f"Trial {trial_number} does not exist in study {STUDY_NAME!r}."
    )


def run_materialized_trial(trial_number=None):
    """Run one stored combination through main.py and open its dashboard."""
    optuna = _require_optuna()
    study = _load_existing_study(optuna)
    if trial_number is None:
        try:
            trial = study.best_trial
        except ValueError as exc:
            raise SystemExit("The study does not have a completed trial yet.") from exc
        selection = "best"
    else:
        trial = _find_trial(study, trial_number)
        selection = "selected"

    if not trial.params:
        raise SystemExit(
            f"Trial {trial.number} has no parameters and cannot be executed."
        )

    parameter_environment = _environment_from_parameters(trial.params)
    child_environment = dict(os.environ)
    child_environment.update(
        {
            name: "1" if value is True else "0" if value is False else str(value)
            for name, value in parameter_environment.items()
        }
    )
    child_environment["PYTHONUNBUFFERED"] = "1"

    value = "not completed" if trial.value is None else f"{trial.value:.6f}"
    print(
        f"Running {selection} trial {trial.number}: "
        f"state={trial.state.name}, stored_loss={value}",
        flush=True,
    )
    print(f"Parameters: {trial.params}", flush=True)
    print(
        f"This run will replace the simulation CSVs in {PROJECT_ROOT / 'Output'}, "
        "write a normal log under Logs/, and open the dashboard when complete.",
        flush=True,
    )

    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py")],
        cwd=PROJECT_ROOT,
        env=child_environment,
        check=False,
    )
    if completed.returncode:
        raise SystemExit(
            f"Trial {trial.number} simulation failed with exit code "
            f"{completed.returncode}."
        )
    return completed.returncode


def stop_daemon():
    pid = _read_pid()
    if not _pid_is_running(pid):
        print("Optimizer is not running.")
        return
    os.kill(pid, signal.SIGTERM)
    print(f"Sent SIGTERM to optimizer PID {pid}.")


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--daemon", action="store_true")
    action.add_argument("--worker", action="store_true")
    action.add_argument("--status", action="store_true")
    action.add_argument("--stop", action="store_true")
    action.add_argument(
        "--run-best",
        action="store_true",
        help="Run the best stored combination, write Output/ and open dashboard.",
    )
    action.add_argument(
        "--run-trial",
        type=int,
        metavar="NUMBER",
        help="Run one stored trial, write Output/ and open dashboard.",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=None,
        help="Maximum trials; omit for an indefinite search.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    if args.status:
        show_status()
    elif args.stop:
        stop_daemon()
    elif args.daemon:
        launch_daemon(args.trials)
    elif args.run_best:
        run_materialized_trial()
    elif args.run_trial is not None:
        run_materialized_trial(args.run_trial)
    else:
        run_worker(args.trials)


if __name__ == "__main__":
    main()
