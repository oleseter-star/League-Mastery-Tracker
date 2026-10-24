# Match history and composition statistics

Status (2026-10-24): implemented and in use on this branch, not yet merged
to `main`. Ole's four accounts are fully imported (951 ranked and Clash
games, back to mid-2025, all histories complete). The 22 games where
friends played on KampensHete were assigned in Match review (16 to Per,
6 to Iver).

What exists:

* **Matches** in the navigation opens **Match statistics**: filters for
  Person, ranked mode, patch range, role, and minimum games; an overview;
  and a champions table. Each champion opens a detail page with win rates
  with and against champions grouped by role (lane opponent marked), with
  tracked Persons, and per patch.
* **Persons** on the statistics page: each person's record, or, with one
  person selected, win rates with each tracked teammate. A teammate opens
  a "with" page (`/matches/with/<id>`): the record together, both
  persons' roles, and both champion pools.
* **Match review**: games where two accounts of one Person were in the
  same match. Choose who played each account, ignore a game or all games,
  and restore ignored games. Post-game style cards with champion icons,
  position icons, K/D/A, CS, and damage.
* Only Riot's ranked match type and Summoner's Rift Clash are imported:
  Ranked Solo/Duo (420), Ranked Flex (440), Ranked 5s (710), Clash (700).
* Positions are shown as Top, Jungle, Mid, Bot, Support.

Next steps:

1. Import the other 19 tracked accounts (friends) for their own history.
   The import runs on the PC with the key read from the clipboard (pasting
   into hidden prompts fails in VS Code's terminal); see Command-line use.
2. Open a pull request for this branch so CI runs the new code.
3. Later: a recent-games view with the match cards, team-style statistics
   (needs champion classes), and casual modes as separate views.

Known quirk: on Python 3.13+ the test suite prints ResourceWarnings about
unclosed in-memory SQLite connections (existing tests too); CI runs 3.12.

Implementation:

* tables: `Match`, `MatchParticipant`, `MatchImportState` in
  `application/database/models.py`;
* Riot calls: `RiotService.get_match_ids` and `get_match`, rate-limited by
  `application/services/riot_rate_limiter.py`;
* import: `application/services/match_import_service.py`;
* statistics: `application/services/match_statistics_service.py`;
* queue, patch, and position names: `application/services/match_catalog.py`;
* who played a game, ignore and review: `application/services/match_assignment_service.py`;
* columns added to existing match tables at startup:
  `application/services/match_schema_service.py`;
* pages: `application/routes/match_statistics.py`,
  `application/routes/match_review.py`, templates `match_statistics.html`,
  `match_champion.html`, `match_with_person.html`, `match_review.html`,
  `_match_components.html`;
* command line: `match_history.py`.

## Command-line use

Close the application before importing; statistics can run while it is
open. The import uses the `RIOT_API_KEY` environment variable when set,
otherwise the API key saved in Settings, or `--ask-key` for a key entered
for one run.

```powershell
python match_history.py import --ask-key
python match_history.py import --account "Main#EUW" --max-games 200
python match_history.py stats summary
python match_history.py stats persons --mode solo
python match_history.py stats person-champions --person Ole --mode solo --mode flex
python match_history.py stats positions --person Ole --min-games 5
python match_history.py stats allies --person Ole --champion Lux --patch 26.12-26.18
python match_history.py stats lanes --person Ole --champion Lux --position mid
python match_history.py stats patches --person Ole --champion Lux
python match_history.py stats pairs --mode clash
```

Every table shows games, wins and losses, win rate, and a score: the
lower bound of the 95% confidence interval for the win rate, used for
sorting. These options narrow the games counted:

* `--mode solo`, `flex`, `5s`, or `clash`, repeated to combine;
* `--patch 26.18`, a list (`26.17,26.18`), or a range (`26.12-26.18`),
  repeated to combine; `16.18` works as well as `26.18`;
* `--min-games` (default 3), `--since`, and `--until`.

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
  first, at most 100 per call, filterable by queue, by type (for example
  `ranked`, which covers every ranked queue), and by time.
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
* **Patches.** Each game records its game version, for example
  `16.18.712.3456`. Game versions are 15.x for 2025 and 16.x for 2026, while
  Riot announces the same patches as 25.x and 26.x (the first 2025 patches
  as 25.S1.1 and so on). Patches are stored as `16.18` and shown as `26.18`.
* **Scope.** Only ranked games and Summoner's Rift Clash are imported:
  Ranked Solo/Duo (420), Ranked Flex (440), Ranked 5s (weekend premade
  ranked, 710), and Clash (700). Normals, ARAM, League
  Classic, and other modes are not imported; casual modes may follow later.

## Data model

Three additive tables; existing application tables are not changed.
Columns added to the match tables after they first shipped on this branch
(`played_by_person_id`, `ignored`) are added at startup by
`MatchSchemaService`, because `db.create_all()` never alters existing
tables.

`matches`: one row per game, shared by every tracked account in it.

| Column | Notes |
| --- | --- |
| `riot_match_id` | Unique, for example `EUW1_7212345678`. Not encrypted, so it deduplicates games across accounts and API keys. |
| `platform_id`, `queue_id`, `game_mode`, `map_id`, `game_version` | Filters for mode. |
| `patch` | `major.minor` of `game_version`, for example `16.18`; indexed for patch filters. |
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
2. Page through match IDs newest first, for Riot's `ranked` type and for the
   Clash queue.
3. Skip IDs already linked to this account. Stop at the first page with only
   known IDs once `history_complete` is set; before that, keep paging to
   backfill older games.
4. Fetch each unknown game once. A game already stored through another
   account is not fetched again; the existing participant row is linked by
   PUUID, or by `participant_id` after one fresh fetch when the PUUID came
   from a different key.
5. Commit after each game, so an interrupted import keeps its progress.

Listing by type rather than by queue ID imports every ranked queue,
including queues the app does not name yet. That is how Ranked 5s was
found: the probe lists all ranked games, removes the Solo/Duo and Flex
games, and reads the queue ID of a few of the rest. It reported 710, which
now has the mode name `5s` in `match_catalog.py`.

The import accepts a budget (maximum games per run) and a progress callback.
That supports both a command-line import and, later, a background import
with a progress bar in the application.

Requests share one rate limiter set below the development-key limits, and a
429 response waits for `Retry-After` before retrying.

## Statistics

All statistics count games, wins, and win rate for the tracked participant.
Filters: Persons or Riot accounts, modes (one or several), patches (one,
several, or a range), date range, and position.

| View | Grouping |
| --- | --- |
| Person overview | Person |
| Champion overview | Champion, across the selected Persons |
| Person on champion | Person, champion |
| Person on champion in position | Person, champion, position |
| With ally champion | Selected champion (optional), ally champion |
| Against enemy champion | Selected champion (optional), enemy champion |
| With tracked Persons | Pair of Persons on the same team |
| Per patch | Patch, newest first, for following a champion or Person over time |

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

## User interface

Chosen: a **Match statistics** page with filters and a champions table,
and a **champion detail** page with results with and against champions by
role, with tracked Persons, and per patch. **Match review** handles games
where an account was played by someone other than its owner. A section on
the Person page was considered and not built.

The import still runs from the command line. An in-app import needs a
background task with progress, because a first import can take far longer
than a browser request should.

## Phases

1. Probe real accounts (`probe_match_history.py`). Done.
2. Backend: tables, Riot match calls with rate limiting, the import service,
   statistics service, and a command-line tool. Done; Ole's accounts are
   imported.
3. Application: statistics, champion detail, and Match review pages are
   done; an in-app background import with progress is not.
4. Champion classes and team-style views.
5. Optional: recent-games view with match cards, JSON export of match data,
   casual modes, League Classic view. Patch filters are done.

## Open questions

* Should the import move into the application, with a background task?
* Should casual modes (normals, ARAM) be added later as separate views?
* Should games where no tracked account remains (after deleting a Person)
  be kept or removed?
* Is a personal API key worth requesting, given it changes PUUIDs once?
