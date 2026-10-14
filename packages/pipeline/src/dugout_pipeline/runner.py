"""Runs a list of adapters, records each run in `source_runs`, and decides whether the job failed."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dugout_pipeline.adapters.base import IngestContext, MissingCredential, SourceDisabled
from dugout_pipeline.registry import ADAPTERS, build

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    source: str
    ok: bool
    rows: dict[str, int] = field(default_factory=dict)
    message: str = ""
    seconds: float = 0.0
    required: bool = False
    skipped: bool = False


@dataclass
class JobResult:
    results: list[SourceResult]

    @property
    def failed_required(self) -> list[SourceResult]:
        return [r for r in self.results if r.required and not r.ok and not r.skipped]

    @property
    def ok(self) -> bool:
        return not self.failed_required


def run(ctx: IngestContext, sources: list[str]) -> JobResult:
    results = []
    for name in sources:
        cls = ADAPTERS[name]
        started, t0 = datetime.now(UTC), time.monotonic()
        res = SourceResult(name, ok=False, required=cls.required)
        adapter = None
        try:
            adapter = build(name, ctx)
            res.rows = adapter.ingest() or {}
            res.ok = True
        except (SourceDisabled, MissingCredential) as exc:
            res.skipped, res.message = True, str(exc)
        except Exception as exc:  # one source failing must not take down the others
            log.exception("source %s failed", name)
            res.message = f"{type(exc).__name__}: {exc}"[:500]
        finally:
            if adapter:
                adapter.close()
        res.seconds = round(time.monotonic() - t0, 1)
        ctx.con.execute(
            "INSERT OR REPLACE INTO source_runs VALUES (?,?,?,?,?,?,?)",
            [
                ctx.run_id,
                name,
                started,
                datetime.now(UTC),
                res.ok,
                sum(res.rows.values()),
                res.message or None,
            ],
        )
        results.append(res)
    return JobResult(results)


def format_report(job: JobResult) -> str:
    lines = [f"{'source':<24}{'status':<10}{'secs':>7}  rows / message"]
    for r in job.results:
        status = "skipped" if r.skipped else "ok" if r.ok else ("FAILED" if r.required else "failed")
        detail = ", ".join(f"{k}={v}" for k, v in r.rows.items()) if r.ok else r.message
        lines.append(f"{r.source:<24}{status:<10}{r.seconds:>7}  {detail}")
    lines.append(
        "job: "
        + (
            "OK"
            if job.ok
            else "FAILED (required source failed: " + ", ".join(r.source for r in job.failed_required) + ")"
        )
    )
    return "\n".join(lines)
