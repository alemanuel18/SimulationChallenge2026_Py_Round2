"""Development-only evaluator for published rounds and candidate strategies."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def load_baseline(path: Path) -> list[dict[str, float | int]]:
    periods = []
    with path.open(newline="", encoding="utf-8") as source:
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
        raise ValueError(f"Baseline ATT has no periods: {path}")
    return periods


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("round_directory", type=Path)
    parser.add_argument(
        "--strategy",
        type=Path,
        help=(
            "Inject this round2_strategy.py while leaving the evaluated "
            "round directory unchanged."
        ),
    )
    args = parser.parse_args()

    round_directory = args.round_directory.resolve()
    os.chdir(round_directory)
    sys.path.insert(0, str(round_directory))
    strategy_path = args.strategy.resolve() if args.strategy else None
    if strategy_path is not None:
        sys.meta_path.insert(0, _CandidateStrategyFinder(strategy_path))

    # Preserve the simulator's normal import order.
    import main as simulation_main  # noqa: F401
    from config.simulation_config import WARM_UP_DAYS
    from scenario_builders import create_with_disruption
    from simulation_model import Model

    baseline = load_baseline(
        round_directory / "Output" / "Baseline_ATT_By_Statistics_Interval.csv"
    )
    started = time.perf_counter()
    simulation = Model(create_with_disruption(), seed=2026)
    simulation.warmup(period=dt.timedelta(days=WARM_UP_DAYS))
    period_start_time = simulation.clock_time
    cumulative_loss = 0.0
    measured = []

    for period in baseline:
        period_days = int(period["end"]) - int(period["start"]) + 1
        simulation.run(duration=dt.timedelta(days=period_days))
        raw_att = (
            simulation.get_teu_weighted_average_transport_time_hours(
                period_start_time,
                simulation.clock_time,
            )
            / 24.0
        )
        disruption_att = float(f"{raw_att:.2f}")
        baseline_att = float(period["att"])
        ratio = (
            1.0
            if disruption_att <= 0 and baseline_att <= 0
            else 0.0
            if disruption_att <= 0
            else baseline_att / disruption_att
        )
        period_loss = (1.0 - ratio) * period_days
        cumulative_loss += period_loss
        measured.append(
            {
                "period": period["index"],
                "baseline_att": baseline_att,
                "disruption_att": disruption_att,
                "period_loss": period_loss,
            }
        )
        period_start_time = simulation.clock_time
        if int(period["index"]) % 12 == 0:
            print(
                f"period={period['index']} day={period['end']} "
                f"loss={cumulative_loss:.6f}",
                flush=True,
            )

    result = {
        "round_directory": str(round_directory),
        "strategy_path": str(strategy_path) if strategy_path else None,
        "loss": cumulative_loss,
        "runtime_seconds": time.perf_counter() - started,
        "periods": measured,
    }
    output_name = (
        "Adaptive_Candidate_Evaluation.json"
        if strategy_path is not None
        else "Candidate_Evaluation.json"
    )
    output_path = round_directory / "Output" / output_name
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "periods"}))
    print(f"details={output_path}")


class _CandidateStrategyFinder(importlib.abc.MetaPathFinder):
    """Redirect only the candidate module to a file outside the target round."""

    def __init__(self, strategy_path: Path):
        self.strategy_path = strategy_path

    def find_spec(self, fullname, path, target=None):
        if fullname != "response_strategies.round2_strategy":
            return None
        return importlib.util.spec_from_file_location(fullname, self.strategy_path)


if __name__ == "__main__":
    main()
