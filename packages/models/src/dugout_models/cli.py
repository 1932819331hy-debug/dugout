"""`dugout-models` command line: backtests and model fitting."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from dugout_pipeline.db import connect
from dugout_pipeline.settings import REPO_ROOT, get_settings

BACKTESTS = REPO_ROOT / "docs" / "backtests"


def cmd_backtest(args) -> int:
    con = connect(args.db or get_settings().warehouse_path)
    if args.model == "predictor":
        from dugout_models.backtest import run

        report = run(con, args.seasons, bayes=not args.no_bayes, out_dir=BACKTESTS, name=args.name)
        print(json.dumps(report["results"], indent=1))
        print("beats Elo:", report["beats_elo"])
        return 0 if all(all(v.values()) for v in report["beats_elo"].values()) else 1
    raise SystemExit(f"unknown model {args.model}")


def main(argv: list[str] | None = None) -> int:
    if os.name == "nt":
        # PyTensor's C backend needs a modern g++; NUTS runs through nutpie/numba instead, so skip C compilation.
        os.environ.setdefault("PYTENSOR_FLAGS", "cxx=")
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    logging.getLogger("pymc").setLevel(logging.ERROR)
    p = argparse.ArgumentParser(prog="dugout-models")
    p.add_argument("--db")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("backtest")
    s.add_argument("model", choices=["predictor"])
    s.add_argument("--seasons", nargs="+", default=["2024-25", "2025-26"])
    s.add_argument("--no-bayes", action="store_true", help="skip the (slow) NUTS Dixon–Coles baseline")
    s.add_argument("--name", default="predictor", help="report file name in docs/backtests/")
    s.set_defaults(fn=cmd_backtest)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
