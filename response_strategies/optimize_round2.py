"""Robust multi-scenario optimizer for the adaptive hidden-round strategy.

Each candidate is evaluated on ten isolated stress scenarios in parallel. The
objective penalizes average loss, instability, and the worst case. Generated
cases, baselines, results, databases and logs remain in ignored directories.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time
import traceback


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
STATE_DIRECTORY = Path(__file__).resolve().parent / "optuna_state"
DATABASE_PATH = STATE_DIRECTORY / "hidden_round.db"
BEST_PATH = STATE_DIRECTORY / "hidden_round_best.json"
LOG_PATH = STATE_DIRECTORY / "hidden_round_optimizer.log"
PID_PATH = STATE_DIRECTORY / "hidden_round_optimizer.pid"
STUDY_NAME = "wsc_hidden_round_robust_loss_v1"
FAILURE_LOSS = 1_000.0


def _require_optuna():
    try:
        import optuna
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Optuna is not installed. Run: .venv/bin/python -m pip install optuna"
        ) from exc
    return optuna


def _load_scenario_support():
    # Preserve the simulator's import order and avoid its package cycle.
    from simulation_model import Model
    from response_strategies.hidden_scenarios import (
        CASE_ROOT,
        create_context,
        load_case_definitions,
        prepare_case_directories,
    )
    return Model, CASE_ROOT, create_context, load_case_definitions, prepare_case_directories


def _suggest_parameters(trial):
    """Search only topology-independent controls used by the current strategy."""
    return {
        "wait_fraction": trial.suggest_float("wait_fraction", 0.10, 1.50),
        "wait_weight": trial.suggest_float("wait_weight", 0.0, 4.0),
        "berth_call_days": trial.suggest_float("berth_call_days", 0.0, 0.75),
        "berth_wait_weight": trial.suggest_float("berth_wait_weight", 0.0, 50_000.0),
        "detour_gain_ratio": trial.suggest_float("detour_gain_ratio", 0.5, 12.0, log=True),
        "minimum_saved_days": trial.suggest_float("minimum_saved_days", 0.0, 10.0),
        "lead_headway_factor": trial.suggest_float("lead_headway_factor", 0.0, 5.0),
        "port_lead_headway_factor": trial.suggest_float("port_lead_headway_factor", 0.0, 5.0),
        "port_skip_min_savings_ratio": trial.suggest_float("port_skip_min_savings_ratio", 0.0, 1.0),
        "bypass_closure_fraction": trial.suggest_float("bypass_closure_fraction", 0.0, 2.0),
    }


def _default_parameters():
    return {
        "wait_fraction": 0.932682014844758,
        "wait_weight": 1.0,
        "berth_call_days": 0.2143979900583058,
        "berth_wait_weight": 12_994.122976779254,
        "detour_gain_ratio": 5.0,
        "minimum_saved_days": 1.0,
        "lead_headway_factor": 1.5,
        "port_lead_headway_factor": 0.25,
        "port_skip_min_savings_ratio": 0.5,
        "bypass_closure_fraction": 0.5,
    }


def _environment_from_parameters(parameters):
    mapping = {
        "WSC_STRATEGY_MODE": "detour",
        "WSC_WAIT_FRACTION": parameters["wait_fraction"],
        "WSC_WAIT_WEIGHT": parameters["wait_weight"],
        "WSC_ESTIMATED_BERTH_CALL_DAYS": parameters["berth_call_days"],
        "WSC_BERTH_WAIT_WEIGHT": parameters["berth_wait_weight"],
        "WSC_DETOUR_GAIN_RATIO": parameters["detour_gain_ratio"],
        "WSC_MINIMUM_SAVED_DAYS": parameters["minimum_saved_days"],
        "WSC_LEAD_HEADWAY_FACTOR": parameters["lead_headway_factor"],
        "WSC_PORT_LEAD_HEADWAY_FACTOR": parameters["port_lead_headway_factor"],
        "WSC_PORT_SKIP_MIN_SAVINGS_RATIO": parameters["port_skip_min_savings_ratio"],
        "WSC_BYPASS_CLOSURE_FRACTION": parameters["bypass_closure_fraction"],
    }
    return {name: str(value) for name, value in mapping.items()}


def _set_strategy_environment(parameters):
    # A resumed shell may still contain route-specific variables from the old
    # Round 2 optimizer. They would silently reintroduce scenario overfitting.
    for name in tuple(os.environ):
        if name.startswith("WSC_"):
            os.environ.pop(name, None)
    environment = _environment_from_parameters(parameters)
    for name, value in environment.items():
        os.environ[name] = value
    return environment


def _run_periods(context, seed, warmup_days, simulation_days, interval_days):
    Model, _, _, _, _ = _load_scenario_support()
    sim = Model(context, seed=seed)
    if warmup_days:
        sim.warmup(period=dt.timedelta(days=warmup_days))
    values = []
    period_start = sim.clock_time
    elapsed = 0
    while elapsed < simulation_days:
        period_days = min(interval_days, simulation_days - elapsed)
        sim.run(duration=dt.timedelta(days=period_days))
        raw_days = sim.get_teu_weighted_average_transport_time_hours(
            period_start, sim.clock_time
        ) / 24.0
        values.append(float(f"{raw_days:.2f}"))
        period_start = sim.clock_time
        elapsed += period_days
    return values


def _loss_from_periods(baseline, disrupted, interval_days, simulation_days):
    if len(baseline) != len(disrupted):
        raise ValueError("Baseline and disruption period counts differ")
    loss = 0.0
    elapsed = 0
    for base_att, disruption_att in zip(baseline, disrupted):
        days = min(interval_days, simulation_days - elapsed)
        ratio = (1.0 if disruption_att <= 0 and base_att <= 0 else 0.0
                 if disruption_att <= 0 else base_att / disruption_att)
        loss += (1.0 - ratio) * days
        elapsed += days
    return loss


def _baseline_cache_path(case_root, case_id, warmup_days, simulation_days, interval_days):
    return Path(case_root) / case_id / (
        f"baseline_w{warmup_days}_d{simulation_days}_i{interval_days}.json"
    )


def _compute_baseline_task(definition, seed, warmup_days, simulation_days, interval_days):
    _, _, create_context, _, _ = _load_scenario_support()
    _set_strategy_environment(_default_parameters())
    started = time.perf_counter()
    context = create_context(definition, include_disruptions=False, warm_up_days=warmup_days)
    periods = _run_periods(context, seed, warmup_days, simulation_days, interval_days)
    return {
        "case": definition["id"], "seed": seed, "warmup_days": warmup_days,
        "simulation_days": simulation_days, "interval_days": interval_days,
        "period_att": periods, "runtime_seconds": time.perf_counter() - started,
    }


def _prepare_baselines(definitions, case_root, workers, seed, warmup_days, simulation_days, interval_days):
    baselines, missing = {}, []
    for definition in definitions:
        path = _baseline_cache_path(case_root, definition["id"], warmup_days, simulation_days, interval_days)
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("seed") == seed:
                baselines[definition["id"]] = payload["period_att"]
                continue
        missing.append(definition)
    if missing:
        print(f"Computing {len(missing)} missing paired baselines...", flush=True)
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_compute_baseline_task, definition, seed, warmup_days,
                                simulation_days, interval_days): definition
                for definition in missing
            }
            for future in concurrent.futures.as_completed(futures):
                definition = futures[future]
                payload = future.result()
                path = _baseline_cache_path(case_root, definition["id"], warmup_days,
                                            simulation_days, interval_days)
                path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                baselines[definition["id"]] = payload["period_att"]
                print(f"  baseline {definition['id']} ({payload['runtime_seconds']:.1f}s)", flush=True)
    return baselines


def _run_case_task(definition, baseline, parameters, seed, warmup_days, simulation_days, interval_days):
    _, _, create_context, _, _ = _load_scenario_support()
    environment = _set_strategy_environment(parameters)
    started = time.perf_counter()
    context = create_context(definition, include_disruptions=True, warm_up_days=warmup_days)
    periods = _run_periods(context, seed, warmup_days, simulation_days, interval_days)
    return {
        "case": definition["id"],
        "loss": _loss_from_periods(baseline, periods, interval_days, simulation_days),
        "period_att": periods, "runtime_seconds": time.perf_counter() - started,
        "environment": environment,
    }


def _robust_score(losses):
    """Penalize average degradation, dispersion, and the upper-tail result."""
    if not losses:
        return FAILURE_LOSS
    mean = statistics.fmean(losses)
    deviation = statistics.pstdev(losses) if len(losses) > 1 else 0.0
    worst_excess = max(0.0, max(losses) - mean)
    return mean + 0.35 * deviation + 0.25 * worst_excess


def _write_case_result(case_root, case_result, run_name, parameters, score):
    result_path = Path(case_root) / case_result["case"] / "results" / f"{run_name}.json"
    payload = {**case_result, "parameters": parameters, "robust_score": score}
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(result_path)


def evaluate_parameters(parameters, run_name, workers=10, seed=2026,
                        warmup_days=140, simulation_days=360, interval_days=5):
    _, case_root, _, load_cases, prepare_cases = _load_scenario_support()
    prepare_cases()
    definitions = load_cases()
    baselines = _prepare_baselines(definitions, case_root, workers, seed,
                                   warmup_days, simulation_days, interval_days)
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_run_case_task, definition, baselines[definition["id"]],
                            parameters, seed, warmup_days, simulation_days,
                            interval_days): definition
            for definition in definitions
        }
        for future in concurrent.futures.as_completed(futures):
            definition = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"case": definition["id"], "loss": FAILURE_LOSS,
                          "error": f"{type(exc).__name__}: {exc}",
                          "traceback": traceback.format_exc()}
            results.append(result)
            suffix = f" error={result['error']}" if "error" in result else ""
            print(f"  {result['case']}: loss={result['loss']:.6f}{suffix}", flush=True)
    results.sort(key=lambda item: item["case"])
    score = _robust_score([item["loss"] for item in results])
    for result in results:
        _write_case_result(case_root, result, run_name, parameters, score)
    return score, results


def _storage_url():
    return f"sqlite:///{DATABASE_PATH}"


def _create_study(optuna):
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name=STUDY_NAME, storage=_storage_url(), direction="minimize",
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=2026, multivariate=True,
                                           n_startup_trials=12),
    )
    if not study.trials:
        study.enqueue_trial(_default_parameters(),
                            user_attrs={"source": "current adaptive defaults"})
    return study


def _objective_factory(args):
    def objective(trial):
        parameters = _suggest_parameters(trial)
        started = time.perf_counter()
        score, results = evaluate_parameters(
            parameters, f"trial_{trial.number:06d}", args.workers, args.seed,
            args.warmup_days, args.simulation_days, args.interval_days)
        losses = {item["case"]: item["loss"] for item in results}
        trial.set_user_attr("case_losses", losses)
        trial.set_user_attr("mean_loss", statistics.fmean(losses.values()))
        trial.set_user_attr("worst_loss", max(losses.values()))
        trial.set_user_attr("runtime_seconds", time.perf_counter() - started)
        trial.set_user_attr("environment", _environment_from_parameters(parameters))
        return score
    return objective


def _write_best(study, trial=None):
    try:
        best = study.best_trial
    except ValueError:
        return
    payload = {
        "study": study.study_name, "trial": best.number,
        "robust_score": best.value, "mean_loss": best.user_attrs.get("mean_loss"),
        "worst_loss": best.user_attrs.get("worst_loss"),
        "case_losses": best.user_attrs.get("case_losses"),
        "parameters": best.params, "environment": best.user_attrs.get("environment"),
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = BEST_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(BEST_PATH)
    print(f"best trial={best.number} robust_score={best.value:.6f}", flush=True)


def run_worker(args):
    current_pid, existing_pid = os.getpid(), _read_pid()
    if existing_pid != current_pid and _pid_is_running(existing_pid):
        raise SystemExit(f"Optimizer is already running with PID {existing_pid}.")
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(f"{current_pid}\n", encoding="utf-8")
    study = _create_study(_require_optuna())
    print(f"Starting {STUDY_NAME}; trials={args.trials or 'unlimited'}; "
          f"cases=10; workers={args.workers}", flush=True)
    try:
        study.optimize(_objective_factory(args), n_trials=args.trials,
                       callbacks=[_write_best], catch=(Exception,), gc_after_trial=True)
    finally:
        if _read_pid() == current_pid:
            PID_PATH.unlink(missing_ok=True)


def launch_daemon(args):
    existing_pid = _read_pid()
    if _pid_is_running(existing_pid):
        print(f"Optimizer is already running with PID {existing_pid}.")
        return
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker",
               "--workers", str(args.workers), "--seed", str(args.seed),
               "--warmup-days", str(args.warmup_days),
               "--simulation-days", str(args.simulation_days),
               "--interval-days", str(args.interval_days)]
    if args.trials is not None:
        command.extend(["--trials", str(args.trials)])
    environment = dict(os.environ)
    environment["PYTHONUNBUFFERED"] = "1"
    with LOG_PATH.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=PROJECT_ROOT, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True,
                                   close_fds=True)
    PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")
    print(f"Optimizer started with PID {process.pid}.\nLog: {LOG_PATH}\nBest: {BEST_PATH}")


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


def _load_existing_study(optuna):
    if not DATABASE_PATH.is_file():
        raise SystemExit(f"Study not found: {DATABASE_PATH}")
    return optuna.load_study(study_name=STUDY_NAME, storage=_storage_url())


def show_status():
    pid = _read_pid()
    print(f"PID: {pid or '-'}\nRunning: {'yes' if _pid_is_running(pid) else 'no'}")
    print(BEST_PATH.read_text(encoding="utf-8").rstrip()
          if BEST_PATH.is_file() else "Best result: unavailable")
    print(f"Log: {LOG_PATH}")


def show_best_history(limit):
    study = _load_existing_study(_require_optuna())
    record, improvements = math.inf, []
    for trial in sorted(study.trials, key=lambda item: item.number):
        if trial.value is not None and trial.value < record:
            improvements.append(trial)
            record = trial.value
    for trial in improvements[-limit:]:
        print(f"trial={trial.number} robust_score={trial.value:.6f} "
              f"mean={trial.user_attrs.get('mean_loss')} "
              f"worst={trial.user_attrs.get('worst_loss')}")
        print(f"  params: {trial.params}")


def evaluate_stored_trial(args, trial_number=None):
    study = _load_existing_study(_require_optuna())
    trial = study.best_trial if trial_number is None else next(
        (item for item in study.trials if item.number == trial_number), None)
    if trial is None:
        raise SystemExit(f"Trial {trial_number} does not exist")
    score, _ = evaluate_parameters(
        trial.params, f"rerun_trial_{trial.number:06d}", args.workers, args.seed,
        args.warmup_days, args.simulation_days, args.interval_days)
    print(f"trial={trial.number} robust_score={score:.6f}")


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
    action.add_argument("--prepare-cases", action="store_true")
    action.add_argument("--evaluate-default", action="store_true")
    action.add_argument("--smoke", action="store_true")
    action.add_argument("--best-history", nargs="?", type=int, const=10)
    action.add_argument("--run-best", action="store_true")
    action.add_argument("--run-trial", type=int, metavar="NUMBER")
    parser.add_argument("--trials", type=int, default=None)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--warmup-days", type=int, default=140)
    parser.add_argument("--simulation-days", type=int, default=360)
    parser.add_argument("--interval-days", type=int, default=5)
    args = parser.parse_args(argv)
    if args.workers < 1 or args.interval_days < 1 or args.warmup_days < 0 or args.simulation_days < 1:
        parser.error("workers/interval/simulation must be positive and warmup non-negative")
    return args


def main(argv=None):
    args = parse_arguments(argv)
    if args.status:
        show_status()
    elif args.best_history is not None:
        show_best_history(args.best_history)
    elif args.stop:
        stop_daemon()
    elif args.prepare_cases:
        _, case_root, _, _, prepare_cases = _load_scenario_support()
        paths = prepare_cases(overwrite=True)
        print(f"Prepared {len(paths)} cases under {case_root}")
    elif args.smoke:
        score, _ = evaluate_parameters(_default_parameters(), "smoke_default",
                                       args.workers, args.seed, 5, 15, 5)
        print(f"smoke robust_score={score:.6f}")
    elif args.evaluate_default:
        score, _ = evaluate_parameters(_default_parameters(), "current_defaults",
                                       args.workers, args.seed, args.warmup_days,
                                       args.simulation_days, args.interval_days)
        print(f"default robust_score={score:.6f}")
    elif args.daemon:
        launch_daemon(args)
    elif args.run_best:
        evaluate_stored_trial(args)
    elif args.run_trial is not None:
        evaluate_stored_trial(args, args.run_trial)
    else:
        run_worker(args)


if __name__ == "__main__":
    main()
