"""Transfer market outputs for `publish`: fair value, sale likelihood and a scouting shortlist per club.

Built from transfermarkt-datasets (CC0; valuations and appearances run to June 2026) plus the committed current
squad file `data/reference/transfermarkt_squads.csv` (values and contracts as of the last local refresh).

  fair_fee              valuation model (docs/backtests/valuation.md): price if sold to another Premier League club
  sale_likelihood       mobility model (realism.md): P(sold for a fee in a transfer window), features as of today
  needs                 positions where the club is thinnest/weakest (heuristic: depth and value at the position)
  shortlist             candidates per need, ranked by the mean percentile of quality (market value), playing-time
                        outlook at the club (opportunity.md) and transfer realism (realism.md). The ranking rule is a
                        transparent heuristic; each component is a backtested model.
"""

from __future__ import annotations

import logging
from datetime import datetime

import duckdb
import numpy as np
import pandas as pd
from dugout_pipeline.settings import REPO_ROOT
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from dugout_models import realism, valuation
from dugout_models.opportunity import FEATURES as OPP_FEATURES
from dugout_models.opportunity import OpportunityModel
from dugout_models.opportunity import build as opportunity_frame
from dugout_models.publish import _row

log = logging.getLogger(__name__)

SQUADS = REPO_ROOT / "data" / "reference" / "transfermarkt_squads.csv"
PL = "GB1"
# Position groups a club needs covered, as transfermarkt sub-positions.
GROUPS = {
    "goalkeeper": ["Goalkeeper"],
    "centre-back": ["Centre-Back"],
    "full-back": ["Right-Back", "Left-Back"],
    "defensive midfield": ["Defensive Midfield"],
    "central midfield": ["Central Midfield", "Attacking Midfield"],
    "winger": ["Right Winger", "Left Winger", "Right Midfield", "Left Midfield"],
    "centre-forward": ["Centre-Forward", "Second Striker"],
}
NEEDED = {
    "goalkeeper": 2,
    "centre-back": 4,
    "full-back": 4,
    "defensive midfield": 2,
    "central midfield": 4,
    "winger": 4,
    "centre-forward": 2,
}
SHORTLIST = 5


def _season(d: pd.Series) -> pd.Series:
    return pd.Series(np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1), index=d.index)


class Market:
    def __init__(self, now: datetime):
        self.now = pd.Timestamp(now.date())
        self.t = valuation.load()
        comps = pd.read_parquet(valuation.TM_DIR / "competitions.parquet")
        self.comps = comps
        realism.TOP_TIER.update(comps.loc[comps.sub_type == "first_tier", "competition_id"])
        self.squads = pd.read_csv(SQUADS, dtype={"tm_player_id": str, "tm_club_id": str})
        self.players = self.t["players"].copy()
        self.players["player_id"] = self.players.player_id.astype(str)
        self.players = self.players.set_index("player_id")
        self._with_current_values()
        self.clubs = self.t["clubs"].copy()
        self.clubs["club_id"] = self.clubs.club_id.astype(str)

    def _with_current_values(self) -> None:
        """Adds today's squad-file values as valuation rows, so 'latest value' means October, not June."""
        v = self.t["player_valuations"].copy()
        v["player_id"] = v.player_id.astype(str)
        v["current_club_id"] = v.current_club_id.astype(str)
        sq = self.squads.dropna(subset=["market_value_eur"])
        extra = pd.DataFrame(
            {
                "player_id": sq.tm_player_id,
                "date": pd.to_datetime(sq.scraped_on),
                "market_value_in_eur": sq.market_value_eur.astype(float),
                "current_club_name": sq.club_id,
                "current_club_id": sq.tm_club_id,
                "player_club_domestic_competition_id": PL,
            }
        )
        v["date"] = pd.to_datetime(v.date)
        self.t["player_valuations"] = pd.concat([v, extra], ignore_index=True)
        for k in ("transfers", "appearances"):
            df = self.t[k].copy()
            for c in ("player_id", "from_club_id", "to_club_id", "player_club_id"):
                if c in df:
                    df[c] = df[c].astype(str)
            self.t[k] = df
        self.t["players"]["player_id"] = self.t["players"].player_id.astype(str)
        self.t["clubs"]["club_id"] = self.t["clubs"].club_id.astype(str)

    # -- fitted models ---------------------------------------------------------------------------------------
    def fit(self) -> None:
        df = valuation.build(self.t)
        self.val = valuation.ValuationModel().fit(df[df.date <= self.now])
        snap = realism.snapshots(self.t, range(2015, 2026)).dropna(subset=realism.MOBILITY)
        self.mob = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(
            snap[realism.MOBILITY], snap.moved
        )
        self.mob_base = float(snap.moved.mean())
        pairs = realism.destination_pairs(self.t, range(2015, 2026)).dropna(subset=realism.DESTINATION)
        self.dest = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)).fit(
            pairs[realism.DESTINATION], pairs.label
        )
        self.dest_base = float(pairs.label.mean())
        self.opp = OpportunityModel().fit(opportunity_frame())
        self.now_snap = realism.snapshots(self.t, [self.now.year], as_of=self.now).set_index("player_id")
        self.league_value = valuation.league_strength(self.t).set_index(["comp", "year"]).league_value
        vals = self.t["player_valuations"]
        recent = (
            vals[vals.date >= self.now - pd.Timedelta(days=365)]
            .sort_values("date")
            .groupby("player_id")
            .tail(1)
        )
        self.club_value = recent.groupby("current_club_id").market_value_in_eur.sum()
        self.latest_value = vals.sort_values("date").groupby("player_id").market_value_in_eur.last()
        tr = self.t["transfers"].copy()
        tr["date"] = pd.to_datetime(tr.transfer_date)
        tr["fee"] = pd.to_numeric(tr.transfer_fee, errors="coerce")
        recent_tr = tr[(tr.date < self.now) & (tr.date >= self.now - pd.Timedelta(days=1095))]
        self.capacity = recent_tr.groupby("to_club_id").fee.max()
        ap = self.t["appearances"].copy()
        ap["date"] = pd.to_datetime(ap.date)
        ap["season"] = _season(ap.date)
        self.ap = ap

    # -- per-player pieces -----------------------------------------------------------------------------------
    def comp_of(self, tm_club: str) -> str | None:
        row = self.clubs.loc[self.clubs.club_id == str(tm_club), "domestic_competition_id"]
        return row.iloc[0] if len(row) else None

    def fair_fee(self, ids: list[str], seller_comp: list[str | None]) -> pd.DataFrame:
        ap = self.ap[(self.ap.date < self.now) & (self.ap.date >= self.now - pd.Timedelta(days=365))]
        form = ap.groupby("player_id").agg(
            minutes_365=("minutes_played", "sum"),
            goals=("goals", "sum"),
            assists=("assists", "sum"),
            apps_365=("game_id", "nunique"),
        )
        year = self.now.year
        ls_year = max(y for c, y in self.league_value.index if c == PL)
        df = pd.DataFrame({"player_id": ids, "from_comp": seller_comp})
        df["age"] = (self.now - pd.to_datetime(df.player_id.map(self.players.date_of_birth))).dt.days / 365.25
        df["log_mv"] = np.log1p(df.player_id.map(self.latest_value))
        df = df.join(form, on="player_id")
        df[["minutes_365", "goals", "assists", "apps_365"]] = df[
            ["minutes_365", "goals", "assists", "apps_365"]
        ].fillna(0)
        df["ga_p90_365"] = (df.goals + df.assists) / df.minutes_365.clip(lower=90) * 90
        df["log_from_league"] = np.log1p([self.league_value.get((c, ls_year), np.nan) for c in df.from_comp])
        df["log_to_league"] = np.log1p(self.league_value.get((PL, ls_year), np.nan))
        df["same_league"] = (df.from_comp == PL).astype(float)
        df["year"] = year
        pos = df.player_id.map(self.players.position)
        for p in ("Attack", "Midfield", "Defender", "Goalkeeper"):
            df[f"pos_{p}"] = (pos == p).astype(float)
        ok = df.dropna(subset=["age", "log_mv"]).index
        out = pd.DataFrame(index=df.index, columns=["fair_fee", "low", "high"], dtype=float)
        if len(ok):
            out.loc[ok] = self.val.predict(df.loc[ok]).to_numpy()
        return out

    def sale_likelihood(self, ids: list[str]) -> pd.Series:
        snap = self.now_snap.reindex(ids)
        ok = snap.dropna(subset=realism.MOBILITY)
        p = pd.Series(np.nan, index=ids)
        if len(ok):
            p.loc[ok.index] = self.mob.predict_proba(ok[realism.MOBILITY])[:, 1]
        return p

    def realism_score(self, pid: str, seller: str, buyer: str, fee: float) -> dict | None:
        p_mob = self.sale_likelihood([pid]).iloc[0]
        if np.isnan(p_mob) or seller not in set(self.clubs.club_id) or buyer not in set(self.clubs.club_id):
            return None
        clubs = self.clubs.set_index("club_id")
        comps = self.comps.set_index("competition_id")
        f = realism._pair_features(fee, seller, buyer, self.capacity, clubs, comps, self.club_value)
        p_dest = float(self.dest.predict_proba(pd.DataFrame([f])[realism.DESTINATION])[:, 1][0])
        expiry = pd.to_datetime(self.players.contract_expiration_date.get(pid))
        months = (expiry - self.now).days / 30.44 if pd.notna(expiry) else None
        c = realism.contract_points(months)

        def logit(x):
            x = min(max(x, 1e-4), 1 - 1e-4)
            return np.log(x / (1 - x))

        z = logit(p_mob) - logit(self.mob_base) + logit(p_dest) - logit(self.dest_base) + c
        return {
            "realism": float(100 / (1 + np.exp(-z))),
            "p_sold": float(p_mob),
            "p_this_club": float(p_dest),
            "contract_months": None if months is None else float(months),
        }

    def outlook(self, pid: str, buyer: str, fee: float, incumbents: pd.DataFrame) -> float | None:
        """Expected minutes share at `buyer` (opportunity model) given the current squad at his position."""
        last = self.now.year - 1 if self.now.month >= 7 else self.now.year - 2  # last completed season
        own = self.ap[(self.ap.player_id == pid) & (self.ap.season == last)]
        if own.empty:
            return None
        club = own.player_club_id.mode().iloc[0]
        games = self.ap[(self.ap.player_club_id == club) & (self.ap.season == last)].date.nunique()
        mv = self.latest_value.get(pid, np.nan)
        dob = pd.to_datetime(self.players.date_of_birth.get(pid))
        inc_vals = incumbents.market_value_eur.astype(float)
        record = self.capacity.get(buyer, np.nan)
        ls_year = max(y for c, y in self.league_value.index if c == PL)
        row = {
            "prev_share": own.minutes_played.sum() / (90 * max(games, 1)),
            "log_mv": np.log1p(mv),
            "age": (self.now - dob).days / 365.25 if pd.notna(dob) else np.nan,
            "league_gap": np.log1p(self.league_value.get((PL, ls_year), np.nan))
            - np.log1p(self.league_value.get((self.comp_of(club), ls_year), np.nan)),
            "rank_at_pos": 1 + int((inc_vals > mv).sum()),
            "value_vs_best": np.log1p(mv) - np.log1p(inc_vals.max()) if len(inc_vals) else 0.0,
            "incumbents": len(incumbents),
            "fee_vs_record": np.log1p(fee) - np.log1p(record) if record == record else 0.0,
        }
        row["age2"] = (row["age"] - 26) ** 2
        x = pd.DataFrame([row])[OPP_FEATURES]
        if x.isna().any(axis=None):
            return None
        return float(self.opp.predict(x)[0])

    # -- club level ------------------------------------------------------------------------------------------
    def squad(self, club_slug: str) -> pd.DataFrame:
        sq = self.squads[self.squads.club_id == club_slug].copy()
        sq["sub_position"] = sq.tm_player_id.map(self.players.sub_position)
        sq["group"] = sq.sub_position.map({s: g for g, subs in GROUPS.items() for s in subs})
        sq["age"] = (self.now - pd.to_datetime(sq.birth_date)).dt.days / 365.25
        return sq

    def needs(self, club_slug: str) -> pd.DataFrame:
        """Score each position group: missing depth (vs a two-deep squad) and value of the best option
        relative to the squad's best eleven. Higher = bigger need."""
        sq = self.squad(club_slug)
        top11 = sq.market_value_eur.nlargest(11).median()
        rows = []
        for g, want in NEEDED.items():
            at = sq[(sq.group == g) & (sq.age < 33)]
            depth_gap = max(0, want - len(at)) / want
            best = at.market_value_eur.max() if len(at) else 0.0
            quality_gap = max(0.0, 1 - (best or 0) / top11) if top11 else 0.0
            ageing = float((sq[(sq.group == g)].age >= 31).mean()) if (sq.group == g).any() else 0.0
            rows.append(
                {
                    "group": g,
                    "score": depth_gap + quality_gap + 0.5 * ageing,
                    "depth": len(at),
                    "depth_gap": depth_gap,
                    "quality_gap": quality_gap,
                    "ageing_share": ageing,
                }
            )
        return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

    def shortlist(self, club_slug: str, group: str, tm_club: str) -> pd.DataFrame:
        sq = self.squad(club_slug)
        cap = self.capacity.get(tm_club, np.nan)
        cap = cap if cap == cap and cap > 0 else self.club_value.get(tm_club, 0) * 0.1
        pool = self.players.reset_index()
        pool = pool[
            pool.sub_position.isin(GROUPS[group])
            & (
                pool.current_club_domestic_competition_id.isin(
                    self.comps.loc[self.comps.sub_type == "first_tier", "competition_id"]
                )
            )
            & (pool.current_club_id.astype(str) != tm_club)
            & (pool.last_season >= self.now.year - 1)
        ].copy()
        pool["age"] = (self.now - pd.to_datetime(pool.date_of_birth)).dt.days / 365.25
        pool["value"] = pool.player_id.map(self.latest_value)
        recent = (
            self.ap[(self.ap.date >= self.now - pd.Timedelta(days=365))]
            .groupby("player_id")
            .minutes_played.sum()
        )
        pool["minutes_365"] = pool.player_id.map(recent).fillna(0)
        pool = pool[
            pool.age.between(18, 29)
            & (pool.value >= 0.15 * cap)
            & (pool.value <= 1.2 * cap)
            & (pool.minutes_365 >= 1200)
        ]
        pool = pool.nlargest(60, "value")  # the realism/outlook models are per-pair; keep the pool bounded
        if pool.empty:
            return pool
        fees = self.fair_fee(pool.player_id.tolist(), pool.current_club_domestic_competition_id.tolist())
        pool["fair_fee"] = fees.fair_fee.to_numpy()
        incumbents = sq[sq.group == group]
        out = []
        for r in pool.itertuples():
            fee = r.fair_fee if r.fair_fee == r.fair_fee else r.value
            rs = self.realism_score(r.player_id, str(r.current_club_id), tm_club, fee)
            share = self.outlook(r.player_id, tm_club, fee, incumbents)
            if rs is None or share is None:
                continue
            out.append(
                {
                    "tm_player_id": r.player_id,
                    "name": r.name,
                    "club": r.current_club_name,
                    "age": r.age,
                    "value": r.value,
                    "fair_fee": fee,
                    "minutes_share": share,
                    **rs,
                }
            )
        df = pd.DataFrame(out)
        if df.empty:
            return df
        df["score"] = (
            df.value.rank(pct=True) + df.minutes_share.rank(pct=True) + df.realism.rank(pct=True)
        ) / 3
        return df.sort_values("score", ascending=False).head(SHORTLIST).reset_index(drop=True)


def _tm_to_reep(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    from dugout_pipeline.ids import attach_catalogue

    if not attach_catalogue(con):
        return {}
    rows = con.execute(
        "SELECT external_id, reep_id FROM reep.bridges WHERE provider='transfermarkt' AND namespace='spieler'"
    ).fetchall()
    return {str(a): b for a, b in rows}


def market(con: duckdb.DuckDBPyConnection, now: datetime, clubs: list[str] | None = None) -> list[dict]:
    mk = Market(now)
    mk.fit()
    reep = _tm_to_reep(con)
    showcase = clubs or sorted(mk.squads.club_id.unique())
    rows: list[dict] = []
    # fair value and sale likelihood for every current Premier League player
    sq = mk.squads.copy()
    fees = mk.fair_fee(sq.tm_player_id.tolist(), [PL] * len(sq))
    sale = mk.sale_likelihood(sq.tm_player_id.tolist())
    for r, f, s in zip(sq.itertuples(), fees.itertuples(), sale.to_numpy(), strict=True):
        pid = (
            r.player_id
            if isinstance(r.player_id, str)
            else reep.get(r.tm_player_id, f"transfermarkt:{r.tm_player_id}")
        )
        if f.fair_fee == f.fair_fee:
            rows += [
                _row("valuation", "player", pid, "fair_fee", round(f.fair_fee, -5), now),
                _row("valuation", "player", pid, "fair_fee_low", round(f.low, -5), now),
                _row("valuation", "player", pid, "fair_fee_high", round(f.high, -5), now),
            ]
        if s == s:
            rows.append(_row("realism", "player", pid, "sale_likelihood", round(float(s), 3), now))
    for slug in showcase:
        tm_club = mk.squads.loc[mk.squads.club_id == slug, "tm_club_id"].iloc[0]
        needs = mk.needs(slug)
        for i, n in needs.head(2).iterrows():
            rank = i + 1
            rows.append(_row("scout", "club", slug, "need", n.group, now, f"need:{rank}"))
            rows.append(_row("scout", "club", slug, "need_depth", int(n.depth), now, f"need:{rank}"))
            short = mk.shortlist(slug, n.group, str(tm_club))
            for k, c in short.iterrows():
                pid = reep.get(c.tm_player_id, f"transfermarkt:{c.tm_player_id}")
                ctx = f"{slug}:need:{rank}:{k + 1}"
                rows += [
                    _row("scout", "player", pid, "candidate_name", c["name"], now, ctx),
                    _row("scout", "player", pid, "candidate_club", c.club, now, ctx),
                    _row("scout", "player", pid, "candidate_position", n.group, now, ctx),
                    _row("scout", "player", pid, "age", round(c.age, 1), now, ctx),
                    _row("scout", "player", pid, "market_value", c.value, now, ctx),
                    _row("scout", "player", pid, "fair_fee", round(c.fair_fee, -5), now, ctx),
                    _row(
                        "scout", "player", pid, "expected_minutes_share", round(c.minutes_share, 3), now, ctx
                    ),
                    _row("scout", "player", pid, "realism", round(c.realism, 1), now, ctx),
                    _row("scout", "player", pid, "p_sold", round(c.p_sold, 3), now, ctx),
                    _row("scout", "player", pid, "p_this_club", round(c.p_this_club, 3), now, ctx),
                    _row("scout", "player", pid, "shortlist_score", round(c.score, 3), now, ctx),
                ]
                if pd.notna(c.contract_months):
                    rows.append(
                        _row("scout", "player", pid, "contract_months", round(c.contract_months), now, ctx)
                    )
        log.info("market: %s done", slug)
    return rows
