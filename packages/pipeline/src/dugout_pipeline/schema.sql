-- dugout warehouse schema (DuckDB). Idempotent: safe to run on every connect.
-- Conventions: *_id columns are dugout ids (club slug, reep id for people when known);
-- per-source observations keep a `source` column so the Stat Auditor can cross-check them.

CREATE TABLE IF NOT EXISTS entity_ids (
    entity_type  VARCHAR NOT NULL,            -- club | player | manager | match
    dugout_id    VARCHAR NOT NULL,
    provider     VARCHAR NOT NULL,            -- reep provider name (api_football, opta, ...) or fpl / football_data_org
    namespace    VARCHAR NOT NULL,
    external_id  VARCHAR NOT NULL,
    reep_id      VARCHAR,
    PRIMARY KEY (entity_type, provider, namespace, external_id)
);

CREATE TABLE IF NOT EXISTS clubs (
    club_id      VARCHAR PRIMARY KEY,         -- slug, e.g. liverpool
    reep_id      VARCHAR,
    name         VARCHAR NOT NULL,
    short_name   VARCHAR,
    league       VARCHAR NOT NULL,
    season       VARCHAR NOT NULL,            -- 2026-27
    venue        VARCHAR,
    address      VARCHAR,
    lat          DOUBLE,
    lon          DOUBLE,
    updated_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    player_id    VARCHAR PRIMARY KEY,         -- reep id, else '<provider>:<id>'
    reep_id      VARCHAR,
    name         VARCHAR NOT NULL,
    web_name     VARCHAR,
    birth_date   DATE,
    nationality  VARCHAR,
    position     VARCHAR,                     -- GK | DEF | MID | FWD
    club_id      VARCHAR,
    updated_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS managers (
    manager_id   VARCHAR PRIMARY KEY,
    reep_id      VARCHAR,
    name         VARCHAR NOT NULL,
    birth_date   DATE,
    nationality  VARCHAR,
    club_id      VARCHAR,
    start_date   DATE,
    source       VARCHAR NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id     VARCHAR PRIMARY KEY,         -- <league>:<season>:<home>:<away> (stable across reschedules)
    league       VARCHAR NOT NULL,
    season       VARCHAR NOT NULL,
    gameweek     INTEGER,
    kickoff_utc  TIMESTAMPTZ,
    home_club_id VARCHAR NOT NULL,
    away_club_id VARCHAR NOT NULL,
    status       VARCHAR,                     -- scheduled | live | finished | postponed
    home_goals   INTEGER,
    away_goals   INTEGER,
    updated_at   TIMESTAMPTZ NOT NULL
);

-- One row per (match, source): what each provider reports. `matches` holds the agreed value.
CREATE TABLE IF NOT EXISTS match_observations (
    match_id     VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    external_id  VARCHAR,
    status       VARCHAR,
    home_goals   INTEGER,
    away_goals   INTEGER,
    home_xg      DOUBLE,
    away_xg      DOUBLE,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (match_id, source)
);

CREATE TABLE IF NOT EXISTS player_match_stats (
    player_id    VARCHAR NOT NULL,
    match_id     VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    club_id      VARCHAR,
    minutes      INTEGER,
    goals        INTEGER,
    assists      INTEGER,
    xg           DOUBLE,
    xa           DOUBLE,
    starts       INTEGER,
    yellow       INTEGER,
    red          INTEGER,
    -- FPL / Opta-derived extras (NULL where a season did not track them; defensive stats from 2025-26)
    saves        INTEGER,
    influence    DOUBLE,
    creativity   DOUBLE,
    threat       DOUBLE,
    bps          INTEGER,
    xgc          DOUBLE,
    tackles      INTEGER,
    recoveries   INTEGER,
    cbi          INTEGER,
    defensive_contribution INTEGER,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (player_id, match_id, source)
);

CREATE TABLE IF NOT EXISTS lineups (
    match_id     VARCHAR NOT NULL,
    club_id      VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    formation    VARCHAR,
    player_id    VARCHAR NOT NULL,
    starter      BOOLEAN NOT NULL,
    position     VARCHAR,
    grid         VARCHAR,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (match_id, club_id, source, player_id)
);

-- Open-data event streams (StatsBomb, Wyscout, PFF, Metrica...) in SPADL-like columns.
CREATE TABLE IF NOT EXISTS events (
    dataset      VARCHAR NOT NULL,            -- statsbomb | wyscout_public | pff_wc2022 | metrica | skillcorner
    game_id      VARCHAR NOT NULL,
    event_id     VARCHAR NOT NULL,
    period       INTEGER,
    time_seconds DOUBLE,
    team_id      VARCHAR,
    player_id    VARCHAR,
    type_name    VARCHAR,
    result_name  VARCHAR,
    bodypart     VARCHAR,
    start_x      DOUBLE,
    start_y      DOUBLE,
    end_x        DOUBLE,
    end_y        DOUBLE,
    xg           DOUBLE,                      -- provider shot xG where available (StatsBomb)
    PRIMARY KEY (dataset, game_id, event_id)
);

CREATE TABLE IF NOT EXISTS injuries (
    player_id       VARCHAR NOT NULL,
    club_id         VARCHAR,
    source          VARCHAR NOT NULL,
    snapshot_date   DATE NOT NULL,
    status          VARCHAR,                  -- available | doubtful | injured | suspended | unavailable | loan
    reason          VARCHAR,
    chance_next     INTEGER,                  -- 0-100, FPL chance_of_playing_next_round
    news            VARCHAR,
    news_added      TIMESTAMPTZ,
    expected_return DATE,
    fetched_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (player_id, source, snapshot_date)
);

CREATE TABLE IF NOT EXISTS transfers (
    player_id    VARCHAR NOT NULL,
    date         DATE NOT NULL,
    from_club    VARCHAR,
    to_club      VARCHAR,
    fee_eur      DOUBLE,
    fee_text     VARCHAR,
    kind         VARCHAR,                     -- permanent | loan | free | end_of_loan
    source       VARCHAR NOT NULL,
    PRIMARY KEY (player_id, date, source)
);

CREATE TABLE IF NOT EXISTS market_values (
    player_id    VARCHAR NOT NULL,
    date         DATE NOT NULL,
    value_eur    DOUBLE NOT NULL,
    source       VARCHAR NOT NULL,
    PRIMARY KEY (player_id, date, source)
);

CREATE TABLE IF NOT EXISTS contracts (
    player_id    VARCHAR NOT NULL,
    club_id      VARCHAR,
    expires      DATE,
    source       VARCHAR NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (player_id, source)
);

CREATE TABLE IF NOT EXISTS news_items (
    news_id      VARCHAR PRIMARY KEY,         -- sha256(canonical url)[:16]
    source       VARCHAR NOT NULL,
    outlet       VARCHAR,
    url          VARCHAR NOT NULL,
    title        VARCHAR,
    published_at TIMESTAMPTZ,
    summary      VARCHAR,
    body_text    VARCHAR,                     -- extracted locally for NLI; never republished
    club_ids     VARCHAR[],
    source_tier  INTEGER NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS standings (
    league       VARCHAR NOT NULL,
    season       VARCHAR NOT NULL,
    club_id      VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    position     INTEGER,
    played       INTEGER,
    won          INTEGER,
    drawn        INTEGER,
    lost         INTEGER,
    goals_for    INTEGER,
    goals_against INTEGER,
    points       INTEGER,
    form         VARCHAR,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (league, season, club_id, source)
);

CREATE TABLE IF NOT EXISTS elo (
    club_id      VARCHAR NOT NULL,
    date         DATE NOT NULL,
    elo          DOUBLE NOT NULL,
    source       VARCHAR NOT NULL,
    PRIMARY KEY (club_id, date, source)
);

CREATE TABLE IF NOT EXISTS historical_results (
    league       VARCHAR NOT NULL,
    season       VARCHAR NOT NULL,
    date         DATE NOT NULL,
    home         VARCHAR NOT NULL,            -- club slug where mappable, else raw name
    away         VARCHAR NOT NULL,
    home_goals   INTEGER,
    away_goals   INTEGER,
    odds_home    DOUBLE,                      -- closing odds (Pinnacle/market avg where available)
    odds_draw    DOUBLE,
    odds_away    DOUBLE,
    odds_source  VARCHAR,
    source       VARCHAR NOT NULL,
    PRIMARY KEY (league, date, home, away)
);

CREATE TABLE IF NOT EXISTS weather (
    match_id     VARCHAR PRIMARY KEY,
    temp_c       DOUBLE,
    precip_mm    DOUBLE,
    wind_kmh     DOUBLE,
    source       VARCHAR NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS set_piece_notes (
    club_id      VARCHAR NOT NULL,
    note         VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (club_id, note, source)
);

CREATE TABLE IF NOT EXISTS provenance (
    sha256       VARCHAR NOT NULL,            -- of the response body
    source       VARCHAR NOT NULL,
    url          VARCHAR NOT NULL,            -- redacted
    status       INTEGER NOT NULL,
    bytes        INTEGER NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source, url, fetched_at)
);

CREATE TABLE IF NOT EXISTS source_runs (
    run_id       VARCHAR NOT NULL,
    source       VARCHAR NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    ok           BOOLEAN,
    rows_written INTEGER,
    message      VARCHAR,
    PRIMARY KEY (run_id, source)
);
