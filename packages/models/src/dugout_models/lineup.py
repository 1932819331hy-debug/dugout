"""Lineup optimiser: OR-Tools CP-SAT integer program.

maximise   sum_{p,s} x[p,s] * (rating[p] * fit[p,s] - fatigue[p])
subject to each formation slot filled exactly once, each player in at most one slot, unavailable players
excluded, fit[p,s] = 0 means the player cannot play that slot.

Rating: FPL ICT index per 90 (Opta-based composite of influence, creativity, threat), season-to-date,
standardised within position group, shrunk towards the group mean for small samples.
Slot fit: transfermarkt sub-positions (exact 1.0, adjacent 0.75, same line 0.4).
Fatigue: penalty for heavy recent load (minutes in the previous 7 days above 135).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

SCALE = 1000  # CP-SAT needs integer coefficients
# Blend of quality and manager trust for the *predicted* XI, chosen on 2023-24 (see docs/backtests/lineup.md).
PREDICTED_XI_TRUST = 0.75

FORMATIONS: dict[str, list[str]] = {
    "4-3-3": ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "CF", "LW"],
    "4-2-3-1": ["GK", "RB", "CB", "CB", "LB", "DM", "DM", "RW", "AM", "LW", "CF"],
    "3-4-2-1": ["GK", "CB", "CB", "CB", "RWB", "CM", "CM", "LWB", "AM", "AM", "CF"],
    "4-4-2": ["GK", "RB", "CB", "CB", "LB", "RM", "CM", "CM", "LM", "CF", "CF"],
}

# transfermarkt sub_position -> our slot code
SUB = {
    "Goalkeeper": "GK",
    "Centre-Back": "CB",
    "Right-Back": "RB",
    "Left-Back": "LB",
    "Defensive Midfield": "DM",
    "Central Midfield": "CM",
    "Attacking Midfield": "AM",
    "Right Midfield": "RM",
    "Left Midfield": "LM",
    "Right Winger": "RW",
    "Left Winger": "LW",
    "Second Striker": "CF",
    "Centre-Forward": "CF",
}
LINE = {
    "GK": "G",
    "CB": "D",
    "RB": "D",
    "LB": "D",
    "RWB": "D",
    "LWB": "D",
    "DM": "M",
    "CM": "M",
    "AM": "M",
    "RM": "M",
    "LM": "M",
    "RW": "F",
    "LW": "F",
    "CF": "F",
}
ADJACENT = {
    ("RB", "RWB"),
    ("LB", "LWB"),
    ("RB", "CB"),
    ("LB", "CB"),
    ("DM", "CM"),
    ("CM", "AM"),
    ("AM", "CF"),
    ("RW", "RM"),
    ("LW", "LM"),
    ("RW", "AM"),
    ("LW", "AM"),
    ("RW", "CF"),
    ("LW", "CF"),
    ("RWB", "RM"),
    ("LWB", "LM"),
    ("DM", "CB"),
    ("RM", "CM"),
    ("LM", "CM"),
}


def fit_score(player_slot: str | None, slot: str) -> float:
    if not isinstance(player_slot, str) or player_slot not in LINE:  # unknown position (NaN / unmapped)
        return 0.0
    if player_slot == slot:
        return 1.0
    if (player_slot, slot) in ADJACENT or (slot, player_slot) in ADJACENT:
        return 0.75
    if slot == "GK" or player_slot == "GK":
        return 0.0
    return 0.4 if LINE[player_slot] == LINE[slot] else 0.0


@dataclass
class Selection:
    formation: str
    xi: list[tuple[str, str]]  # (player_id, slot)
    objective: float


def optimise(squad: pd.DataFrame, formation: str = "4-3-3", time_limit: float = 5.0) -> Selection:
    """squad columns: player_id, slot (natural position code), rating (z-score), available (bool),
    fatigue (>= 0, same units as rating)."""
    slots = FORMATIONS[formation]
    squad = squad[squad.available].reset_index(drop=True)
    m = cp_model.CpModel()
    x = {}
    for p in squad.itertuples():
        for j, s in enumerate(slots):
            f = fit_score(p.slot, s)
            if f > 0:
                x[p.Index, j] = m.NewBoolVar(f"x_{p.Index}_{j}")
    for j in range(len(slots)):
        m.AddExactlyOne([v for (i, jj), v in x.items() if jj == j])
    for i in range(len(squad)):
        m.AddAtMostOne([v for (ii, _), v in x.items() if ii == i])
    # shift ratings positive so every filled slot adds value; fit scales quality, fatigue subtracts
    base = squad.rating - squad.rating.min() + 1.0
    m.Maximize(
        sum(
            v * int(SCALE * (base[i] * fit_score(squad.slot[i], slots[j]) - squad.fatigue[i]))
            for (i, j), v in x.items()
        )
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ValueError(f"no feasible {formation} XI from {len(squad)} available players")
    xi = [(squad.player_id[i], slots[j]) for (i, j), v in x.items() if solver.Value(v)]
    return Selection(formation, xi, solver.ObjectiveValue() / SCALE)


def best_formation(squad: pd.DataFrame, formations: list[str] | None = None) -> Selection:
    out = []
    for f in formations or list(FORMATIONS):
        try:
            out.append(optimise(squad, f))
        except ValueError:
            continue
    return max(out, key=lambda s: s.objective)


def ratings_from_history(hist: pd.DataFrame, prior_minutes: float = 450) -> pd.Series:
    """ICT per 90 by player, standardised within line, shrunk towards the line mean for low minutes."""
    g = hist.groupby("player_id").agg(ict=("ict", "sum"), minutes=("minutes", "sum"), line=("line", "last"))
    per90 = g.ict / g.minutes.clip(lower=1) * 90
    z = per90.groupby(g.line).transform(lambda s: (s - s.mean()) / (s.std() or 1))
    w = g.minutes / (g.minutes + prior_minutes)
    return (w * z).fillna(0)


def backtest(
    stats: pd.DataFrame,
    positions: pd.DataFrame,
    absences: pd.DataFrame,
    trust_weights: tuple[float, ...] = (0.0,),
) -> dict:
    """stats: per player-match rows (match_id, date, club_id, player_id, minutes, starts, ict);
    positions: player_id -> slot; absences: (player_id, date) injury absences known before kick-off."""
    stats = stats.merge(positions, on="player_id", how="left")
    stats["line"] = stats.slot.map(LINE)
    absent = set(zip(absences.player_id, absences.date, strict=True))
    overlap_opt: dict[float, list[float]] = {w: [] for w in trust_weights}
    overlap_base, n = [], 0
    for (club, _match), grp in stats.groupby(["club_id", "match_id"]):
        date = grp.date.iloc[0]
        hist = stats[(stats.club_id == club) & (stats.date < date)]
        if hist.match_id.nunique() < 5:
            continue
        actual = set(grp.loc[grp.starts == 1, "player_id"])
        if len(actual) != 11:
            continue
        squad_ids = hist.player_id.unique()
        r = ratings_from_history(hist)
        last7 = hist[hist.date >= date - pd.Timedelta(days=7)].groupby("player_id").minutes.sum()
        squad = pd.DataFrame({"player_id": squad_ids})
        squad = squad.merge(positions, on="player_id", how="left")
        quality = squad.player_id.map(r).fillna(0)
        last5 = hist[hist.match_id.isin(hist.drop_duplicates("match_id").nlargest(5, "date").match_id)]
        share = squad.player_id.map(last5.groupby("player_id").minutes.sum() / (5 * 90)).fillna(0)
        trust = (share - share.mean()) / (share.std() or 1)
        squad["available"] = [(p, date) not in absent for p in squad.player_id]
        squad["fatigue"] = (squad.player_id.map(last7).fillna(0) - 135).clip(lower=0) / 90 * 0.5
        picks = {}
        for w in trust_weights:
            squad["rating"] = (1 - w) * quality + w * trust
            try:
                picks[w] = {p for p, _ in best_formation(squad).xi}
            except ValueError:
                break
        if len(picks) != len(trust_weights):
            continue
        for w, chosen in picks.items():
            overlap_opt[w].append(len(chosen & actual) / 11)
        base = set(last5.groupby("player_id").minutes.sum().nlargest(11).index)
        overlap_base.append(len(base & actual) / 11)
        n += 1
    return {
        "matches": n,
        "optimiser_overlap": {str(w): float(np.mean(v)) for w, v in overlap_opt.items()},
        "recent_minutes_baseline_overlap": float(np.mean(overlap_base)),
    }


def run_backtest(
    con,
    season: str = "2024-25",
    api_season: int = 2024,
    out_dir=None,
    trust_weights: tuple[float, ...] = (0.0,),
) -> dict:
    """Agreement of the optimiser's XI with the XI the manager actually picked, vs a recent-minutes heuristic."""
    import json
    from datetime import UTC, datetime

    from dugout_pipeline.ids import attach_catalogue

    from dugout_models.injury import INJURY_DIR, TM_DIR

    stats = con.execute(
        """SELECT s.match_id, CAST(m.kickoff_utc AS DATE) AS date, s.club_id, s.player_id, s.minutes, s.starts,
                  coalesce(s.influence, 0) + coalesce(s.creativity, 0) + coalesce(s.threat, 0) AS ict
           FROM player_match_stats s JOIN matches m USING (match_id)
           WHERE s.source = 'fpl_history' AND m.season = ? AND s.starts IS NOT NULL""",
        [season],
    ).df()
    stats["date"] = pd.to_datetime(stats.date)
    attach_catalogue(con)
    tm = pd.read_parquet(TM_DIR / "players.parquet", columns=["player_id", "sub_position"])
    tm["player_id"] = tm.player_id.astype(str)
    bridge = con.execute("""SELECT reep_id, external_id FROM reep.bridges
                            WHERE provider='transfermarkt' AND namespace='spieler'""").df()
    positions = (
        bridge.merge(tm, left_on="external_id", right_on="player_id")
        .assign(slot=lambda d: d.sub_position.map(SUB))[["reep_id", "slot"]]
        .rename(columns={"reep_id": "player_id"})
        .drop_duplicates("player_id")
    )
    inj = pd.read_parquet(INJURY_DIR / f"injuries_{api_season}.parquet")
    inj = inj[inj.type == "Missing Fixture"].dropna(subset=["reep_id"])
    absences = pd.DataFrame({"player_id": inj.reep_id, "date": pd.to_datetime(inj.date)})
    res = backtest(stats, positions, absences, trust_weights)
    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "season": season, **res}
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "lineup.json").write_text(json.dumps(report, indent=2))
        lines = [
            "# Lineup optimiser backtest",
            "",
            f"Generated {report['generated_at']}. Season {season}: for each club and match, the optimiser picks the "
            "best XI from players available that day (injury absences removed), using only data before kick-off.",
            "",
            "| Method | Mean overlap with the actual XI | Team-matches |",
            "|---|---|---|",
        ]
        labels = {
            "0.0": "Strongest XI (quality only: ICT/90 x position fit, fatigue)",
            str(PREDICTED_XI_TRUST): f"**Predicted XI** (quality + trust, weight {PREDICTED_XI_TRUST})",
        }
        for w, v in res["optimiser_overlap"].items():
            lines.append(f"| {labels.get(w, f'trust weight {w}')} | {v:.1%} | {res['matches']} |")
        lines += [
            f"| Most minutes in the last 5 matches (heuristic) | {res['recent_minutes_baseline_overlap']:.1%} | "
            f"{res['matches']} |",
            "",
            f"Trust weight {PREDICTED_XI_TRUST} was chosen on 2023-24 (validation); this table is the 2024-25 test.",
            "Trust = share of the last five matches' minutes. The strongest XI ignores managers' habits by design.",
        ]
        (out_dir / "lineup.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
