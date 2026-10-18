"""Candidate pools in the market model (the Championship): pool players and today's club leagues, on tiny tables."""

import pandas as pd
from dugout_models.market import Market


def _market() -> Market:
    mk = object.__new__(Market)
    mk.now = pd.Timestamp("2026-10-19")
    mk.pools = {"GB2"}
    mk.squads = pd.DataFrame(
        {
            "tm_player_id": ["1", "2", "3"],
            "name": ["Known Winger", "New Keeper", "Liverpool Player"],
            "tm_club_id": ["379", "1112", "31"],
            "club_id": ["west-ham-united", "wrexham", "liverpool"],
            "club_name": ["West Ham United", "Wrexham AFC", None],
            "birth_date": ["1996-12-20", "2004-01-01", "1999-01-01"],
            "position": ["Right Winger", "Goalkeeper", None],
            "contract_expires": ["2030-06-30", "2028-06-30", "2027-06-30"],
            "comp": ["GB2", "GB2", "GB1"],
        }
    )
    players = pd.DataFrame(
        {
            "player_id": ["1", "3"],
            "name": ["Known Winger", "Liverpool Player"],
            "date_of_birth": ["1996-12-20 00:00:00", "1999-01-01 00:00:00"],
            "sub_position": ["Right Winger", "Centre-Back"],
            "position": ["Attack", "Defender"],
            "current_club_id": [379, 31],
            "current_club_domestic_competition_id": ["GB1", "GB1"],
            "contract_expiration_date": ["2030-06-30", "2027-06-30"],
            "last_season": [2025, 2025],
        }
    )
    clubs = pd.DataFrame(
        {
            "club_id": [379, 31],
            "name": ["West Ham United", "Liverpool FC"],
            "domestic_competition_id": ["GB1", "GB1"],
        }
    )
    mk.t = {"players": players, "clubs": clubs}
    mk.players = players.assign(player_id=lambda d: d.player_id.astype(str)).set_index("player_id")
    return mk


def test_pool_players_join_the_players_table():
    mk = _market()
    mk._with_pool_players()
    new = mk.players.loc["2"]
    assert (new["name"], new.sub_position, new.position) == ("New Keeper", "Goalkeeper", "Goalkeeper")
    assert new.current_club_id == "1112" and new.current_club_domestic_competition_id == "GB2"
    assert new.date_of_birth == "2004-01-01 00:00:00"  # the dataset's format: one parse for the whole column
    known = mk.players.loc["1"]  # relegated with West Ham: today's league, not the dataset's
    assert known.current_club_domestic_competition_id == "GB2" and known.last_season == 2026
    assert mk.players.loc["3"].current_club_domestic_competition_id == "GB1"  # league squads untouched
    assert "2" in set(mk.t["players"].player_id)  # the snapshots (potential, realism) see him too


def test_live_clubs_use_todays_league_and_add_missing_clubs():
    mk = _market()
    clubs = mk._live_clubs().set_index("club_id")
    assert clubs.loc["379"].domestic_competition_id == "GB2"  # relegated
    assert (clubs.loc["1112"]["name"], clubs.loc["1112"].domestic_competition_id) == ("Wrexham AFC", "GB2")
    assert clubs.loc["31"].domestic_competition_id == "GB1"
    assert mk.t["clubs"].domestic_competition_id.tolist() == ["GB1", "GB1"]  # training tables unchanged


def test_pool_clubs_get_no_lists_of_their_own():
    assert _market().buying_clubs() == ["liverpool"]
