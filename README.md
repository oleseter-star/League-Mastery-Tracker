# League Mastery Tracker

League Mastery Tracker is a local application for organizing Persons, their Riot accounts, and League of Legends Champion Mastery. It runs a Flask server on the local computer and opens the interface in the default browser. The packaged Windows application is designed for ordinary users and does not require a separate Python or database installation.

## Product identity and status

The canonical product identity is defined in `application/config/__init__.py`:

```text
Product name: League Mastery Tracker
Release name: League Mastery Tracker 2.0
Application version: 2.0.0
Windows executable: LeagueMasteryTracker.exe
```

League Mastery Tracker 2.0 passed its native Windows build and acceptance (Steps 10.16–10.17) on 2026-09-29. The repository contains the complete core workflows described below; the final release steps are tracked in [docs/STEP10_WINDOWS_ACCEPTANCE_HANDOFF.md](docs/STEP10_WINDOWS_ACCEPTANCE_HANDOFF.md).

The verified Step 10.5 historical checkpoint was:

```text
757 executed
744 reconciled passes
0 failures
0 errors
13 intentional skips
```

The current Step 10.15 verification is:

```text
783 executed
770 reconciled passes
0 failures
0 errors
13 intentional skips
```

It consists of one restricted full-suite run, two sandbox-only local-loopback socket permission errors, and one focused elevated rerun of the 16-test application-server module; the reconciled totals replace only those two errors. See the tracked [Step10-test-results.txt](Step10-test-results.txt) artifact for the complete evidence and skip categories. The native Windows build and acceptance evidence is recorded in the same artifact and in the Windows acceptance handoff.

## Features

- Create a Person and attach one or more Riot accounts.
- Synchronize Champion Mastery for accounts that are stale or for all accounts on demand.
- Show Mastery points, Champion names, and local Champion images on the Dashboard.
- Record when each Riot account was Last synchronized.
- Keep Champion reference data available through a Bundled dataset and a Local cache.
- Preserve an Unknown champion and allow Manual metadata when reference data is incomplete; the Missing metadata page identifies records that need attention.
- Manage the Riot API key, Portable data, Database backup, Database restore, and Controlled shutdown from Settings.
- Export and import the portable domain data separately from full SQLite backups.

Deleting a Person also deletes that Person's locally stored Riot accounts and Champion Mastery records. Treat deletion, JSON import, and Database restore as destructive workflows and create or verify a suitable backup first.

## Reference data and offline behavior

The repository includes local Champion reference data and images under:

```text
application/bundled_reference_data/data_dragon/
├── manifest.json
├── champions.json
└── champion_icons/
```

The checked-in manifest currently identifies Data Dragon version `16.14.1`, locale `en_US`, and 173 Champions. This snapshot lets a new data directory display Champion names and images without a Riot API key, a Data Dragon request, or a manual update.

At startup, the application validates local sources and selects them in this order:

1. A valid Local cache when its Data Dragon version is newer than the Bundled dataset.
2. The valid Bundled dataset.
3. Existing SQLite records as a Database-only fallback when neither file source is usable.

Reference data is merged without deleting existing Champions or their Champion Mastery relationships. Manual metadata is preserved, and an Unknown champion can receive metadata later when its Riot Champion ID appears in a valid source.

Normal startup and navigation are offline operations. They do not contact Riot or Data Dragon, and a manual Data Dragon update is not required for first startup. Refresh a browser page to reload existing local information; this does not synchronize or update data. Network access occurs only through explicit actions that need it, including adding a Riot account, synchronizing Champion Mastery, and updating reference data.

### Manual Data Dragon updates

The Reference data update control on the Dashboard explicitly checks Data Dragon. The application compares the active Data Dragon version with the latest version and downloads only through that manual workflow. In status terms, a newer remote version means Update available; otherwise there is No update available. A forced update may reinstall the current remote version, but an older remote version does not replace newer local data.

A successful update downloads Champion data and images, builds and validates a complete temporary dataset, merges its metadata, and installs the Local cache atomically. A failed update leaves the previously usable bundle, cache, database records, and Champion Mastery available.

Developers can intentionally rebuild the checked-in Bundled dataset with:

```powershell
python build_champion_reference_bundle.py
```

That command contacts Data Dragon and rewrites the tracked resources under `application\bundled_reference_data\data_dragon\`; it is not part of normal application startup.

## Riot API synchronization

Adding a Riot account resolves the Riot ID through Riot's API and stores its PUUID, but it does not automatically synchronize Champion Mastery. The Dashboard provides two explicit POST actions:

- Synchronize accounts that have never been synchronized or whose Last synchronized time is at least 24 hours old.
- Synchronize every stored Riot account, regardless of age.

Champion Mastery from the League Classic game mode, which Riot reports as 60000 plus the regular champion ID, is not stored; synchronization also removes Classic records saved by earlier versions.

Synchronization updates local data account by account. A failure for one account does not stop the remaining accounts, and existing local records remain available when the network or Riot API is unavailable. Normal offline browsing does not initiate synchronization.

## Run from source

Python and the dependencies pinned in `requirements.txt` are required for development. From the repository root, create and activate a virtual environment, install the tracked requirements, and run the Python entry point:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

On non-Windows systems, use the activation command appropriate for the shell. The application writes development data to the repository-local `data/` directory unless the data-directory override described below is set.

## Tests

With the project environment active, run the unittest suite with:

```powershell
python -m unittest discover -s tests -v
```

Platform-specific or optional-environment skips should be reviewed in context; they are not test failures. Later focused additions can change the current number of discovered tests. Windows build and acceptance results are recorded in [Step10-test-results.txt](Step10-test-results.txt); this section describes only the automated suite.

## Windows builds

Build dependencies are pinned separately from runtime dependencies:

```powershell
python -m pip install -r requirements-build.txt
```

The repository tracks two PyInstaller specifications:

```text
LeagueMasteryTracker.spec
LeagueMasteryTracker-onefile.spec
```

Build either specification from the repository root:

```powershell
python -m PyInstaller --clean --noconfirm LeagueMasteryTracker.spec
python -m PyInstaller --clean --noconfirm LeagueMasteryTracker-onefile.spec
```

Both current specifications use PyInstaller's single-executable architecture and intentionally have no `COLLECT` phase. They both write the canonical executable to:

```text
dist\LeagueMasteryTracker.exe
```

The standard and explicitly named one-file specifications are retained as separate build targets, but the current repository does not define a separate one-folder artifact. Running both commands in sequence targets the same output filename.

Both specifications include Flask templates, static assets, the Bundled dataset, local Champion images, and required `pystray` modules. `pyinstaller_build_metadata.py` derives the executable name and Windows version resource from the canonical product configuration. The packaged executable uses `console=False`. `packaging/windows/record_windows_build.ps1` builds from a clean tree and verifies the console-free subsystem and version metadata; the application icon is confirmed in File Explorer. Do not treat source-level packaging tests as a substitute for a native Windows build.

## Application data

Mutable user data is separate from the packaged application. On Windows, the default Data directory is:

```text
%LOCALAPPDATA%\LeagueMasteryTracker\
```

`LEAGUE_MASTERY_TRACKER_DATA_DIR` overrides that location. When `LOCALAPPDATA` is unavailable on Windows, the application falls back to the current profile's `AppData\Local\LeagueMasteryTracker` directory. Source runs on non-Windows systems default to the repository-local `data/` directory.

The application creates these locations at runtime:

```text
database\league_mastery_tracker.db
configuration\flask_secret_key.bin
configuration\riot_api_key.dpapi
reference\
backups\
```

The `reference\` directory holds an updated Local cache. The `backups\` directory holds internal SQLite backups. A controlled legacy-data migration copies existing project-local data into a new Windows Application data location without deleting the source or overwriting existing destination data.

## Configuration and Riot API-key protection

Settings can save or replace a Riot API key. On Windows, locally saved keys are encrypted with DPAPI for the current Windows user and stored in `configuration\riot_api_key.dpapi`. A legacy plaintext `configuration\riot_api_key.txt` can be migrated to protected storage. `RIOT_API_KEY` remains a supported environment source for development or deployment configuration.

The key is not stored in SQLite and is not included in Database backups or JSON exports. DPAPI protection is not a promise that the key can be moved to another Windows profile or computer; save a new key when the existing protected value cannot be decrypted. Riot development keys expire and must be replaced when Riot invalidates them. Never commit API keys or data-directory contents.

## Data protection workflows

Database backup and JSON export solve different problems. A backup is a full SQLite recovery point for this installation. A JSON export is Portable data that can be imported through the versioned application contract.

### Database backup and restore

The application can create a Database backup manually. At startup it also creates one when an existing database has no backup or the newest backup is at least 24 hours old. Internal backups use SQLite's backup operation, and the default retention policy keeps the 10 newest files.

Database restore accepts only validated internal backup candidates. Selecting a backup copies it into private staging; it does not immediately replace the live database. The staged restore is verified and applied before SQLAlchemy opens the database on the next startup. If a live database exists, the application first creates and validates a Safety backup. Failed validation or replacement leaves the current database in place.

### JSON export and import

JSON export produces a UTF-8 portable file containing Persons, Riot accounts, Champions, Champion Mastery, format metadata, and counts. Stable relationships use PUUID, Riot Champion IDs, and nesting rather than internal database primary keys. Local secrets are excluded.

JSON import is not Database restore. The application validates and privately stages an export, shows a preview, rejects blocking PUUID conflicts, and requires the exact confirmation text `IMPORT`. Immediately before an import that writes data, it revalidates the source and plan, consumes the staged request so it cannot run twice, and creates a mandatory Safety backup. Database changes run in one transaction and roll back on failure. A no-change plan performs no writes and creates no backup.

## Desktop lifecycle

The packaged application coordinates its local server, browser, notification-area integration, and shutdown:

- Single-instance control prevents a second server process for the same user session; a second launch opens the existing local application URL.
- Each browser tab sends a local heartbeat. After at least one tab has registered, closing all relevant tabs allows the application to request Controlled shutdown after its grace period.
- Settings provides an explicit Controlled shutdown action.
- Server, tab-monitor, tray, and instance-lock resources are cleaned up during shutdown.
- Windows packages are console-free.

These behaviors are local. They do not make startup or navigation dependent on internet access.

## Legal notice and attribution

League Mastery Tracker isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

Source of champion reference data and graphical assets: Riot Games Data Dragon. The application stores this material locally to support offline use.

- [Riot Developer General Policies](https://developer.riotgames.com/policies/general)
- [Riot Data Dragon documentation](https://developer.riotgames.com/docs/lol)

## Development outlook

The stable product identity is League Mastery Tracker 2.0, Version 2.0.0. Core local-data, synchronization, backup, portable-data, offline-reference, and lifecycle workflows are implemented. Ongoing work should continue to rely on focused regression checks and final Windows acceptance evidence; later documentation or terminology slices do not by themselves declare the release complete.
