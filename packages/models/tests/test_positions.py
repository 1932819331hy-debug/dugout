import pandas as pd
import pytest
from dugout_models.market import GROUP_OF, GROUPS, NEEDED, Market
from dugout_models.positions import group_weights


def _lineups(starts: dict[str, dict[str, int]]) -> pd.DataFrame:
    """played()-shaped rows from {player: {position: starts}}."""
    rows = [(p, pos, n) for p, by in starts.items() for pos, n in by.items()]
    out = pd.DataFrame(rows, columns=["player_id", "position", "starts"])
    out["share"] = out.starts / out.groupby("player_id").starts.transform("sum")
    return out


def _weights(w: pd.DataFrame, pid: str) -> dict[str, float]:
    return dict(w.loc[w.player_id == pid, ["group", "weight"]].itertuples(index=False))


def test_group_weights_count_players_where_they_start():
    lu = _lineups(
        {
            "cb": {"Centre-Back": 30, "Right-Back": 20},  # a centre-back who also starts at right-back
            "fb": {"Right-Back": 12, "Left-Back": 12, "Right Winger": 6},  # both flanks add up to one group
            "dm": {"Defensive Midfield": 40, "Centre-Back": 5},  # under a quarter elsewhere: one group only
            "new": {"Centre-Forward": 4},  # too few starts on record: his listed position
        }
    )
    listed = pd.Series(
        {
            "cb": "Centre-Back",
            "fb": "Right-Back",
            "dm": "Defensive Midfield",
            "new": "Left Winger",
            "kid": "Goalkeeper",
        }
    )
    w = group_weights(lu, listed, GROUP_OF)
    assert _weights(w, "cb") == pytest.approx({"centre-back": 0.6, "full-back": 0.4})
    assert _weights(w, "fb") == pytest.approx({"full-back": 1.0})  # the winger share (20%) is under the bar
    assert _weights(w, "dm") == pytest.approx({"defensive midfield": 1.0})
    assert _weights(w, "new") == {"winger": 1.0}
    assert _weights(w, "kid") == {"goalkeeper": 1.0}  # no starts at all
    assert set(w.loc[w.player_id.isin(["new", "kid"]), "source"]) == {"listed"}
    assert w.groupby("player_id").weight.sum().tolist() == pytest.approx([1.0] * 5)


def _market(players: list[tuple], lineups: pd.DataFrame) -> Market:
    """A Market with only what needs() reads: squads, listed positions, lineups, no appearances."""
    mk = Market.__new__(Market)
    mk.now = pd.Timestamp("2026-10-18")
    mk.squads = pd.DataFrame(
        players, columns=["club_id", "tm_player_id", "name", "sub_position", "market_value_eur", "birth_date"]
    ).assign(comp="GB1", tm_club_id=lambda d: d.club_id)
    mk.players = (
        mk.squads.set_index("tm_player_id")[["sub_position"]]
        .rename_axis("player_id")
        .assign(foot=None, height_in_cm=None, international_caps=None)
    )
    mk.squads = mk.squads.drop(columns="sub_position")
    mk.incoming, mk.played = {}, pd.Series(dtype=object)
    mk.comps = pd.DataFrame({"competition_id": ["GB1"], "sub_type": ["first_tier"]})
    mk.ap = pd.DataFrame(
        columns=["player_id", "date", "competition_id", "minutes_played", "goals", "assists"]
    ).astype({"date": "datetime64[ns]"})
    mk.use_positions(lineups)
    return mk


def _squad(club: str, extra: list[tuple] = ()) -> list[tuple]:
    """Two of everything at the listed positions, worth 10m each, aged 25."""
    rows = [
        (club, f"{club}-{g}-{i}", f"{club} {g} {i}", GROUPS[g][0], 10e6, "2001-01-01")
        for g in NEEDED
        for i in range(2)
    ]
    return rows + list(extra)


def test_needs_count_a_centre_back_who_starts_at_full_back_towards_full_back_depth():
    versatile = ("a", "a-x", "Versatile", "Centre-Back", 30e6, "2000-01-01")
    lineups = _lineups({"a-x": {"Centre-Back": 20, "Right-Back": 30}})
    mk = _market(_squad("a", [versatile]) + _squad("b") + _squad("c"), lineups)
    need = mk.needs("a").set_index("group")
    assert need.loc["full-back", "depth"] == pytest.approx(2.6)
    assert need.loc["centre-back", "depth"] == pytest.approx(2.4)
    assert need.loc["full-back", "players"] == 3
    # he is an option at both positions, so he is the best option at each (worth more than the rest)
    assert need.loc["full-back", "best_name"] == need.loc["centre-back", "best_name"] == "Versatile"


def test_comparison_squads_are_grouped_the_same_way():
    # the other clubs' best full-back is a centre-back who starts at right-back: a's full-backs look weak next to him
    lineups = _lineups({f"{c}-x": {"Centre-Back": 20, "Right-Back": 30} for c in "bc"})
    star = [(c, f"{c}-x", f"{c} star", "Centre-Back", 40e6, "2000-01-01") for c in "bc"]
    mk = _market(_squad("a") + _squad("b", star[:1]) + _squad("c", star[1:]), lineups)
    need = mk.needs("a").set_index("group")
    assert need.loc["full-back", "peer_best_value"] == 40e6
    assert need.loc["full-back", "quality_gap"] == pytest.approx(0.75)
    assert need.index[0] in ("full-back", "centre-back")


def test_needs_fall_back_to_the_listed_position_without_lineups():
    mk = _market(
        _squad("a", [("a", "a-x", "Versatile", "Centre-Back", 30e6, "2000-01-01")]) + _squad("b"),
        _lineups({}),
    )
    need = mk.needs("a").set_index("group")
    assert need.loc["centre-back", "depth"] == 3
    assert need.loc["full-back", "depth"] == 2
