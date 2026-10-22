# Match history and composition statistics

Status: design and backend in progress. No user interface yet. The probe
(`probe_match_history.py`) has not been run against real accounts, so the
volume assumptions below are still estimates.

## Goal

Use historical games to show what works, for one Riot account, for a Person
across all of their accounts, and for groups of friends:

* a Person's results overall, per champion, and per champion in a position;
* a champion's results across all tracked Persons;
* results with a given ally champion and against a given enemy champion;
* results when two tracked Persons play on the same team;
* later, results by team style (number of tanks, damage profile).

## What Riot provides

Match-V5 gives two calls:

* `GET /lol/match/v5/matches/by-puuid/{puuid}/ids` returns match IDs newest
  first, at most 100 per call, filterable by queue and time.
* `GET /lol/match/v5/matches/{matchId}` returns one game: queue, creation
  time, duration, game version, and all ten participants with `puuid`,
  Riot ID, `championId`, `teamId`, `teamPosition`, `win`, KDA, and more.

Constraints that shape the design:

* **Rate limits.** A development key allows 20 requests per second and 100
  per two minutes. Every game costs one request, so a first import of 1,000
  games takes about 20 minutes. Later imports only fetch new games.
* **Retention.** Riot keeps match history for a limited time (roughly the
  last two years; the probe will show the real depth). Games that age out
  can only be analyzed if they were stored locally first, so local match
  data becomes more valuable over time and must be covered by backups.
* **PUUIDs depend on the API key project.** Riot encrypts PUUIDs per API key
  project. Development keys from the same Riot developer account keep the
  same values, but a personal or production key will not. Stored PUUIDs,
  including the ones inside stored matches, must therefore not be the only
  link between a game and a tracked Riot account. The probe reports whether
  stored PUUIDs still match the current key.
* **Positions.** `teamPosition` is set in Summoner's Rift queues and empty in
  ARAM, so position-based views only use Summoner's Rift games.
* **League Classic.** Classic games are outside the 2.0 scope, matching the
  Champion Mastery exclusion. They are not imported.

## Data model

Three additive tables. Existing tables are not changed.

`matches`: one row per game, shared by every tracked account in it.

| Column | Notes |
| --- | --- |
| `riot_match_id` | Unique, for example `EUW1_7212345678`. Not encrypted, so it deduplicates games across accounts and API keys. |
| `platform_id`, `queue_id`, `game_mode`, `map_id`, `game_version` | Filters for queue and patch. |
| `game_creation`, `game_duration_seconds` | Date filters and remakes. |
| `raw_data` | The full Match-V5 document, zlib-compressed (about 10 KB per game). Keeps items, runes, and damage available for later features after Riot no longer serves the game. |

`match_participants`: ten rows per game.

| Column | Notes |
| --- | --- |
| `match_id` | Parent game. |
| `participant_id` | Riot's 1-10 position in the game, stable for every API key. |
| `puuid` | As seen by the key that imported the game. |
| `riot_id_game_name`, `riot_id_tagline` | Readable names at the time of the game. |
| `riot_champion_id`, `team_id`, `team_position`, `win` | The fields every statistic needs. |
| `kills`, `deaths`, `assists` | Cheap to keep, useful later. |
| `riot_account_id` | Set when the participant is a tracked Riot account. This is the link statistics use, so a later API key change does not break existing games. |

`match_import_states`: one row per tracked Riot account with
`last_import_at` and `history_complete`.

Deleting a Person or Riot account keeps the games but clears
`riot_account_id`, so friends' statistics from shared games survive. The
import state is deleted with its Riot account.

### Compatibility

The schema version stays 1. JSON export documents record the schema version
and import rejects any other version, so a version bump would make every
existing 2.0 export unimportable. Additive tables avoid that:

* startup already runs `db.create_all()`, which creates missing tables in
  new and existing databases;
* a 2.0 build that opens a newer database ignores the extra tables;
* restoring a 2.0 backup gets the tables created at the next startup.

Rule for later work: tables that older versions can safely ignore do not
change the schema version; any change to existing tables or to the meaning
of stored data needs a migration and a version bump, and JSON import then has
to accept the older document version explicitly.

Backups copy the whole SQLite file, so match data is included. JSON export
stays limited to Persons, Riot accounts, Champions, and Champion Mastery for
now.

## Import

For each Riot account, on request only (no automatic network calls):

1. Re-resolve the Riot ID to a PUUID for the current key when the stored
   PUUID is rejected.
2. Page through match IDs for the imported queues, newest first.
3. Skip IDs already linked to this account. Stop at the first page with only
   known IDs once `history_complete` is set; before that, keep paging to
   backfill older games.
4. Fetch each unknown game once. A game already stored through another
   account is not fetched again; the existing participant row is linked by
   PUUID, or by `participant_id` after one fresh fetch when the PUUID came
   from a different key.
5. Commit after each game, so an interrupted import keeps its progress.

Imported queues by default: Ranked Solo/Duo (420), Ranked Flex (440), Normal
Draft (400), Normal Blind (430), Quickplay (490), and ARAM (450). The probe
will show whether ARAM is worth its request cost.

The import accepts a budget (maximum games per run) and a progress callback.
That supports both a command-line import and, later, a background import
with a progress bar in the application.

Requests share one rate limiter set below the development-key limits, and a
429 response waits for `Retry-After` before retrying.

## Statistics

All statistics count games, wins, and win rate for the tracked participant.
Filters: Persons or Riot accounts, queues, date range, and position.

| View | Grouping |
| --- | --- |
| Person overview | Person |
| Champion overview | Champion, across the selected Persons |
| Person on champion | Person, champion |
| Person on champion in position | Person, champion, position |
| With ally champion | Selected champion (optional), ally champion |
| Against enemy champion | Selected champion (optional), enemy champion |
| With tracked Persons | Pair of Persons on the same team |

A Person can only appear once per game, so counting participant rows linked
to any of a Person's accounts counts distinct games.

Small samples are the main risk: an exact five-champion team almost never
repeats, and "3-0 with Zac" is noise. Every result shows its game count,
results below a minimum (default 5 games) are hidden or marked, and sorting
uses the lower bound of the 95% Wilson interval, so 30-15 ranks above 3-0.

## Team style (later)

Team-style views need champion classes. Data Dragon provides them as
`tags` (for example `["Mage", "Support"]`), but the bundled dataset only
stores ID, name, and image. Adding classes means a bundled dataset format
change (manifest, builder, validation, merge) and a new additive table for
champion classes. Once that exists, useful groupings include number of tanks
or fighters per team, ranged versus melee, and an approximate damage profile.

## User interface options

Not decided. Options to choose from:

* **Statistics page** with filters (Persons, queues, dates) and tabs for the
  views above.
* **Person page section** showing that Person's champions and positions with
  win rates next to the existing Mastery.
* **Champion detail** showing who plays it best and its best allies and
  hardest enemies.

The import needs a background task with progress, because a first import
can take far longer than a browser request should.

## Phases

1. Probe real accounts (`probe_match_history.py`). Done; waiting for a run.
2. Backend: tables, Riot match calls with rate limiting, the import service, and
   statistics service, plus a command-line tool to import and print
   statistics. In progress on this branch.
3. Application: background import with progress and the chosen pages.
4. Champion classes and team-style views.
5. Optional: patch filter, JSON export of match data, League Classic view.

## Open questions

* Which queues should be imported and shown by default?
* Should ARAM be imported, given its request cost and lack of positions?
* Which interface option, or combination, fits best?
* Should games where no tracked account remains (after deleting a Person)
  be kept or removed?
* Is a personal API key worth requesting, given it changes PUUIDs once?
