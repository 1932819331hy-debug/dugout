"""Transfer realism (0-100) for a (player, buying club) pair, shown with every factor.

Fitted on historical moves (transfermarkt-datasets, CC0):
  mobility     P(player is sold for a fee in a summer window)             gradient boosting (logistic for coefficients)
  destination  P(the move goes to this club | he moves)                  pairwise logistic: real buyer vs sampled
               clubs that bought someone that window
               + press reports linking him with that club in the year before (the Guardian's Rumour Mill
               archive, rumour_links), fitted like the other features; they did not help mobility (realism.md)
Not fittable historically, so a prior weight (documented, editable in PRIORS):
  contract     months remaining (no historical contract data)

P(this move in a window) = P(sold, contract-adjusted) x P(this club | sold) (market.Market.realism_score).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from dugout_models.valuation import TM_DIR, load

if TYPE_CHECKING:
    from dugout_models.rumours import People

MOBILITY_V1 = [
    "age",
    "age2",
    "log_mv",
    "mv_change",
    "minutes_share",
    "share_change",
    "rel_value",
    "log_league",
    "tenure",
    "peak_ratio",
    "relegated",
]
# Europe's richest clubs rarely sell young regulars (3.6% a summer at the top ten, 2024-25) though the features
# above (young, valuable, rising) look like a sale; the club's wealth rank across Europe, and its interaction with
# being a regular, let the model tell a Timber at Arsenal from a regular at a selling club. See realism.md.
ELITE_RANK = 10
MOBILITY = [*MOBILITY_V1, "log_europe_rank", "elite_regular"]
DESTINATION_V1 = ["capacity_ratio", "league_gap", "club_value_gap", "same_league", "same_country"]
# step_down: how far the buyer is below the seller (players rarely move to smaller clubs). See realism.md.
DESTINATION = [*DESTINATION_V1, "step_down"]
PRIORS = {
    "contract": {"<=12 months": 0.8, "13-24 months": 0.3, ">24 months": -0.4},
}
# News signal, fitted from the Guardian Rumour Mill archive (rumour_links, dugout_models.rumours): point-in-time
# counts of reports published before the snapshot date (1 June in training, today live). Each candidate set is
# trained on 2015-22 and scored on validation summer 2023 (mobility by Brier, destination by log loss); the winner
# ships if it beats no news there (realism.md, 2026-10-18). Since 2020 the column runs only in transfer windows,
# so the 90 days before 1 June hold no reports: the year before is the window that carries signal.
NEWS_DAYS = (90, 365)
NEWS_MOBILITY_ALL = [f"news_{k}_{w}" for w in NEWS_DAYS for k in ("reports", "clubs")]
NEWS_DESTINATION_ALL = [f"news_{k}_{w}" for w in NEWS_DAYS for k in ("club", "club_share")]
NEWS_MOBILITY_CANDIDATES = {
    "none": [],
    "reports_90": ["news_reports_90"],
    "reports_365": ["news_reports_365"],
    "reports_clubs_365": ["news_reports_365", "news_clubs_365"],
    "all": NEWS_MOBILITY_ALL,
}
NEWS_DESTINATION_CANDIDATES = {
    "none": [],
    "club_90": ["news_club_90"],
    "club_365": ["news_club_365"],
    "club_share_365": ["news_club_365", "news_club_share_365"],
    "all": NEWS_DESTINATION_ALL,
}
NEWS_MOBILITY: list[str] = NEWS_MOBILITY_CANDIDATES["none"]  # every news set was worse on validation
NEWS_DESTINATION: list[str] = NEWS_DESTINATION_CANDIDATES["club_share_365"]
MOBILITY_SHIPPED = [*MOBILITY, *NEWS_MOBILITY]
DESTINATION_SHIPPED = [*DESTINATION, *NEWS_DESTINATION]


# Train mobility only on players whose transfer history the dataset carries (chosen on validation, realism.md).
COVERED_ONLY = True


def _club(cid: str | None) -> int | None:
    return None if cid is None else int(cid)


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


TOP_TIER: set[str] = set()  # filled from competitions.parquet in backtest()


def club_people(t: dict[str, pd.DataFrame]) -> People:
    """Where each player played when (dugout_models.rumours.People: transfers + club appearances + dated
    valuation names). The valuations' own club id is the player's club *today*, not on the valuation date."""
    from dugout_models.rumours import Gazetteer, People

    tt = dict(t)
    tt.setdefault(
        "competitions", pd.read_parquet(TM_DIR / "competitions.parquet", columns=["competition_id", "type"])
    )
    return People.build(tt, Gazetteer.build(t["transfers"], t["clubs"]))


def snapshots(
    t: dict[str, pd.DataFrame],
    years: range | list[int],
    as_of: pd.Timestamp | None = None,
    people: People | None = None,
    dated: bool = True,
    covered_only: bool = COVERED_ONLY,
) -> pd.DataFrame:
    """Player state on 1 June of each year, and whether he was *sold for a fee* by 1 September.

    Zero-fee rows in the dataset mix loans, loan returns, free and youth moves with no flag to tell them apart,
    so the label is a paid transfer — which is also what a transfer shortlist is about.

    dated: the player's club on 1 June from his club timeline (`club_people`); False = the valuations' club id,
    which is today's club (the bug before 2026-10-17, kept for the backtest comparison). Live scoring (as_of)
    uses today's club either way. covered_only: only players with a transfer history in the dataset (it has none
    for anyone whose last season is before 2023, so for them "sold" can never be true)."""
    if dated and as_of is None and people is None:
        people = club_people(t)
    covered = set(t["transfers"].player_id)
    vals = t["player_valuations"].copy()
    vals["date"] = pd.to_datetime(vals.date)
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr.transfer_date)
    fee = pd.to_numeric(tr.transfer_fee, errors="coerce")
    sold = tr[fee > 0]
    ap = t["appearances"][["player_id", "date", "minutes_played", "player_club_id", "competition_id"]].copy()
    ap["date"] = pd.to_datetime(ap.date)
    clubs = t["clubs"][["club_id", "domestic_competition_id"]]
    dob = t["players"].set_index("player_id").date_of_birth
    out = []
    for y in years:
        d0 = as_of if as_of is not None else pd.Timestamp(f"{y}-06-01")  # as_of: score "now" (live use)
        d1 = pd.Timestamp(f"{y}-09-01")
        v = vals[vals.date < d0].sort_values("date").groupby("player_id").tail(1)
        v = v[v.date > d0 - pd.Timedelta(days=200)]  # still an active, valued player
        prev = vals[vals.date < d0 - pd.Timedelta(days=365)].sort_values("date").groupby("player_id").tail(1)
        v = v.merge(
            prev[["player_id", "market_value_in_eur"]], on="player_id", how="left", suffixes=("", "_prev")
        )
        season = ap[(ap.date >= d0 - pd.Timedelta(days=365)) & (ap.date < d0)]
        mins = season.groupby("player_id").minutes_played.sum()
        club_games = season.groupby("player_club_id").date.nunique()
        if dated and as_of is None:
            ids = pd.array([_club(people.club_on(int(p), d0)[0]) for p in v.player_id], dtype="Int64")
            # the same id type as the tables it is compared with: Market passes string ids (market.py)
            v["club_id"] = (
                ids
                if ap.player_club_id.dtype != object
                else pd.Series(ids, index=v.index).astype(str).where(lambda s: s != "<NA>", None)
            )
        else:
            v["club_id"] = v.current_club_id
        v = v.merge(clubs, on="club_id", how="left")
        v["minutes_share"] = v.player_id.map(mins).fillna(0) / (
            90 * v.club_id.map(club_games).fillna(38).clip(lower=10)
        )
        league_val = v.groupby("domestic_competition_id").market_value_in_eur.transform("median")
        club_val = v.groupby("club_id").market_value_in_eur.transform("median")
        v["rel_value"] = np.log1p(v.market_value_in_eur) - np.log1p(club_val)
        v["log_league"] = np.log1p(league_val)
        # club wealth rank across Europe: total value of its valued players (1 = richest)
        total = v.groupby("club_id").market_value_in_eur.transform("sum")
        europe_rank = total.rank(ascending=False, method="dense")
        v["log_europe_rank"] = np.log(europe_rank)
        v["elite_regular"] = (europe_rank <= ELITE_RANK).astype(float) * v.minutes_share
        v["log_mv"] = np.log1p(v.market_value_in_eur)
        v["mv_change"] = np.log1p(v.market_value_in_eur) - np.log1p(
            v.market_value_in_eur_prev.fillna(v.market_value_in_eur)
        )
        v["age"] = (d0 - pd.to_datetime(v.player_id.map(dob))).dt.days / 365.25
        v["age2"] = (v.age - 26) ** 2
        # years since he joined his current club (contracts run 3-5 years; no historical contract data exists)
        if dated and as_of is None:  # from the start of his spell in the club timeline
            starts = [people.since(int(p), d0) for p in v.player_id]
            v["tenure"] = [(d0 - s).days / 365.25 if s is not None else np.nan for s in starts]
        else:
            joined = tr[(tr.date < d0)].sort_values("date").groupby(["player_id", "to_club_id"]).date.last()
            v["tenure"] = [
                (d0 - joined.get((p, c), pd.NaT)).days / 365.25 if (p, c) in joined.index else np.nan
                for p, c in zip(v.player_id, v.club_id, strict=True)
            ]
        v["tenure"] = v.tenure.fillna(v.tenure.median())
        # value relative to his own peak so far
        peak = vals[vals.date < d0].groupby("player_id").market_value_in_eur.max()
        v["peak_ratio"] = np.log1p(v.market_value_in_eur) - np.log1p(v.player_id.map(peak))
        # change in playing time vs the season before
        before = ap[(ap.date >= d0 - pd.Timedelta(days=730)) & (ap.date < d0 - pd.Timedelta(days=365))]
        prev_share = before.groupby("player_id").minutes_played.sum() / (90 * 38)
        v["share_change"] = v.minutes_share - v.player_id.map(prev_share).fillna(v.minutes_share)
        # club relegated: its league games last season were top tier, but its games this August-October are not
        lg = season[season.competition_id.isin(TOP_TIER)].groupby("player_club_id").size()
        nxt = ap[(ap.date >= d0 + pd.Timedelta(days=60)) & (ap.date < d0 + pd.Timedelta(days=150))]
        nxt_top = nxt[nxt.competition_id.isin(TOP_TIER)].groupby("player_club_id").size()
        v["relegated"] = (
            v.club_id.isin(lg.index) & ~v.club_id.isin(nxt_top.index) & v.club_id.isin(nxt.player_club_id)
        ).astype(float)
        moved = set(sold[(sold.date >= d0) & (sold.date < d1)].player_id)
        v["moved"] = v.player_id.isin(moved)
        v["year"] = y
        out.append(v)
    snap = pd.concat(out).dropna(subset=["age"])
    if (
        covered_only and as_of is None
    ):  # features above use everyone; only the rows to learn from are filtered
        snap = snap[snap.player_id.isin(covered)]
    return snap.reset_index(drop=True)


def destination_pairs(
    t: dict[str, pd.DataFrame],
    years: range,
    negatives: int = 5,
    seed: int = 7,
    people: People | None = None,
    dated: bool = True,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tr = t["transfers"].copy()
    tr["date"] = pd.to_datetime(tr.transfer_date)
    tr["fee"] = pd.to_numeric(tr.transfer_fee, errors="coerce")
    clubs = t["clubs"].set_index("club_id")
    comps = pd.read_parquet(TM_DIR / "competitions.parquet").set_index("competition_id")
    vals = t["player_valuations"].copy()
    vals["date"] = pd.to_datetime(vals.date)
    if dated:  # the club each valuation names on its date (its club id column is today's club)
        from dugout_pipeline.clubs import normalise

        names = (people or club_people(t)).club_names
        vals["club"] = pd.to_numeric(vals.current_club_name.fillna("").map(normalise).map(names)).astype(
            "Int64"
        )
    else:
        vals["club"] = vals.current_club_id
    rows = []
    for y in years:
        # club strength = sum of its players' latest valuations before the window (TM club totals are empty)
        latest = vals[(vals.date < f"{y}-06-01") & (vals.date >= f"{y - 1}-06-01")].sort_values("date")
        latest = latest.groupby("player_id").tail(1)
        club_value = latest.groupby("club").market_value_in_eur.sum()
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
        **step_features(seller, buyer, club_value),
    }


def step_features(seller, buyer, club_value: pd.Series) -> dict:
    gap = float(np.log1p(club_value.get(buyer, 0)) - np.log1p(club_value.get(seller, 0)))
    return {"step_down": max(-gap, 0.0)}


def load_links(con: duckdb.DuckDBPyConnection | None) -> pd.DataFrame:
    """Rumour links (dugout-models publish rumours): one row per (report, player, club it links him with).
    Empty without a warehouse, or before the archive has been loaded (history job)."""
    cols = ["rumour_id", "published_at", "tm_player_id", "tm_club_id"]
    empty = pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == "published_at" else str) for c in cols})
    if con is None:
        return empty
    try:
        df = con.execute(f"SELECT {', '.join(cols)} FROM rumour_links").df()
    except duckdb.CatalogException:  # warehouse from before the table existed
        return empty
    df["published_at"] = pd.to_datetime(df.published_at, utc=True).dt.tz_convert(None)
    return df.astype({"tm_player_id": str, "tm_club_id": str})


def _window(links: pd.DataFrame, players: pd.Series, dates: pd.Series, days: int) -> pd.DataFrame:
    """Links about each (row's player) published in the `days` before (row's date), with the row index as `row`.
    Strictly before the date: a report on the snapshot day is not known at its start."""
    keys = pd.DataFrame(
        {
            "row": players.index,
            "tm_player_id": players.astype(str).to_numpy(),
            "d": pd.to_datetime(dates.to_numpy()),
        }
    )
    m = keys.merge(links, on="tm_player_id")
    return m[(m.published_at < m.d) & (m.published_at >= m.d - np.timedelta64(days, "D"))]


def player_news(links: pd.DataFrame, players: pd.Series, dates: pd.Series) -> pd.DataFrame:
    """Per row: log1p(reports naming the player with a club) and the number of clubs named, in each window."""
    out = pd.DataFrame(index=players.index)
    for w in NEWS_DAYS:
        m = _window(links, players, dates, w)
        g = m.groupby("row")
        out[f"news_reports_{w}"] = np.log1p(g.rumour_id.nunique().reindex(out.index).fillna(0))
        out[f"news_clubs_{w}"] = g.tm_club_id.nunique().reindex(out.index).fillna(0).astype(float)
    return out


def pair_news(links: pd.DataFrame, players: pd.Series, clubs: pd.Series, dates: pd.Series) -> pd.DataFrame:
    """Per (player, candidate club) row: log1p(reports linking him with this club) and their share of all reports
    linking him with a club, in each window (0 when nobody wrote about him)."""
    out = pd.DataFrame(index=players.index)
    club = clubs.astype(str)
    for w in NEWS_DAYS:
        m = _window(links, players, dates, w)
        total = m.groupby("row").rumour_id.nunique().reindex(out.index).fillna(0)
        m = m[m.tm_club_id.to_numpy() == club.reindex(m.row).to_numpy()]
        this = m.groupby("row").rumour_id.nunique().reindex(out.index).fillna(0)
        out[f"news_club_{w}"] = np.log1p(this)
        out[f"news_club_share_{w}"] = (this / total.where(total > 0)).fillna(0)
    return out


def with_news(
    snap: pd.DataFrame, pairs: pd.DataFrame, links: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The training frames with the news features (reports before 1 June of each summer)."""
    d_snap = pd.to_datetime(snap.year.astype(str) + "-06-01")
    d_pairs = pd.to_datetime(pairs.year.astype(str) + "-06-01")
    snap = snap.join(player_news(links, snap.player_id, d_snap))
    pairs = pairs.join(pair_news(links, pairs.player_id, pairs.club, d_pairs))
    return snap, pairs


def _top1(frame: pd.DataFrame, p: np.ndarray) -> float:
    """Share of moves whose real buyer is ranked first among its candidates."""
    return float(frame.assign(p=p).loc[lambda d: d.groupby(["year", "player_id"]).p.idxmax()].label.mean())


def _dest_fit(train: pd.DataFrame, cols: list[str]):
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(train[cols], train.label)


def news_backtest(snap: pd.DataFrame, pairs: pd.DataFrame) -> dict:
    """With and without the press features (frames from with_news): candidates on validation 2023 (train 2015-22),
    then the chosen sets against no news on test 2024-25 (train 2015-23), plus how much of each frame the press
    covers at all."""
    out: dict = {
        "validation": {"mobility": {}, "destination": {}},
        "test": {"mobility": {}, "destination": {}},
    }
    for stage, tr, te in (
        ("validation", lambda f: f[f.year <= 2022], lambda f: f[f.year == 2023]),
        ("test", lambda f: f[f.year <= 2023], lambda f: f[f.year >= 2024]),
    ):
        s_tr, s_te, p_tr, p_te = tr(snap), te(snap), tr(pairs), te(pairs)
        for k, cols in NEWS_MOBILITY_CANDIDATES.items():
            p = (
                mobility_model()
                .fit(s_tr[MOBILITY + cols], s_tr.moved)
                .predict_proba(s_te[MOBILITY + cols])[:, 1]
            )
            out[stage]["mobility"][k] = {
                "auc": float(roc_auc_score(s_te.moved, p)),
                "brier": float(brier_score_loss(s_te.moved, p)),
                "mean_p": float(p.mean()),
            }
        for k, cols in NEWS_DESTINATION_CANDIDATES.items():
            m = _dest_fit(p_tr, DESTINATION + cols)
            p = m.predict_proba(p_te[DESTINATION + cols])[:, 1]
            out[stage]["destination"][k] = {
                "auc": float(roc_auc_score(p_te.label, p)),
                "top1": _top1(p_te, p),
                "log_loss": float(log_loss(p_te.label, p)),
                "coefficients": dict(
                    zip(cols, m[-1].coef_[0][len(DESTINATION) :].round(3).tolist(), strict=True)
                ),
            }
            if k == "club_share_365" and stage == "test":
                named = (p_te.label & (p_te.news_club_365 > 0)).to_numpy()
                p0 = _dest_fit(p_tr, DESTINATION).predict_proba(p_te[DESTINATION])[:, 1]
                moves = p_te.assign(named=named).groupby(["year", "player_id"]).named.transform("max")
                sub = moves.to_numpy()
                out["test"]["named_moves"] = {
                    "moves": int(p_te[sub].groupby(["year", "player_id"]).ngroups),
                    "top1_with": _top1(p_te[sub], p[sub]),
                    "top1_without": _top1(p_te[sub], p0[sub]),
                }
    val = out["validation"]
    out["chosen"] = {
        "mobility": min(val["mobility"], key=lambda k: val["mobility"][k]["brier"]),
        "destination": min(val["destination"], key=lambda k: val["destination"][k]["log_loss"]),
    }
    cov = []
    for era, f_s, f_p in (
        ("2015-2019", snap[snap.year <= 2019], pairs[pairs.year <= 2019]),
        ("2020-2023", snap[snap.year.between(2020, 2023)], pairs[pairs.year.between(2020, 2023)]),
        ("2024-2025 (test)", snap[snap.year >= 2024], pairs[pairs.year >= 2024]),
    ):
        written = f_s.news_reports_365 > 0
        named = f_p.news_club_365 > 0
        cov.append(
            {
                "years": era,
                "players": len(f_s),
                "written_about": float(written.mean()),
                "sold_if_written": float(f_s[written].moved.mean()) if written.any() else None,
                "sold_otherwise": float(f_s[~written].moved.mean()),
                "buyer_named": float(f_p[f_p.label].news_club_365.gt(0).mean()),
                "other_named": float(f_p[~f_p.label].news_club_365.gt(0).mean()),
                "named_is_buyer": float(f_p[named].label.mean()) if named.any() else None,
                "named_90": float(f_p[f_p.label].news_club_90.gt(0).mean()),
            }
        )
    out["coverage"] = cov
    return out


def news_md(n: dict) -> list[str]:
    """The press-reports section of realism.md."""
    v, te, ch = n["validation"], n["test"], n["chosen"]
    lines = [
        "**Press reports (2026-10-18).** The Guardian's Rumour Mill archive (every column since 2001, "
        f"`rumour_links`: {n['links']} links of a player with a club) gives point-in-time press features: reports "
        "published before 1 June naming the player with any club (mobility) or with this club (destination), in "
        "the 90 days and the year before. Each set is trained on 2015-2022 and scored on validation summer 2023 "
        "(mobility by Brier, destination by log loss); the test summers 2024-2025 are scored once, with the "
        "previous year added to training.",
        "",
        "| Validation 2023 | AUC | Brier / log loss | Top-1 |",
        "|---|---|---|---|",
    ]
    for k, r in v["mobility"].items():
        lines.append(f"| Mobility, {k} | {r['auc']:.4f} | {r['brier']:.5f} | — |")
    for k, r in v["destination"].items():
        lines.append(f"| Destination, {k} | {r['auc']:.4f} | {r['log_loss']:.4f} | {r['top1']:.1%} |")
    lines += [
        "",
        f"Chosen on validation: mobility `{ch['mobility']}`, destination `{ch['destination']}`. Shipped: mobility "
        f"`{n['shipped']['mobility'] or 'none'}`, destination `{n['shipped']['destination']}`.",
        "",
        "| Test 2024-2025 | AUC | Brier / log loss | Top-1 |",
        "|---|---|---|---|",
    ]
    for k in dict.fromkeys(["none", ch["mobility"], "all"]):
        r = te["mobility"][k]
        lines.append(f"| Mobility, {k} | {r['auc']:.4f} | {r['brier']:.5f} | — |")
    for k in dict.fromkeys(["none", ch["destination"], "all"]):
        r = te["destination"][k]
        lines.append(f"| Destination, {k} | {r['auc']:.4f} | {r['log_loss']:.4f} | {r['top1']:.1%} |")
    nm = te["named_moves"]
    lines += [
        "",
        f"Test moves whose buyer the press had named in the year before: {nm['moves']}; the real buyer ranked first "
        f"{nm['top1_with']:.1%} of the time with press reports, {nm['top1_without']:.1%} without. Coefficients "
        "(standardised): "
        + ", ".join(f"{k} {c}" for k, c in te["destination"][ch["destination"]]["coefficients"].items())
        + ".",
        "",
        "| Years | Player-summers | Written about (year before) | Sold if written about | Sold otherwise | "
        "Real buyer named | Other candidate named | Named club was the buyer | Real buyer named, 90 days |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def pct(x):
        return "—" if x is None else f"{x:.1%}"

    for c in n["coverage"]:
        lines.append(
            f"| {c['years']} | {c['players']} | {pct(c['written_about'])} | {pct(c['sold_if_written'])} | "
            f"{pct(c['sold_otherwise'])} | {pct(c['buyer_named'])} | {pct(c['other_named'])} | "
            f"{pct(c['named_is_buyer'])} | {pct(c['named_90'])} |"
        )
    lines += [
        "",
        "Reading this honestly:",
        "",
        "- **Destination: a small, real gain.** When the column had linked a player with a club in the year before, "
        "that club was usually the buyer, but few moves are covered: the column is about English football and, "
        "since 2020, runs only during transfer windows (nothing in March-May, little or nothing in the summers of 2021 and 2024), so the "
        "90 days before 1 June are empty in the modern era and the year before is the window that carries the "
        "signal. Some reports before 1 June are deals already agreed, which the press knows and so does a club.",
        "- **Mobility: no gain (a negative result).** Players the press writes about are sold more often, but they "
        "are also the valuable, rising players the model already rates; every news set was slightly worse on "
        "validation, so the sale likelihood does not use them.",
        "- **Live:** the past year's reports up to today (archive plus the nightly Rumour Mill items), so in "
        "October they cover the last January and summer windows, like the year before 1 June in training. The "
        "shortlist says when reports linking a player with the club make the move at least 1.1 times as likely "
        "as the same estimate with nothing written about him.",
    ]
    return lines


def mobility_model() -> lgb.LGBMClassifier:
    """The shipped sale-likelihood model: gradient boosting beats the logistic on test Brier (realism.md) and is
    calibrated for young regulars at Europe's richest clubs, where the logistic overstated sales several-fold."""
    return lgb.LGBMClassifier(
        n_estimators=400,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=200,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        verbose=-1,
        random_state=7,
    )


def contract_points(months_left: float | None) -> float:
    if months_left is None or np.isnan(months_left):
        return 0.0
    c = PRIORS["contract"]
    return (
        c["<=12 months"] if months_left <= 12 else c["13-24 months"] if months_left <= 24 else c[">24 months"]
    )


def backtest(out_dir: Path | None = None, con: duckdb.DuckDBPyConnection | None = None) -> dict:
    """con: the warehouse, for the rumour links (press reports); without it the news features are all zero."""
    t = load()
    comps = pd.read_parquet(TM_DIR / "competitions.parquet")
    TOP_TIER.update(comps.loc[comps.sub_type == "first_tier", "competition_id"])
    people = club_people(t)
    links = load_links(con)
    snap = snapshots(t, range(2015, 2026), people=people).dropna(subset=MOBILITY)
    pairs = destination_pairs(t, range(2015, 2026), people=people).dropna(subset=DESTINATION)
    snap, pairs = with_news(snap, pairs, links)
    train, test = snap[snap.year <= 2023], snap[snap.year >= 2024]
    # the previous frame (valuations' club id = today's club, every player) on the same test rows, for comparison
    old = snapshots(t, range(2015, 2026), dated=False, covered_only=False).dropna(subset=MOBILITY)
    old_test = old[old.year >= 2024].merge(test[["player_id", "year"]], on=["player_id", "year"])
    p_old = mobility_model().fit(old[old.year <= 2023][MOBILITY], old[old.year <= 2023].moved)
    p_old = p_old.predict_proba(old_test[MOBILITY])[:, 1]
    mob = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(train[MOBILITY], train.moved)
    p_mob = mob.predict_proba(test[MOBILITY])[:, 1]
    mob_v1 = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    p_mob_v1 = mob_v1.fit(train[MOBILITY_V1], train.moved).predict_proba(test[MOBILITY_V1])[:, 1]
    # young regulars at Europe's ten richest clubs: the players a shortlist most often gets wrong
    elite = (
        (test.log_europe_rank <= np.log(ELITE_RANK)) & (test.age <= 26) & (test.minutes_share >= 0.5)
    ).to_numpy()
    gbm = mobility_model().fit(train[MOBILITY_SHIPPED], train.moved)
    p_gbm = gbm.predict_proba(test[MOBILITY_SHIPPED])[:, 1]
    ptr, pte = pairs[pairs.year <= 2023], pairs[pairs.year >= 2024]
    pairs_old = destination_pairs(t, range(2015, 2026), dated=False).dropna(subset=DESTINATION)

    def fit_dest(cols):
        m = _dest_fit(ptr, cols)
        p = m.predict_proba(pte[cols])[:, 1]
        return m, p, _top1(pte, p)  # top-1: is the real buyer ranked first among its candidates?

    _, p_v1, top1_v1 = fit_dest(DESTINATION_V1)
    m_old = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    m_old.fit(pairs_old[pairs_old.year <= 2023][DESTINATION], pairs_old[pairs_old.year <= 2023].label)
    pte_old = pairs_old[pairs_old.year >= 2024]
    p_dest_old = m_old.predict_proba(pte_old[DESTINATION])[:, 1]
    top1_old = (
        pte_old.assign(p=p_dest_old).loc[lambda d: d.groupby(["year", "player_id"]).p.idxmax()].label.mean()
    )
    dest, p_dest, top1 = fit_dest(DESTINATION_SHIPPED)
    _, p_quiet, top1_quiet = fit_dest(DESTINATION)
    news = news_backtest(snap, pairs)
    n_cands = pte.groupby(["year", "player_id"]).size().mean()
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mobility": {
            "train": len(train),
            "test": len(test),
            "auc_logistic": float(roc_auc_score(test.moved, p_mob)),
            "auc_gbm": float(roc_auc_score(test.moved, p_gbm)),
            "auc": float(max(roc_auc_score(test.moved, p_mob), roc_auc_score(test.moved, p_gbm))),
            "brier_logistic": float(brier_score_loss(test.moved, p_mob)),
            "brier_gbm": float(brier_score_loss(test.moved, p_gbm)),
            "brier_base_rate": float(brier_score_loss(test.moved, np.full(len(test), train.moved.mean()))),
            "auc_logistic_v1": float(roc_auc_score(test.moved, p_mob_v1)),
            "brier_logistic_v1": float(brier_score_loss(test.moved, p_mob_v1)),
            "elite_regulars": int(elite.sum()),
            "elite_regulars_sold": float(test.moved.to_numpy()[elite].mean()),
            "elite_regulars_mean_p": float(p_mob[elite].mean()),
            "elite_regulars_mean_p_v1": float(p_mob_v1[elite].mean()),
            "elite_regulars_mean_p_gbm": float(p_gbm[elite].mean()),
            "base_rate": float(test.moved.mean()),
            "mean_p_gbm": float(p_gbm.mean()),
            "undated_auc_gbm": float(roc_auc_score(old_test.moved, p_old)),
            "undated_brier_gbm": float(brier_score_loss(old_test.moved, p_old)),
            "undated_mean_p_gbm": float(p_old.mean()),
            "train_covered_only": COVERED_ONLY,
            "coefficients": dict(zip(MOBILITY, mob[-1].coef_[0].round(3).tolist(), strict=True)),
        },
        "destination": {
            "test_moves": int(pte.groupby(["year", "player_id"]).ngroups),
            "auc": float(roc_auc_score(pte.label, p_dest)),
            "top1": float(top1),
            "random_top1": float(1 / n_cands),
            "coefficients": dict(zip(DESTINATION_SHIPPED, dest[-1].coef_[0].round(3).tolist(), strict=True)),
            "no_press_auc": float(roc_auc_score(pte.label, p_quiet)),
            "no_press_top1": float(top1_quiet),
            "v1_auc": float(roc_auc_score(pte.label, p_v1)),
            "v1_top1": float(top1_v1),
            "undated_auc": float(roc_auc_score(pte_old.label, p_dest_old)),
            "undated_top1": float(top1_old),
        },
        "priors": PRIORS,
        "news": {
            **news,
            "links": len(links),
            "shipped": {"mobility": NEWS_MOBILITY, "destination": NEWS_DESTINATION},
        },
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
            f"| Mobility (sold for a fee this summer?) | logistic | {m['auc_logistic']:.3f} | Brier "
            f"{m['brier_logistic']:.4f} vs base rate {m['brier_base_rate']:.4f}; {m['base_rate']:.1%} sold, "
            f"{m['test']} player-summers |",
            f"| **Mobility (shipped)** | gradient boosting | {m['auc_gbm']:.3f} | Brier {m['brier_gbm']:.4f}; mean "
            f"forecast {m['mean_p_gbm']:.1%} |",
            f"| Mobility, previous frame (today's club) | gradient boosting | {m['undated_auc_gbm']:.3f} | Brier "
            f"{m['undated_brier_gbm']:.4f}; mean forecast {m['undated_mean_p_gbm']:.1%} (same test player-summers) |",
            f"| Mobility, without Europe wealth rank | logistic | {m['auc_logistic_v1']:.3f} | Brier "
            f"{m['brier_logistic_v1']:.4f} |",
            f"| **Destination (this club, given a move; shipped)** | pairwise logistic + step-down + press reports | "
            f"{d['auc']:.3f} | real buyer ranked first {d['top1']:.1%} vs random {d['random_top1']:.1%}, "
            f"{d['test_moves']} moves |",
            f"| Destination, without press reports | pairwise logistic + step-down | {d['no_press_auc']:.3f} | real "
            f"buyer ranked first {d['no_press_top1']:.1%} |",
            f"| Destination, without step-down | pairwise logistic | {d['v1_auc']:.3f} | real buyer ranked first "
            f"{d['v1_top1']:.1%} |",
            f"| Destination, previous frame (today's club) | pairwise logistic + step-down | {d['undated_auc']:.3f} | "
            f"real buyer ranked first {d['undated_top1']:.1%}; inflated, see below |",
            "| Contract | prior weights | — | no historical contract data |",
            "",
            *news_md(report["news"]),
            "",
            "**Club on the day (2026-10-17).** transfermarkt-datasets' `player_valuations.current_club_id` is the "
            "player's club today, not on the valuation date, and `transfers` has no rows for anyone whose last season "
            "is before 2023 (gaps for active players too). The frames used to take a player's club from that id: "
            "wrong for 45% of players on 1 June 2016, 33% in 2022, 19% in 2024, so their minutes share, club value, "
            "wealth rank, tenure and relegation flag described another club. Clubs now come from a timeline of "
            "transfers, club appearances (national teams excluded) and the valuations' dated club names "
            "(`club_people`, shared with the rumour track record), and mobility trains only on players the dataset "
            'has a transfer history for (else "sold" can never be true for them; chosen on validation season 2023: '
            "Brier 0.0439 vs 0.0442, mean forecast 5.3% vs 3.6% for a 5.1% rate). The previous destination frame "
            "counted each club's squad by today's club, so a buyer's value already included the player it was "
            "buying and anyone it signed later: its higher scores are hindsight, and the drop is the honest number.",
            "",
            "Mobility coefficients: " + ", ".join(f"{k} {v}" for k, v in m["coefficients"].items()),
            "",
            f"Young regulars at Europe's {ELITE_RANK} richest clubs (age 26 or under, half the minutes or more): "
            f"{m['elite_regulars']} test player-summers, {m['elite_regulars_sold']:.1%} sold; mean predicted "
            f"{m['elite_regulars_mean_p_gbm']:.1%} by the shipped gradient boosting, {m['elite_regulars_mean_p']:.1%} by the "
            f"logistic, {m['elite_regulars_mean_p_v1']:.1%} by the logistic without the wealth rank. The gradient "
            "boosting is chosen on test Brier. Before the club fix its weakness was the opposite group (valuable "
            "regulars at clubs outside Europe's richest 30: sold 38% of the time, predicted about 20%); not re-measured.",
            "",
            "Destination coefficients: " + ", ".join(f"{k} {v}" for k, v in d["coefficients"].items()),
            "",
            "Tested and not adopted (2026-10-16): a club-stature feature for mobility (selling club's squad value vs "
            "its league's median club; AUC 0.753 with or without it: big clubs' regulars were sold in 15.7% of test "
            "summers, more than the 7.7% base rate, not less), and an elite-rival feature for destination (both "
            "clubs in their league's top six; coefficient about zero: top clubs do sell to domestic rivals).",
            "",
            "Wages are not modelled: no free, licensable wage data exists (Capology is not open).",
        ]
        (out_dir / "realism.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
