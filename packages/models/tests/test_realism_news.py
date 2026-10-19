"""Realism's news signal: point-in-time press features from rumour links, on tiny synthetic tables."""

import duckdb
import numpy as np
import pandas as pd
from dugout_models import realism


def _links() -> pd.DataFrame:
    rows = [
        # player 1: linked with club 31 twice and club 631 once before 1 June 2020, and with 31 on the day itself
        ("r1", "2020-05-20", "1", "31"),
        ("r2", "2020-04-01", "1", "31"),
        ("r2", "2020-04-01", "1", "631"),  # the same report names a second club
        ("r3", "2019-09-01", "1", "631"),  # inside the year, outside the 90 days
        ("r4", "2020-06-01", "1", "31"),  # on the snapshot day: not known at its start
        ("r5", "2018-01-01", "1", "31"),  # more than a year before
        # player 2: never written about before the date
        ("r6", "2020-07-15", "2", "31"),
    ]
    df = pd.DataFrame(rows, columns=["rumour_id", "published_at", "tm_player_id", "tm_club_id"])
    df["published_at"] = pd.to_datetime(df.published_at)
    return df


def test_player_news_counts_only_reports_before_the_date():
    d = pd.Series(pd.Timestamp("2020-06-01"), index=[0, 1])
    out = realism.player_news(_links(), pd.Series([1, 2]), d)
    assert np.isclose(
        np.expm1(out.loc[0, "news_reports_90"]), 2
    )  # r1, r2 (r2 counted once despite two clubs)
    assert np.isclose(np.expm1(out.loc[0, "news_reports_365"]), 3)  # + r3
    assert out.loc[0, "news_clubs_90"] == 2 and out.loc[0, "news_clubs_365"] == 2
    assert (out.loc[1] == 0).all()  # r6 comes after the date


def test_pair_news_counts_this_club_and_its_share():
    idx = [10, 11, 12]
    out = realism.pair_news(
        _links(),
        pd.Series([1, 1, 2], index=idx),
        pd.Series([31, 418, 31], index=idx),
        pd.Series(pd.Timestamp("2020-06-01"), index=idx),
    )
    assert np.isclose(np.expm1(out.loc[10, "news_club_90"]), 2)
    assert out.loc[10, "news_club_share_90"] == 1.0  # both reports in the window name club 31
    assert np.isclose(out.loc[10, "news_club_share_365"], 2 / 3)  # r3 names only 631
    assert out.loc[11, "news_club_365"] == 0 and out.loc[11, "news_club_share_365"] == 0
    assert (out.loc[12] == 0).all()


def test_with_news_uses_1_june_of_each_year_and_keeps_rows():
    snap = pd.DataFrame({"player_id": [1, 1], "year": [2020, 2021], "moved": [False, True]})
    pairs = pd.DataFrame(
        {"player_id": [1, 1], "club": [31, 631], "year": [2020, 2020], "label": [True, False]}
    )
    s, p = realism.with_news(snap, pairs, _links())
    assert len(s) == 2 and len(p) == 2
    assert np.isclose(np.expm1(s.loc[0, "news_reports_365"]), 3)
    # by 1 June 2021 only r4 (2020-06-01) and r6 (2020-07-15) are within the year
    assert np.isclose(np.expm1(s.loc[1, "news_reports_365"]), 1)
    assert set(realism.NEWS_MOBILITY_ALL) <= set(s.columns)
    assert set(realism.NEWS_DESTINATION_ALL) <= set(p.columns)


def test_no_archive_gives_zero_news_features():
    con = duckdb.connect()
    empty = realism.load_links(con)  # no rumour_links table yet
    assert empty.empty and list(empty.columns) == ["rumour_id", "published_at", "tm_player_id", "tm_club_id"]
    assert realism.load_links(None).empty
    out = realism.player_news(empty, pd.Series([1]), pd.Series([pd.Timestamp("2020-06-01")]))
    assert (out == 0).all(axis=None)
    pn = realism.pair_news(empty, pd.Series([1]), pd.Series([31]), pd.Series([pd.Timestamp("2020-06-01")]))
    assert (pn == 0).all(axis=None)


def test_load_links_reads_rumour_links_as_naive_utc():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE rumour_links (rumour_id VARCHAR, published_at TIMESTAMPTZ, tm_player_id VARCHAR, "
        "tm_club_id VARCHAR)"
    )
    con.execute("INSERT INTO rumour_links VALUES ('r1', '2020-05-20 23:30:00+00', '1', '31')")
    df = realism.load_links(con)
    assert df.published_at.iloc[0] == pd.Timestamp("2020-05-20 23:30:00")
    assert df.tm_player_id.iloc[0] == "1"


def test_shipped_feature_lists_extend_the_base_models():
    assert realism.MOBILITY_SHIPPED[: len(realism.MOBILITY)] == realism.MOBILITY
    assert realism.DESTINATION_SHIPPED[: len(realism.DESTINATION)] == realism.DESTINATION
    assert set(realism.NEWS_MOBILITY) <= set(realism.NEWS_MOBILITY_ALL)
    assert set(realism.NEWS_DESTINATION) <= set(realism.NEWS_DESTINATION_ALL)
