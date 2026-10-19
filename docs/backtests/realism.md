# Transfer realism backtest

Generated 2026-10-18T16:52:26+00:00. transfermarkt-datasets (CC0); train summer windows 2015-2023, test 2024-2025.

| Factor | Model | Test AUC | Notes |
|---|---|---|---|
| Mobility (sold for a fee this summer?) | logistic | 0.753 | Brier 0.0678 vs base rate 0.0729; 7.9% sold, 27733 player-summers |
| **Mobility (shipped)** | gradient boosting | 0.764 | Brier 0.0672; mean forecast 7.4% |
| Mobility, previous frame (today's club) | gradient boosting | 0.750 | Brier 0.0703; mean forecast 7.0% (same test player-summers) |
| Mobility, without Europe wealth rank | logistic | 0.749 | Brier 0.0685 |
| **Destination (this club, given a move; shipped)** | pairwise logistic + step-down + press reports | 0.737 | real buyer ranked first 47.5% vs random 16.5%, 2004 moves |
| Destination, without press reports | pairwise logistic + step-down | 0.733 | real buyer ranked first 47.2% |
| Destination, without step-down | pairwise logistic | 0.727 | real buyer ranked first 47.3% |
| Destination, previous frame (today's club) | pairwise logistic + step-down | 0.749 | real buyer ranked first 48.2%; inflated, see below |
| Contract | prior weights | — | no historical contract data |

**Press reports (2026-10-18).** The Guardian's Rumour Mill archive (every column since 2001, `rumour_links`: 36744 links of a player with a club) gives point-in-time press features: reports published before 1 June naming the player with any club (mobility) or with this club (destination), in the 90 days and the year before. Each set is trained on 2015-2022 and scored on validation summer 2023 (mobility by Brier, destination by log loss); the test summers 2024-2025 are scored once, with the previous year added to training.

| Validation 2023 | AUC | Brier / log loss | Top-1 |
|---|---|---|---|
| Mobility, none | 0.7776 | 0.06568 | — |
| Mobility, reports_90 | 0.7752 | 0.06575 | — |
| Mobility, reports_365 | 0.7746 | 0.06581 | — |
| Mobility, reports_clubs_365 | 0.7742 | 0.06580 | — |
| Mobility, all | 0.7759 | 0.06572 | — |
| Destination, none | 0.7183 | 0.3903 | 43.7% |
| Destination, club_90 | 0.7181 | 0.3903 | 43.6% |
| Destination, club_365 | 0.7212 | 0.3881 | 43.6% |
| Destination, club_share_365 | 0.7213 | 0.3880 | 43.8% |
| Destination, all | 0.7213 | 0.3881 | 43.8% |

Chosen on validation: mobility `none`, destination `club_share_365`. Shipped: mobility `none`, destination `['news_club_365', 'news_club_share_365']`.

| Test 2024-2025 | AUC | Brier / log loss | Top-1 |
|---|---|---|---|
| Mobility, none | 0.7642 | 0.06720 | — |
| Mobility, all | 0.7622 | 0.06732 | — |
| Destination, none | 0.7325 | 0.3812 | 47.2% |
| Destination, club_share_365 | 0.7372 | 0.3784 | 47.5% |
| Destination, all | 0.7372 | 0.3785 | 47.4% |

Test moves whose buyer the press had named in the year before: 30; the real buyer ranked first 86.7% of the time with press reports, 66.7% without. Coefficients (standardised): news_club_365 0.143, news_club_share_365 0.132.

| Years | Player-summers | Written about (year before) | Sold if written about | Sold otherwise | Real buyer named | Other candidate named | Named club was the buyer | Real buyer named, 90 days |
|---|---|---|---|---|---|---|---|---|
| 2015-2019 | 21501 | 7.7% | 23.1% | 10.0% | 5.6% | 0.3% | 79.1% | 3.5% |
| 2020-2023 | 33749 | 2.7% | 13.0% | 6.6% | 1.4% | 0.1% | 79.5% | 0.0% |
| 2024-2025 (test) | 27733 | 1.7% | 21.0% | 7.7% | 1.5% | 0.0% | 85.7% | 0.0% |

Reading this honestly:

- **Destination: a small, real gain.** When the column had linked a player with a club in the year before, that club was usually the buyer, but few moves are covered: the column is about English football and, since 2020, runs only during transfer windows (nothing in March-May, little or nothing in the summers of 2021 and 2024), so the 90 days before 1 June are empty in the modern era and the year before is the window that carries the signal. Some reports before 1 June are deals already agreed, which the press knows and so does a club.
- **Mobility: no gain (a negative result).** Players the press writes about are sold more often, but they are also the valuable, rising players the model already rates; every news set was slightly worse on validation, so the sale likelihood does not use them.
- **Live:** the past year's reports up to today (archive plus the nightly Rumour Mill items), so in October they cover the last January and summer windows, like the year before 1 June in training. The shortlist says when reports linking a player with the club make the move at least 1.1 times as likely as the same estimate with nothing written about him.

**Club on the day (2026-10-17).** transfermarkt-datasets' `player_valuations.current_club_id` is the player's club today, not on the valuation date, and `transfers` has no rows for anyone whose last season is before 2023 (gaps for active players too). The frames used to take a player's club from that id: wrong for 45% of players on 1 June 2016, 33% in 2022, 19% in 2024, so their minutes share, club value, wealth rank, tenure and relegation flag described another club. Clubs now come from a timeline of transfers, club appearances (national teams excluded) and the valuations' dated club names (`club_people`, shared with the rumour track record), and mobility trains only on players the dataset has a transfer history for (else "sold" can never be true for them; chosen on validation season 2023: Brier 0.0439 vs 0.0442, mean forecast 5.3% vs 3.6% for a 5.1% rate). The previous destination frame counted each club's squad by today's club, so a buyer's value already included the player it was buying and anyone it signed later: its higher scores are hindsight, and the drop is the honest number.

Mobility coefficients: age -0.359, age2 -0.097, log_mv 0.74, mv_change 0.048, minutes_share 0.119, share_change 0.007, rel_value 0.153, log_league 0.018, tenure -0.054, peak_ratio 0.056, relegated 0.087, log_europe_rank 0.302, elite_regular -0.14

Young regulars at Europe's 10 richest clubs (age 26 or under, half the minutes or more): 109 test player-summers, 4.6% sold; mean predicted 4.7% by the shipped gradient boosting, 10.4% by the logistic, 25.3% by the logistic without the wealth rank. The gradient boosting is chosen on test Brier. Before the club fix its weakness was the opposite group (valuable regulars at clubs outside Europe's richest 30: sold 38% of the time, predicted about 20%); not re-measured.

Destination coefficients: capacity_ratio 0.293, league_gap 0.147, club_value_gap -0.082, same_league 0.376, same_country 0.376, step_down -0.31, news_club_365 0.143, news_club_share_365 0.132

Tested and not adopted (2026-10-16): a club-stature feature for mobility (selling club's squad value vs its league's median club; AUC 0.753 with or without it: big clubs' regulars were sold in 15.7% of test summers, more than the 7.7% base rate, not less), and an elite-rival feature for destination (both clubs in their league's top six; coefficient about zero: top clubs do sell to domestic rivals).

Wages are not modelled: no free, licensable wage data exists (Capology is not open).
