"""Injury risk: episodes from missed fixtures, point-in-time record features, the per-league report."""

from __future__ import annotations

import pandas as pd
from dugout_models.injury import _injury_rows, episodes, history_features, report_md


def _missed(rows):
    return pd.DataFrame(rows, columns=["player_id", "date", "reason", "type"]).assign(
        date=lambda d: pd.to_datetime(d.date)
    )


def test_episodes_split_on_gaps_and_skip_non_injuries():
    df = _injury_rows(
        _missed(
            [
                ("a", "2023-01-01", "Hamstring Injury", "Missing Fixture"),
                ("a", "2023-01-08", "Hamstring Injury", "Missing Fixture"),
                ("a", "2023-03-01", "Knee Injury", "Missing Fixture"),
                ("a", "2023-04-01", "Suspended", "Missing Fixture"),
                ("b", "2023-01-01", "Injury", "Questionable"),
            ]
        )
    )
    ep = episodes(df)
    assert len(ep) == 2 and set(ep.player_id) == {"a"}
    first = ep.iloc[0]
    assert first.muscle == 1.0 and first.days_out == 14  # last missed fixture a week on, plus a week


def test_history_features_use_only_the_past_and_label_the_next_fortnight():
    ep = episodes(
        _missed([("a", "2023-01-10", "Calf Injury", "Missing Fixture"), ("a", "2023-06-01", "Knock", "x")])
    )
    p = pd.DataFrame(
        {"player_id": ["a", "a", "b"], "date": pd.to_datetime(["2023-01-01", "2023-02-01", "2023-02-01"])}
    )
    f = history_features(p, ep)
    assert f.label.tolist() == [True, False, False]  # injured nine days after the first match
    assert f.prev_episodes.tolist() == [0, 1, 0]  # the spell after the first match is not known on that day
    assert f.days_since_episode.tolist() == [999, 22, 999]
    assert f.last_muscle.tolist() == [0, 1, 0]
    assert "label" not in history_features(p, ep, label=False)


def test_report_lists_unscored_leagues():
    r = {"auc": 0.6, "brier": 0.03, "top_decile_lift": 2.0}
    league = {
        "name": "Eredivisie",
        "test_rows": 100,
        "positive_rate_test": 0.015,
        "results": {"logistic": r, "logistic_pooled": r, "history_pooled": r, "base_rate": r},
        "validation_auc_history": 0.53,
        "scored": False,
    }
    md = report_md(
        {
            "generated_at": "2026-10-19",
            "episodes": 10,
            "test_rows": 100,
            "positive_rate_test": 0.02,
            "results": {"logistic": r},
            "logistic_coefficients": {"age": 0.1},
            "leagues": {"eredivisie": league, "ligue_1": {"name": "Ligue 1", "scored": False}},
        }
    )
    assert "| Eredivisie | 100 | 1.50% |" in md and md.count("| no") == 2
