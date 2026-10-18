"""Squad needs on played positions vs listed positions: the effect, and a check against the summer 2026 window.

Needs have no ground truth (a club can need a full-back and not find one), so this shows the effect instead:
the top two needs per Premier League club with each grouping, as of today and as of 1 June 2026, and how often
each club then signed a player in one of its two June needs (Wikipedia's summer 2026 transfer lists). Signings'
groups are counted both ways (where they start, and where they are listed) so neither grouping marks its own
homework. A random pick of two of the seven groups is the baseline.

The 1 June squads are rebuilt from today's: players who joined in the window are taken out, players sold or
loaned out in the window are put back; players whose contracts or loans ended are left out (the club knew they
were going). Values are the latest dataset valuation before 1 June and positions count only earlier starts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from math import comb
from pathlib import Path

import duckdb
import pandas as pd

from dugout_models.market import NEEDED, PL, Market, _season, agreed_signings
from dugout_models.positions import played

AS_OF = pd.Timestamp("2026-06-01")
WINDOW_END = pd.Timestamp("2026-09-15")  # Wikipedia's lists cover the window to early September
SIGNING_KINDS = ("permanent", "loan", "free")
LISTED_ONLY = 10**9  # min_starts no player reaches: everyone at his listed position (the old grouping)


def _window(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        """SELECT DISTINCT tm_player_id, tm_from_club, tm_to_club, kind, date, player_name FROM wiki_transfers
           WHERE date >= ? AND date <= ? AND tm_player_id IS NOT NULL""",
        [AS_OF.date(), WINDOW_END.date()],
    ).df()


def june_squads(mk: Market, moves: pd.DataFrame) -> pd.DataFrame:
    """Premier League squads as they stood on 1 June 2026, rebuilt from today's (see the module docstring)."""
    sq = mk.squads[mk.squads.comp == PL].copy()
    slug = dict(zip(sq.tm_club_id.astype(str), sq.club_id, strict=False))
    arrived = moves[moves.kind.isin(SIGNING_KINDS)]
    pairs = set(zip(arrived.tm_player_id.astype(str), arrived.tm_to_club.astype(str), strict=True))
    new = pd.Series(
        [(p, c) in pairs for p, c in zip(sq.tm_player_id, sq.tm_club_id, strict=True)], index=sq.index
    )
    sq = sq[~new & ~(pd.to_datetime(sq.joined, errors="coerce") >= AS_OF)]
    left = moves[moves.kind.isin(("permanent", "loan")) & moves.tm_from_club.astype(str).isin(slug)]
    left = left.sort_values("date").drop_duplicates("tm_player_id")
    left = left[~left.tm_player_id.isin(sq.tm_player_id) & left.tm_player_id.isin(mk.players.index)]
    back = pd.DataFrame(
        {
            "tm_player_id": left.tm_player_id.astype(str).to_numpy(),
            "name": left.tm_player_id.map(mk.players.name).to_numpy(),
            "tm_club_id": left.tm_from_club.astype(str).to_numpy(),
            "club_id": left.tm_from_club.astype(str).map(slug).to_numpy(),
            "birth_date": pd.to_datetime(left.tm_player_id.map(mk.players.date_of_birth))
            .dt.strftime("%Y-%m-%d")
            .to_numpy(),
            "comp": PL,
        }
    )
    sq = pd.concat([sq, back], ignore_index=True)
    v = mk.t["player_valuations"]
    before = v[v.date < AS_OF].sort_values("date").groupby("player_id").market_value_in_eur.last()
    sq["market_value_eur"] = sq.tm_player_id.map(before)
    return sq


def top_two(mk: Market, clubs: list[str]) -> dict[str, list[str]]:
    return {c: mk.needs(c).head(2).group.tolist() for c in clubs}


def _random_hit(k: int, n: int = len(NEEDED)) -> float:
    """Chance that two groups picked at random include one of the k groups the club bought in."""
    return 1 - comb(n - k, 2) / comb(n, 2)


def backtest(
    con: duckdb.DuckDBPyConnection, out_dir: Path | None = None, now: datetime | None = None
) -> dict:
    now = now or datetime.now(UTC)
    mk = Market(now)
    ap = mk.t["appearances"].copy()
    ap["date"] = pd.to_datetime(ap.date)
    ap["season"] = _season(ap.date)
    mk.ap = ap  # needs() reads the last starter's league output from appearances (Market.fit sets it)
    clubs = sorted(mk.squads.loc[mk.squads.comp == PL, "club_id"].unique())

    # today, as the site shows it (announced signings included)
    mk.incoming = agreed_signings(con, now, set(mk.squads.name))
    lineups = played()
    mk.use_positions(lineups, LISTED_ONLY)
    today_before = top_two(mk, clubs)
    mk.use_positions(lineups)
    today_after = top_two(mk, clubs)

    # 1 June 2026, before the summer window
    moves = _window(con)
    today_squads, today_now = mk.squads, mk.now
    mk.squads, mk.now, mk.incoming = june_squads(mk, moves), AS_OF, {}
    for cached in ("_league_ap", "_peer_cache"):  # windows of the last year, computed for today
        mk.__dict__.pop(cached, None)
    june_lineups = played(before=AS_OF)
    mk.use_positions(june_lineups, LISTED_ONLY)
    june_before = top_two(mk, clubs)
    listed_groups = mk.weights.groupby("tm_player_id").group.agg(set)
    mk.use_positions(june_lineups)
    june_after = top_two(mk, clubs)
    played_groups = mk.weights.groupby("tm_player_id").group.agg(set)
    mk.squads, mk.now = today_squads, today_now

    # what each club signed in the window, and in which groups
    slug = dict(zip(today_squads.tm_club_id.astype(str), today_squads.club_id, strict=False))
    ins = moves[moves.kind.isin(SIGNING_KINDS) & moves.tm_to_club.astype(str).isin(slug)].copy()
    ins = ins.drop_duplicates(["tm_player_id", "tm_to_club"])
    ins["club"] = ins.tm_to_club.astype(str).map(slug)
    ins["played"] = ins.tm_player_id.map(played_groups)
    ins["listed"] = ins.tm_player_id.map(listed_groups)
    unknown = int(ins.listed.isna().sum())
    ins = ins.dropna(subset=["listed"])

    labels = ("played", "listed")
    rows, score = [], {lab: {"before": [], "after": [], "random": []} for lab in labels}
    # per need: of the club's two needs (and its first need alone), how many saw a signing in that group
    per_need = {
        lab: {"before": [], "after": [], "first_before": [], "first_after": [], "random": []}
        for lab in labels
    }
    for c in clubs:
        mine = ins[ins.club == c]
        bought = {lab: set().union(*mine[lab]) if len(mine) else set() for lab in ("played", "listed")}
        row = {
            "club": c,
            "today_before": today_before[c],
            "today_after": today_after[c],
            "june_before": june_before[c],
            "june_after": june_after[c],
            "signings": sorted(
                f"{n} ({', '.join(sorted(g))})" for n, g in zip(mine.player_name, mine.played, strict=True)
            ),
        }
        for lab, groups in bought.items():
            if not groups:
                continue
            for k, needs in (("before", june_before[c]), ("after", june_after[c])):
                hit = bool(groups & set(needs))
                row[f"hit_{k}_{lab}"] = hit
                score[lab][k].append(hit)
                per_need[lab][k] += [g in groups for g in needs]
                per_need[lab][f"first_{k}"].append(needs[0] in groups)
            score[lab]["random"].append(_random_hit(len(groups)))
            per_need[lab]["random"] += [len(groups) / len(NEEDED)] * 2
        rows.append(row)

    def rate(x: list) -> float | None:
        return round(sum(x) / len(x), 3) if x else None

    summary = {
        lab: {k: rate(v) for k, v in s.items()} | {"clubs": len(s["before"])} for lab, s in score.items()
    }
    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "as_of": str(AS_OF.date()),
        "window_end": str(WINDOW_END.date()),
        "signings": len(ins),
        "signings_without_position": unknown,
        "changed_today": sum(today_before[c] != today_after[c] for c in clubs),
        "changed_june": sum(june_before[c] != june_after[c] for c in clubs),
        "clubs": len(clubs),
        "hit_rate": summary,
        "need_hit_rate": {lab: {k: rate(v) for k, v in s.items()} for lab, s in per_need.items()},
        "rows": rows,
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "needs.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (out_dir / "needs.md").write_text(_markdown(report), encoding="utf-8")
    return report


# Read against the June table by hand on 2026-10-19 (Wikipedia's lists; groups by where each signing starts).
HAND_CHECKS = """## Checked by hand

- **Liverpool**: June needs centre-back and defensive midfield (listed) became centre-back and full-back
  (played). They signed two centre-backs (Jérémy Jacquet; Ronald Araújo on loan) and wingers, no full-back and no
  holding midfielder: need one met either way, need two missed either way.
- **Nottingham Forest**: goalkeeper and defensive midfield (listed) vs goalkeeper and centre-forward (played).
  They signed Liam Delap (centre-forward): a hit only with played positions.
- **Everton**: centre-back and goalkeeper with both groupings; they signed wingers, a full-back and a holding
  midfielder instead: a miss either way.
- **Manchester United**: defensive and central midfield (listed) vs full-back and defensive midfield (played).
  They signed Carlos Baleba, Andrey Santos and Youri Tielemans: listed positions call both needs, played positions
  one (no full-back came).
- **Tottenham**: centre-forward and full-back (listed) vs defensive midfield and full-back (played). Omar Marmoush,
  Andy Robertson and Sandro Tonali make both groupings two for two.

**Verdict.** Played positions change the top two at about half the clubs and describe squads more truthfully (a
centre-back who plays right-back now covers full-back), but they do not predict what clubs then bought any better
than listed positions, and neither beats random picks: clubs sign across most groups in a window, and a need is
only one reason to buy. Kept for its description of the squad, not for a measured gain.
"""


def _markdown(r: dict) -> str:
    def needs(x: list[str]) -> str:
        return " · ".join(x)

    def tick(row: dict, k: str, lab: str) -> str:
        v = row.get(f"hit_{k}_{lab}")
        return "" if v is None else ("yes" if v else "no")

    h, hn = r["hit_rate"], r["need_hit_rate"]
    lines = [
        "# Squad needs: played positions vs listed positions",
        "",
        f"Generated {r['generated_at']} by `uv run dugout-models backtest needs` (dugout_models/needs_backtest.py).",
        "",
        "**What changed.** A squad's depth at each position group used to count every player once, at his listed "
        "Transfermarkt position. It now counts him where he actually starts (transfermarkt-datasets starting XIs "
        "since 2023-24): in every group with 25%+ of his starts, weighted by his share there. Players with fewer "
        "than 10 recorded starts (new signings from leagues the dataset lacks, youngsters) stay at their listed "
        "position. The six comparison squads are grouped the same way.",
        "",
        "**No ground truth.** A need is a judgement, not an event, so this report shows the effect: the top two "
        "needs per Premier League club with each grouping, and a sanity check against what clubs did next.",
        "",
        f"## Top-two needs as the site shows them today ({r['changed_today']} of {r['clubs']} clubs change)",
        "",
        "| Club | Listed positions (before) | Played positions (after) | Changed |",
        "|---|---|---|---|",
        *[
            f"| {x['club']} | {needs(x['today_before'])} | {needs(x['today_after'])} | "
            f"{'' if x['today_before'] == x['today_after'] else 'yes'} |"
            for x in r["rows"]
        ],
        "",
        f"## Check against the summer 2026 window ({r['changed_june']} of {r['clubs']} clubs change on 1 June)",
        "",
        f"Needs as of {r['as_of']} (squads rebuilt to that day, see the module docstring), signings from "
        f"Wikipedia's transfer lists from {r['as_of']} to {r['window_end']} (permanent, loan and free moves; "
        f"{r['signings']} signings with a known position, {r['signings_without_position']} without one left out). "
        '"Hit" = the club signed at least one player in one of its two needs. A signing\'s groups are counted '
        "where he starts (25%+ of starts) and, separately, at his listed position. Random = two of the seven "
        "groups picked at random, given how many groups each club bought in.",
        "",
        "| Signing's group counted by | Clubs | Listed-position needs (before) | Played-position needs (after) | "
        "Random two groups |",
        "|---|---|---|---|---|",
        *[
            f"| {lab} positions | {h[lab]['clubs']} | {h[lab]['before']:.0%} | {h[lab]['after']:.0%} | "
            f"{h[lab]['random']:.0%} |"
            for lab in ("played", "listed")
            if h[lab]["clubs"]
        ],
        "",
        "Club level is a weak test: clubs signed in several groups, so two random groups already hit most of the "
        "time. Per need is sharper: of the forty (club, need) pairs, the share where the club signed someone in "
        "that group, against the share of the seven groups the club bought in (random).",
        "",
        "| Signing's group counted by | Both needs, before | Both needs, after | First need, before | "
        "First need, after | Random group |",
        "|---|---|---|---|---|---|",
        *[
            f"| {lab} positions | {hn[lab]['before']:.0%} | {hn[lab]['after']:.0%} | "
            f"{hn[lab]['first_before']:.0%} | {hn[lab]['first_after']:.0%} | {hn[lab]['random']:.0%} |"
            for lab in ("played", "listed")
            if hn[lab]["before"] is not None
        ],
        "",
        "| Club | June needs, before | June needs, after | Signed (groups where he starts) | Hit before | "
        "Hit after |",
        "|---|---|---|---|---|---|",
        *[
            f"| {x['club']} | {needs(x['june_before'])} | {needs(x['june_after'])} | "
            f"{'; '.join(x['signings']) or 'none recorded'} | {tick(x, 'before', 'played')} | "
            f"{tick(x, 'after', 'played')} |"
            for x in r["rows"]
        ],
        "",
        HAND_CHECKS,
    ]
    return "\n".join(lines)
