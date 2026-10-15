"""`dugout-agents`: ask a question, build club dossiers, run the evaluation."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dugout_pipeline.settings import REPO_ROOT

CLUBS_DIR = REPO_ROOT / "data" / "clubs"


def _ctx(args):
    from dugout_agents.llm import from_settings
    from dugout_agents.runtime import make_context

    return make_context(llm=None if args.no_llm else from_settings(), db=args.db)


def cmd_ask(args) -> int:
    from dugout_agents.graph import run

    ctx = _ctx(args)
    state = run(ctx, args.question, args.club)
    print(f"route: {state['agents']}  club: {state['club']}  focus: {state.get('focus')}\n")
    for sec in [*state["sections"], state["summary"]]:
        print(f"== {sec.title} [{sec.status}, {sec.writer}]")
        print(sec.text or "(nothing published)")
        for w in sec.withheld:
            print(f"   withheld ({w['status']}): {w['reason']}")
        print()
    return 0


def cmd_dossier(args) -> int:
    from dugout_agents import dossier

    ctx = _ctx(args)
    ok = True
    for club in args.clubs:
        doc, _ = dossier.build(ctx, club)
        v = doc["verification"]
        if v["sections_published"] == 0 or not v["stat_auditor"]["ok"]:
            print(f"{club}: nothing passed verification; not written", file=sys.stderr)
            ok = False
            continue
        path = dossier.write(doc, CLUBS_DIR)
        print(f"{club}: {path.relative_to(REPO_ROOT)}  {v}")
    return 0 if ok else 1


def cmd_eval(args) -> int:
    from dugout_agents.evaluate import run_eval

    ctx = _ctx(args)
    report = run_eval(ctx, out_dir=REPO_ROOT / "docs" / "backtests", limit=args.limit)
    print({k: v for k, v in report["summary"].items()})
    return 0 if report["summary"]["untraceable_number_rate"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    p = argparse.ArgumentParser(prog="dugout-agents")
    p.add_argument("--db")
    p.add_argument("--no-llm", action="store_true", help="deterministic templates only")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ask")
    s.add_argument("question")
    s.add_argument("--club", default="liverpool")
    s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("dossier")
    s.add_argument("clubs", nargs="*", default=["liverpool"])
    s.set_defaults(fn=cmd_dossier)
    s = sub.add_parser("eval")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
