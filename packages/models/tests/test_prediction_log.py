from datetime import UTC, datetime

from dugout_models.publish import load_prediction_log, save_prediction_log
from dugout_pipeline.db import connect


def _add(con, match_id, as_of, p_home):
    kickoff = datetime(2026, 10, 18, 14, tzinfo=UTC)
    con.execute(
        "INSERT INTO prediction_log VALUES (?, ?, ?, 'predictor@test', ?, 0.25, ?)",
        [match_id, as_of, kickoff, p_home, round(0.75 - p_home, 4)],
    )


def test_prediction_log_round_trips_and_appends(tmp_path):
    path = tmp_path / "prediction_log.csv"
    a = connect()
    _add(a, "m1", datetime(2026, 10, 16, 2, 30, tzinfo=UTC), 0.4)
    assert save_prediction_log(a, path) == 1

    # a fresh warehouse (evicted CI cache) gets the committed rows back, then appends its own
    b = connect()
    assert load_prediction_log(b, path) == 1
    _add(b, "m2", datetime(2026, 10, 17, 2, 30, tzinfo=UTC), 0.5)
    assert save_prediction_log(b, path) == 2
    rows = b.execute("SELECT match_id, as_of, p_home FROM prediction_log ORDER BY as_of").fetchall()
    assert [r[0] for r in rows] == ["m1", "m2"]
    assert rows[0][1] == datetime(2026, 10, 16, 2, 30, tzinfo=UTC) and rows[0][2] == 0.4

    # loading again changes nothing (append-only, no duplicates)
    assert load_prediction_log(b, path) == 0
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith("match_id,as_of,")
