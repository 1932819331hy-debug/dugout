"""Injury risk: discrete-time hazard of a new injury absence starting within the next 14 days.

At-risk rows: every league match a player played. Premier League: FPL history (2022-23 on). Other leagues:
transfermarkt-datasets appearances (CC0) in the league, 2022-23 to 2024-25. An *injury episode* starts at the first
fixture a player misses with an injury reason (API-Football free-plan injury lists, 2022–2024, per league);
suspensions, illness-free "coach's decision" and personal reasons are excluded.
Features use only information up to and including the match: age, recent load (minutes over the last 3
matches and 28 days, matches in the last 14 days), injury history (previous episodes, days since the last),
position. Logistic regression (calibrated, interpretable) vs gradient boosting; train 2022-24, test 2024-25.

Outside the Premier League there is no current minutes source (transfermarkt-datasets stops in July 2026), so the
live tier there comes from a history-only model (age, position, injury record) pooled over the six leagues. A league
is scored only if that model ranked its 2023-24 rows usefully when trained on 2022-23 (`scored`), decided before
looking at the 2024-25 test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from dugout_pipeline.adapters.api_football import injury_file
from dugout_pipeline.clubs import league_config, leagues
from dugout_pipeline.ids import attach_catalogue
from dugout_pipeline.settings import REPO_ROOT
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

INJURY_DIR = REPO_ROOT / "data" / "raw" / "api_football"
TM_DIR = REPO_ROOT / "data" / "raw" / "transfermarkt"
BACKTEST_JSON = REPO_ROOT / "docs" / "backtests" / "injury.json"  # which leagues are scored
PL = "premier_league"
HORIZON_DAYS = 14
API_SEASONS = (2022, 2023, 2024)
SEASONS = ("2022-23", "2023-24", "2024-25")
TEST_SEASON = "2024-25"
MUSCLE = ("thigh", "hamstring", "muscle", "calf", "groin", "adductor")
NOT_INJURY = (
    "suspend",
    "red card",
    "yellow card",
    "coach",
    "personal",
    "international",
    "rest",
    "inactive",
    "loan",
    "transfer",
    "birth",
    "family",
    "lack of fitness",
    "ineligible",
)
FEATURES = [
    "age",
    "min_last3",
    "min_28d",
    "matches_14d",
    "prev_episodes",
    "days_since_episode",
    "is_gk",
    "is_def",
    "is_mid",
    "is_fwd",
    "season_week",
    "age2",
    "min_7d",
    "episodes_365",
    "days_lost_365",
    "last_muscle",
]
# what is known about a player outside the Premier League today: no current minutes
HISTORY_FEATURES = [
    "age",
    "age2",
    "is_gk",
    "is_def",
    "is_mid",
    "is_fwd",
    "prev_episodes",
    "days_since_episode",
    "episodes_365",
    "days_lost_365",
    "last_muscle",
]
# a league is scored if the history-only model, trained on 2022-23, ranks its 2023-24 rows this well
SCORE_MIN_AUC = 0.55
SCORE_MIN_POSITIVES = 50


def other_leagues() -> list[str]:
    return [lg for lg in leagues() if lg != PL and league_config(lg)["provider_ids"].get("transfermarkt")]


def episodes(df: pd.DataFrame) -> pd.DataFrame:
    """Missed fixtures (player_id, date, reason) -> injury episodes: a new one when the gap to the previous
    missed fixture exceeds 10 days."""
    df = df.sort_values(["player_id", "date"]).copy()
    gap = df.groupby("player_id").date.diff().dt.days
    df["episode"] = (gap.isna() | (gap > 10)).cumsum()
    ep = (
        df.groupby("episode")
        .agg(
            player_id=("player_id", "first"),
            date=("date", "min"),
            end=("date", "max"),
            reason=("reason", "first"),
        )
        .reset_index(drop=True)
    )
    ep["muscle"] = ep.reason.fillna("").str.lower().str.contains("|".join(MUSCLE)).astype(float)
    ep["days_out"] = (ep.end - ep.date).dt.days + 7  # last missed fixture + about a week
    return ep


def _injury_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df.type == "Missing Fixture"]
    return df[~df.reason.fillna("").str.lower().str.contains("|".join(NOT_INJURY))]


def injury_episodes(league: str = PL) -> pd.DataFrame:
    """Episodes for one league's panel. The Premier League keys players by Reep id (its FPL panel) and uses its own
    lists; other leagues key by Transfermarkt id and take every league's lists, so a spell out at a previous
    club in another league counts too."""
    if league == PL:
        files, key = [injury_file(PL, s) for s in API_SEASONS], "reep_id"
    else:
        files = [injury_file(lg, s) for lg in [PL, *other_leagues()] for s in API_SEASONS]
        key = "tm_player_id"
    frames = [pd.read_parquet(p) for p in files if p.is_file()]
    if not frames:  # the history job has not fetched the lists yet
        return pd.DataFrame(columns=["player_id", "date", "end", "reason", "muscle", "days_out"])
    df = _injury_rows(pd.concat(frames, ignore_index=True))
    df = df[df.columns.intersection(["reep_id", "tm_player_id", "date", "reason"])].dropna(subset=[key])
    df = df.assign(player_id=df[key].astype(str), date=pd.to_datetime(df.date))
    return episodes(df.drop_duplicates(["player_id", "date"]))


def _load(rows: pd.DataFrame) -> pd.DataFrame:
    """Recent-load features on (player_id, date, season, minutes) rows."""
    rows["date"] = pd.to_datetime(rows.date)
    rows = rows.sort_values(["player_id", "date"]).reset_index(drop=True)
    g = rows.groupby("player_id")
    rows["min_last3"] = g.minutes.transform(lambda s: s.rolling(3, min_periods=1).sum())
    rows["min_28d"] = _time_window_sum(rows, "minutes", 28)
    rows["matches_14d"] = _time_window_sum(rows.assign(one=1), "one", 14)
    rows["season_week"] = (rows.date - rows.groupby("season").date.transform("min")).dt.days // 7
    return rows


def panel(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    rows = con.execute(
        """SELECT s.player_id, CAST(m.kickoff_utc AS DATE) AS date, m.season, s.minutes
           FROM player_match_stats s JOIN matches m USING (match_id)
           WHERE s.source = 'fpl_history' AND s.minutes > 0 AND m.season IN ('2022-23', '2023-24', '2024-25')"""
    ).df()
    return _load(rows)


def panel_tm(comp: str) -> pd.DataFrame:
    """League matches played (transfermarkt-datasets appearances, keyed by Transfermarkt id)."""
    apps = pd.read_parquet(
        TM_DIR / "appearances.parquet", columns=["player_id", "date", "competition_id", "minutes_played"]
    )
    apps["date"] = pd.to_datetime(apps.date)
    apps = apps[
        (apps.competition_id == comp)
        & (apps.minutes_played > 0)
        & (apps.date >= "2022-07-01")
        & (apps.date < "2025-07-01")
    ]
    year = np.where(apps.date.dt.month >= 7, apps.date.dt.year, apps.date.dt.year - 1)
    rows = pd.DataFrame(
        {
            "player_id": apps.player_id.astype(str).to_numpy(),
            "date": apps.date.to_numpy(),
            "season": [f"{y}-{(y + 1) % 100:02d}" for y in year],
            "minutes": apps.minutes_played.to_numpy(),
        }
    )
    return _load(rows)


def _time_window_sum(rows: pd.DataFrame, col: str, days: int) -> np.ndarray:
    out = np.zeros(len(rows))
    for _, idx in rows.groupby("player_id").indices.items():
        d = rows.date.to_numpy()[idx]
        v = np.cumsum(np.concatenate([[0], rows[col].to_numpy()[idx]]))
        lo = np.searchsorted(d, d - np.timedelta64(days, "D"), side="right")
        out[idx] = v[np.arange(1, len(idx) + 1)] - v[lo]
    return out


def _positions(df: pd.DataFrame) -> pd.DataFrame:
    df["age"] = (df.date - pd.to_datetime(df.date_of_birth)).dt.days / 365.25
    for k, v in {
        "is_gk": "Goalkeeper",
        "is_def": "Defender",
        "is_mid": "Midfield",
        "is_fwd": "Attack",
    }.items():
        df[k] = (df.position == v).astype(float)
    return df


def _tm_players() -> pd.DataFrame:
    tm = pd.read_parquet(TM_DIR / "players.parquet", columns=["player_id", "date_of_birth", "position"])
    tm["player_id"] = tm.player_id.astype(str)
    return tm


def attach_player_facts(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> pd.DataFrame:
    """Birth date and position from transfermarkt-datasets via the Reep crosswalk."""
    tm = _tm_players()
    if not attach_catalogue(con):
        raise RuntimeError("Reep catalogue needed to join transfermarkt facts")
    bridge = con.execute("""SELECT reep_id, external_id AS tm_id FROM reep.bridges
                            WHERE provider='transfermarkt' AND namespace='spieler'""").df()
    facts = bridge.merge(tm, left_on="tm_id", right_on="player_id").drop(columns=["player_id"])
    df = df.merge(facts.drop_duplicates("reep_id"), left_on="player_id", right_on="reep_id", how="left")
    return _positions(df)


def attach_tm_facts(df: pd.DataFrame) -> pd.DataFrame:
    """Birth date and position for rows keyed by Transfermarkt id."""
    return _positions(df.merge(_tm_players(), on="player_id", how="left"))


def history_features(p: pd.DataFrame, ep: pd.DataFrame, label: bool = True) -> pd.DataFrame:
    """Injury-record features at each row's date (episodes started on or before it), and the label: a new
    episode starts within HORIZON_DAYS after it."""
    by_player = {k: v for k, v in ep.groupby("player_id")}
    lab = np.zeros(len(p), dtype=bool)
    prev = np.zeros(len(p))
    since = np.full(len(p), 999.0)
    eps_365, lost_365, last_muscle = np.zeros(len(p)), np.zeros(len(p)), np.zeros(len(p))
    for i, (pid, d) in enumerate(zip(p.player_id, p.date.to_numpy(), strict=True)):
        e = by_player.get(pid)
        if e is None:
            continue
        starts = e.date.to_numpy()
        nxt = np.searchsorted(starts, d, side="right")
        recent = (starts <= d) & (starts > d - np.timedelta64(365, "D"))
        eps_365[i], lost_365[i] = recent.sum(), e.days_out.to_numpy()[recent].sum()
        if nxt:
            last_muscle[i] = e.muscle.to_numpy()[nxt - 1]
            since[i] = (d - starts[nxt - 1]) / np.timedelta64(1, "D")
        lab[i] = nxt < len(starts) and (starts[nxt] - d) <= np.timedelta64(HORIZON_DAYS, "D")
        prev[i] = nxt  # episodes that started on or before this row
    p = p.assign(prev_episodes=prev, days_since_episode=np.minimum(since, 999))
    p = p.assign(episodes_365=eps_365, days_lost_365=lost_365, last_muscle=last_muscle)
    return p.assign(label=lab) if label else p


def build(con: duckdb.DuckDBPyConnection, league: str = PL) -> pd.DataFrame:
    p = panel(con) if league == PL else panel_tm(league_config(league)["provider_ids"]["transfermarkt"])
    p = history_features(p, injury_episodes(league))
    p["min_7d"] = _time_window_sum(p, "minutes", 7)
    out = attach_player_facts(con, p) if league == PL else attach_tm_facts(p)
    out = out.dropna(subset=["age"])
    out["age2"] = (out.age - 27) ** 2
    out["league"] = league
    return out


def _logit():
    return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))


def _league_cols(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """League indicators (reporting rates differ by league: calibration only, rankings within a league are
    unchanged)."""
    return df.assign(**{f"lg_{lg}": (df.league == lg).astype(float) for lg in names})


def _scores(y: pd.Series, p: np.ndarray, base: bool = False) -> dict:
    top = p >= np.quantile(p, 0.9)
    return {
        "auc": 0.5 if base else float(roc_auc_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "top_decile_lift": 1.0 if base else float(y[top].mean() / y.mean()),
    }


def history_model(frames: pd.DataFrame, names: list[str]):
    """The history-only logistic pooled over leagues (with league indicators); returns (model, columns)."""
    cols = HISTORY_FEATURES + [f"lg_{lg}" for lg in names]
    df = _league_cols(frames, names)
    return _logit().fit(df[cols], df.label), cols


def league_backtests(frames: dict[str, pd.DataFrame]) -> dict:
    """Per league: its own logistic (all features), the same pooled over leagues, the history-only pooled model
    the site uses outside the Premier League, and the base rate; train 2022-24, test 2024-25. `scored` is decided
    on validation (train 2022-23, validate 2023-24), not on the test."""
    names = list(frames)
    allf = _league_cols(pd.concat(frames.values(), ignore_index=True), names)
    lg_cols = [f"lg_{lg}" for lg in names]
    train_all = allf[allf.season != TEST_SEASON]
    pooled = _logit().fit(train_all[FEATURES + lg_cols], train_all.label)
    hist, hist_cols = history_model(train_all, names)
    val_fit, _ = history_model(allf[allf.season == SEASONS[0]], names)
    out = {}
    for lg, df in frames.items():
        df = _league_cols(df, names)
        train, test = df[df.season != TEST_SEASON], df[df.season == TEST_SEASON]
        val = df[df.season == SEASONS[1]]
        if test.label.sum() == 0 or train.label.sum() == 0:
            out[lg] = {"episodes_train": int(train.label.sum()), "scored": False}
            continue
        own = _logit().fit(train[FEATURES], train.label)
        val_auc = (
            float(roc_auc_score(val.label, val_fit.predict_proba(val[hist_cols])[:, 1]))
            if val.label.nunique() == 2
            else 0.5
        )
        out[lg] = {
            "train_rows": len(train),
            "test_rows": len(test),
            "positives_train": int(train.label.sum()),
            "positives_test": int(test.label.sum()),
            "positive_rate_test": float(test.label.mean()),
            "results": {
                "logistic": _scores(test.label, own.predict_proba(test[FEATURES])[:, 1]),
                "logistic_pooled": _scores(test.label, pooled.predict_proba(test[FEATURES + lg_cols])[:, 1]),
                "history_pooled": _scores(test.label, hist.predict_proba(test[hist_cols])[:, 1]),
                "base_rate": _scores(test.label, np.full(len(test), train.label.mean()), base=True),
            },
            "validation_auc_history": val_auc,
            "positives_validation": int(val.label.sum()),
            "scored": bool(lg == PL or (val_auc >= SCORE_MIN_AUC and val.label.sum() >= SCORE_MIN_POSITIVES)),
        }
    return out


def backtest(
    con: duckdb.DuckDBPyConnection, out_dir: Path | None = None, league_list: list[str] | None = None
) -> dict:
    frames = {lg: build(con, lg) for lg in league_list or [PL, *other_leagues()]}
    df = frames[PL]
    train, test = df[df.season != TEST_SEASON], df[df.season == TEST_SEASON]
    base = np.full(len(test), train.label.mean())
    logit = _logit().fit(train[FEATURES], train.label)
    gbm_params = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=100, verbose=-1)
    gbm = lgb.LGBMClassifier(**gbm_params).fit(train[FEATURES], train.label)
    # isotonic calibration fitted out-of-fold, one fold per training season
    folds = [
        (np.where(train.season != s)[0], np.where(train.season == s)[0])
        for s in sorted(train.season.unique())
    ]
    calibrated = CalibratedClassifierCV(lgb.LGBMClassifier(**gbm_params), method="isotonic", cv=folds)
    calibrated.fit(train[FEATURES], train.label)
    res = {
        "logistic": _scores(test.label, logit.predict_proba(test[FEATURES])[:, 1]),
        "gradient_boosting": _scores(test.label, gbm.predict_proba(test[FEATURES])[:, 1]),
        "gradient_boosting_calibrated": _scores(test.label, calibrated.predict_proba(test[FEATURES])[:, 1]),
        "base_rate": _scores(test.label, base, base=True),
    }
    coefs = dict(zip(FEATURES, logit[-1].coef_[0].round(3).tolist(), strict=True))
    per_league = league_backtests(frames)
    names = {lg: league_config(lg)["name"] for lg in frames}
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "horizon_days": HORIZON_DAYS,
        "train_rows": len(train),
        "test_rows": len(test),
        "episodes": len(injury_episodes(PL)),
        "positive_rate_test": float(test.label.mean()),
        "results": res,
        "logistic_coefficients": coefs,
        "leagues": {lg: {"name": names[lg], **r} for lg, r in per_league.items()},
        "scored_leagues": [names[lg] for lg, r in per_league.items() if r["scored"]],
        "unscored_leagues": [names[lg] for lg, r in per_league.items() if not r["scored"]],
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "injury.json").write_text(json.dumps(report, indent=2))
        (out_dir / "injury.md").write_text(report_md(report), encoding="utf-8")
    return report


def report_md(report: dict) -> str:
    res, coefs = report["results"], report["logistic_coefficients"]
    lines = [
        "# Injury risk backtest",
        "",
        f"Generated {report['generated_at']}. Label: a new injury absence starts "
        f"within {HORIZON_DAYS} days of a match played. Train 2022-23 + 2023-24, test 2024-25.",
        "",
        "## Premier League",
        "",
        f"Injury episodes: {report['episodes']}. Test rows: {report['test_rows']} "
        f"(positive rate {report['positive_rate_test']:.2%}).",
        "",
        "| Model | AUC | Brier | Top-decile lift |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {k} | {v['auc']:.3f} | {v['brier']:.5f} | {v['top_decile_lift']:.2f}x |" for k, v in res.items()
    ]
    lines += [
        "",
        "Logistic coefficients (standardised features): " + ", ".join(f"{k} {v}" for k, v in coefs.items()),
        "",
        "## Every league",
        "",
        "Same label and split, per league. At-risk rows outside the Premier League are league matches played in "
        "transfermarkt-datasets appearances. *own*: logistic on the league's rows, all features. *pooled*: the same "
        "trained on all six leagues (league indicators). *history*: pooled, without recent minutes (age, position, "
        "injury record): what the site can score today outside the Premier League, where no current minutes source "
        "exists. *val AUC*: history model trained on 2022-23, ranked on 2023-24; a league is scored when it is at "
        f"least {SCORE_MIN_AUC} with {SCORE_MIN_POSITIVES}+ new absences (decided before the test).",
        "",
        "| League | Test rows | Positive rate | own AUC | own lift | pooled AUC | pooled lift | history AUC "
        "| history lift | Brier history / base | val AUC | Scored |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["leagues"].values():
        if "results" not in r:
            lines.append(f"| {r['name']} | | | | | | | | | | | no (no data) |")
            continue
        x = r["results"]
        lines.append(
            f"| {r['name']} | {r['test_rows']} | {r['positive_rate_test']:.2%} "
            f"| {x['logistic']['auc']:.3f} | {x['logistic']['top_decile_lift']:.2f}x "
            f"| {x['logistic_pooled']['auc']:.3f} | {x['logistic_pooled']['top_decile_lift']:.2f}x "
            f"| {x['history_pooled']['auc']:.3f} | {x['history_pooled']['top_decile_lift']:.2f}x "
            f"| {x['history_pooled']['brier']:.5f} / {x['base_rate']['brier']:.5f} "
            f"| {r['validation_auc_history']:.3f} | {'yes' if r['scored'] else 'no'} |"
        )
    lines += [
        "",
        "Live tiers: Premier League from the own model with FPL minutes (percentile among training rows); other "
        "scored leagues from the history model trained on all seasons, as a percentile among the league's current "
        "squad players (low below the median, moderate to the 80th, elevated to the 95th, high above). The free "
        "plan's injury lists stop with 2024-25, so outside the absences API-Football lists each night the record "
        "behind a tier is at least a season old: it says who has been injury-prone, not who is hurt now.",
        "",
        "Data: API-Football free plan injury lists (2022–2024 seasons only, one call per league-season); minutes from "
        "FPL (Premier League) and transfermarkt-datasets appearances (other leagues); age/position from "
        "transfermarkt-datasets (CC0). Players matched to Transfermarkt by Reep, else by name within the club's "
        "squad that season (the lists give no date of birth).",
    ]
    return "\n".join(lines) + "\n"
