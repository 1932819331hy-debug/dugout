from dugout_pipeline.adapters.base import SourceAdapter
from dugout_pipeline.registry import ADAPTERS, JOBS
from dugout_pipeline.runner import format_report, run


class _Boom(SourceAdapter):
    name = "boom"

    def ingest(self):
        raise RuntimeError("upstream 502")


class _BoomRequired(_Boom):
    name = "boom_required"
    required = True


def test_optional_failure_does_not_fail_job(ctx, monkeypatch):
    monkeypatch.setitem(ADAPTERS, "boom", _Boom)
    job = run(ctx, ["fpl", "boom"])
    assert job.ok
    assert [r.ok for r in job.results] == [True, False]
    msg = ctx.con.execute("SELECT message FROM source_runs WHERE source='boom'").fetchone()[0]
    assert "upstream 502" in msg
    assert "failed" in format_report(job)


def test_required_failure_fails_job(ctx, monkeypatch):
    monkeypatch.setitem(ADAPTERS, "boom_required", _BoomRequired)
    job = run(ctx, ["boom_required"])
    assert not job.ok and "FAILED" in format_report(job)


def test_missing_key_is_skipped_not_crashed(ctx):
    ctx.settings = ctx.settings.model_copy(update={"guardian_api_key": None})
    job = run(ctx, ["fpl", "guardian"])
    assert job.results[1].skipped


def test_jobs_reference_known_adapters():
    for sources in JOBS.values():
        assert set(sources) <= set(ADAPTERS)
    assert JOBS["nightly"][:2] == ["reep", "fpl"]  # ids and clubs first
    assert "transfermarkt" not in JOBS["nightly"]  # scraper never runs in CI
