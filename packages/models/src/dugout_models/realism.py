"""Transfer realism (0-100) for a (player, buying club) pair, shown with every factor.

Fitted on historical moves (transfermarkt-datasets, CC0):
  mobility     P(player completes a permanent move in a summer window)   logistic regression
  destination  P(the move goes to this club | he moves)                  pairwise logistic: real buyer vs sampled
               clubs that bought someone that window
Not fittable historically, so prior weights (documented, editable in PRIORS):
  contract     months remaining (no historical contract data)
  news         tier-weighted mentions linking player and club in the last 30 days (no historical news archive)

realism = 100 * sigmoid( logit(mobility) + logit(destination) + w_contract * c + w_news * n ), centred so an
average plausible move scores ~50.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from dugout_models.valuation import TM_DIR, load

MOBILITY = ["age", "log_mv", "mv_change", "minutes_share", "rel_value", "log_league"]
DESTINATION = ["capacity_ratio", "league_gap", "club_value_gap", "same_league", "same_country"]
PRIORS = {
    "contract": {"<=12 months": 0.8, "13-24 months": 0.3, ">24 months": -0.4},
    "news_weight_per_point": 0.35,
    "news_cap": 4.0,
}


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def snapshots(t: dict[str, pd.DataFrame], years: range) -> pd.DataFrame:
    """Player state on 1 June of each year, and whether he made a permanent move by 1 September."""
    vals = t["player_valuations"].copy()
    vals["date"] = pd.to_datetime(vals.date)
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr.transfer_date)
    fee = pd.to_numeric(tr.transfer_fee, errors="coerce")
    permanent = tr[(fee > 0) | ((fee == 0) & tr.from_club_id.ne(tr.to_club_id))]
    ap = t["appearances"][["player_id", "date", "minutes_played", "player_club_id", "competition_id"]].copy()
    ap["date"] = pd.to_datetime(ap.date)
    clubs = t["clubs"][["club_id", "domestic_competition_id"]]
    dob = t["players"].set_index("player_id").date_of_birth
    out = []
    for y in years:
        d0, d1 = pd.Timestamp(f"{y}-06-01"), pd.Timestamp(f"{y}-09-01")
        v = vals[vals.date < d0].sort_values("date").groupby("player_id").tail(1)
        v = v[v.date > d0 - pd.Timedelta(days=200)]  # still an active, valued player
        prev = vals[vals.date < d0 - pd.Timedelta(days=365)].sort_values("date").groupby("player_id").tail(1)
        v = v.merge(
            prev[["player_id", "market_value_in_eur"]], on="player_id", how="left", suffixes=("", "_prev")
        )
        season = ap[(ap.date >= d0 - pd.Timedelta(days=365)) & (ap.date < d0)]
        mins = season.groupby("player_id").minutes_played.sum()
        club_games = season.groupby("player_club_id").date.nunique()
        v["club_id"] = v.current_club_id
        v = v.merge(clubs, on="club_id", how="left")
        v["minutes_share"] = v.player_id.map(mins).fillna(0) / (
            90 * v.club_id.map(club_games).fillna(38).clip(lower=10)
        )
        league_val = v.groupby("domestic_competition_id").market_value_in_eur.transform("median")
        club_val = v.groupby("club_id").market_value_in_eur.transform("median")
        v["rel_value"] = np.log1p(v.market_value_in_eur) - np.log1p(club_val)
        v["log_league"] = np.log1p(league_val)
        v["log_mv"] = np.log1p(v.market_value_in_eur)
        v["mv_change"] = np.log1p(v.market_value_in_eur) - np.log1p(
            v.market_value_in_eur_prev.fillna(v.market_value_in_eur)
        )
        v["age"] = (d0 - pd.to_datetime(v.player_id.map(dob))).dt.days / 365.25
        moved = set(permanent[(permanent.date >= d0) & (permanent.date < d1)].player_id)
        v["moved"] = v.player_id.isin(moved)
        v["year"] = y
        out.append(v)
    return pd.concat(out).dropna(subset=["age"]).reset_index(drop=True)


def destination_pairs(
    t: dict[str, pd.DataFrame], years: range, negatives: int = 5, seed: int = 7
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr.transfer_date)
    tr["fee"] = pd.to_numeric(tr.transfer_fee, errors="coerce")
    clubs = t["clubs"].set_index("club_id")
    comps = pd.read_parquet(TM_DIR / "competitions.parquet").set_index("competition_id")
    vals = t["player_valuations"].copy()
    vals["date"] = pd.to_datetime(vals.date)
    rows = []
    for y in years:
        # club strength = sum of its players' latest valuations before the window (TM club totals are empty)
        latest = vals[(vals.date < f"{y}-06-01") & (vals.date >= f"{y - 1}-06-01")].sort_values("date")
        latest = latest.groupby("player_id").tail(1)
        club_value = latest.groupby("current_club_id").market_value_in_eur.sum()
        w = tr[(tr.date >= f"{y}-06-01") & (tr.date < f"{y}-09-01") & (tr.fee > 0)]
        hist = tr[(tr.date < f"{y}-06-01") & (tr.date >= f"{y - 3}-06-01")]
        capacity = hist.groupby("to_club_id").fee.max()
        buyers = w.to_club_id.unique()
        buyers = buyers[np.isin(buyers, clubs.index)]
        for r in w.itertuples():
            if r.to_club_id not in clubs.index or r.from_club_id not in clubs.index:
                continue
            cands = [
                r.to_club_id,
                *rng.choice(
                    buyers[buyers != r.to_club_id], size=min(negatives, len(buyers) - 1), replace=False
                ),
            ]
            for c in cands:
                rows.append(
                    {
                        "year": y,
                        "player_id": r.player_id,
                        "club": c,
                        "label": c == r.to_club_id,
                        **_pair_features(r.fee, r.from_club_id, c, capacity, clubs, comps, club_value),
                    }
                )
    return pd.DataFrame(rows)


def _pair_features(fee, seller, buyer, capacity, clubs, comps, club_value: pd.Series) -> dict:
    s, b = clubs.loc[seller], clubs.loc[buyer]
    s_comp, b_comp = s.domestic_competition_id, b.domestic_competition_id
    s_country = comps.country_name.get(s_comp) if s_comp in comps.index else None
    b_country = comps.country_name.get(b_comp) if b_comp in comps.index else None
    league_of = clubs.domestic_competition_id
    sv = club_value[club_value.index.isin(league_of[league_of == s_comp].index)].median()
    bv = club_value[club_value.index.isin(league_of[league_of == b_comp].index)].median()
    return {
        "capacity_ratio": float(np.log1p(capacity.get(buyer, 0)) - np.log1p(fee)),
        "league_gap": float(np.log1p(bv or 0) - np.log1p(sv or 0)),
        "club_value_gap": float(np.log1p(club_value.get(buyer, 0)) - np.log1p(club_value.get(seller, 0))),
        "same_league": float(s_comp == b_comp),
        "same_country": float(s_country == b_country),
    }


def contract_points(months_left: float | None) -> float:
    if months_left is None or np.isnan(months_left):
        return 0.0
    c = PRIORS["contract"]
    return (
        c["<=12 months"] if months_left <= 12 else c["13-24 months"] if months_left <= 24 else c[">24 months"]
    )


def backtest(out_dir: Path | None = None) -> dict:
    t = load()
    snap = snapshots(t, range(2015, 2026)).dropna(subset=MOBILITY)
    train, test = snap[snap.year <= 2023], snap[snap.year >= 2024]
    mob = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(train[MOBILITY], train.moved)
    p_mob = mob.predict_proba(test[MOBILITY])[:, 1]
    pairs = destination_pairs(t, range(2015, 2026)).dropna(subset=DESTINATION)
    ptr, pte = pairs[pairs.year <= 2023], pairs[pairs.year >= 2024]
    dest = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(ptr[DESTINATION], ptr.label)
    p_dest = dest.predict_proba(pte[DESTINATION])[:, 1]
    # top-1 accuracy: is the real buyer ranked first among its candidates?
    pte = pte.assign(p=p_dest)
    top1 = pte.loc[pte.groupby(["year", "player_id"]).p.idxmax()].label.mean()
    n_cands = pte.groupby(["year", "player_id"]).size().mean()
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mobility": {
            "train": len(train),
            "test": len(test),
            "auc": float(roc_auc_score(test.moved, p_mob)),
            "base_rate": float(test.moved.mean()),
            "coefficients": dict(zip(MOBILITY, mob[-1].coef_[0].round(3).tolist(), strict=True)),
        },
        "destination": {
            "test_moves": int(pte.groupby(["year", "player_id"]).ngroups),
            "auc": float(roc_auc_score(pte.label, p_dest)),
            "top1": float(top1),
            "random_top1": float(1 / n_cands),
            "coefficients": dict(zip(DESTINATION, dest[-1].coef_[0].round(3).tolist(), strict=True)),
        },
        "priors": PRIORS,
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "realism.json").write_text(json.dumps(report, indent=2))
        m, d = report["mobility"], report["destination"]
        lines = [
            "# Transfer realism backtest",
            "",
            f"Generated {report['generated_at']}. transfermarkt-datasets (CC0); "
            "train summer windows 2015-2023, test 2024-2025.",
            "",
            "| Factor | Model | Test AUC | Notes |",
            "|---|---|---|---|",
            f"| Mobility (moves this summer?) | logistic | {m['auc']:.3f} | base rate {m['base_rate']:.1%}, "
            f"{m['test']} player-summers |",
            f"| Destination (this club, given a move) | pairwise logistic | {d['auc']:.3f} | real buyer ranked first "
            f"{d['top1']:.1%} vs random {d['random_top1']:.1%}, {d['test_moves']} moves |",
            "| Contract | prior weights | — | no historical contract data |",
            "| News signal | prior weights | — | no historical news archive |",
            "",
            "Mobility coefficients: " + ", ".join(f"{k} {v}" for k, v in m["coefficients"].items()),
            "",
            "Destination coefficients: " + ", ".join(f"{k} {v}" for k, v in d["coefficients"].items()),
            "",
            "Wages are not modelled: no free, licensable wage data exists (Capology is not open).",
        ]
        (out_dir / "realism.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
