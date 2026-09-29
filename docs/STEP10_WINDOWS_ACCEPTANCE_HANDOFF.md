# Step 10 Windows Build and Acceptance Handoff

This checklist completes the native Windows work that remains after the
source implementation through Step 10.15. Step 10.14 language verification
and Step 10.15 regression verification are complete. Steps 10.16 through
10.19 remain pending. No Windows build or Windows acceptance result is
claimed by this document.

## Evidence already verified

* Product: League Mastery Tracker 2.0
* Version: 2.0.0
* Executable target: `LeagueMasteryTracker.exe`
* Language audit: 352 tracked paths, 178 audited text files, 174 intentional
  binary exclusions, 0 controlled exclusions, 0 findings, and 0 audit errors
* Regression: 783 executed, 770 reconciled passes, 0 failures, 0 errors, and
  13 intentional skips

The regression evidence consists of one restricted full-suite run with two
sandbox-only local-loopback socket permission errors, followed by one focused
elevated rerun of the 16-test `tests.test_application_server_service` module.
The reconciled totals replace only those two errors; they are not a single
unrestricted all-green full-suite invocation. See `Step10-language-audit.txt`
and `Step10-test-results.txt` for the recorded evidence.

## Source-transfer gate

Recorded `origin/main` may not include local Step 10 commits. Before any
Windows work, record and verify the commit containing this checklist and all
of its ancestors, then require a clean Windows working tree.

Choose and record one explicit transfer method:

* Copy the complete Git repository.
* Use a local Git bundle.
* Use a separately authorized remote push.

Do not assume that `origin/main` is current, and do not push automatically.

## Native Windows prerequisites

Use the tracked runtime and build requirements. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
```

Do not add untracked third-party tools or assume a Python version beyond what
the tracked requirements support.

## Build procedure

The primary Windows build is the onefile target:

```powershell
python -m PyInstaller --clean --noconfirm LeagueMasteryTracker-onefile.spec
```

The documented optional comparison target is:

```powershell
python -m PyInstaller --clean --noconfirm LeagueMasteryTracker.spec
```

Before each build, clear or record the prior build output according to the
operator's approved local procedure. Do not record success until the command
has completed with exit code 0. Verify the expected result at
`dist\LeagueMasteryTracker.exe`: the console-free configuration, canonical
name and version metadata, application icon, bundled templates and static
assets, bundled reference data, and local Champion images.

## Build evidence

Record one row for every build attempt.

| Windows version | Python version | Commit | Spec | Command | Start/end time | Exit code | Warnings | Executable path | Executable size | SHA-256 | Version metadata | Icon result | Console-window result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | | | | | | |

Use a native PowerShell hash command after the executable exists:

```powershell
Get-FileHash .\dist\LeagueMasteryTracker.exe -Algorithm SHA256
```

## Isolated program and data setup

Copy the executable outside the source and project directories. Use a fresh,
isolated Application data directory; do not reuse normal user data. Set the
supported override before launch, for example:

```powershell
$env:LEAGUE_MASTERY_TRACKER_DATA_DIR = "C:\Step10-Isolated-Data"
```

The default Windows data location is
`%LOCALAPPDATA%\LeagueMasteryTracker\`. Mutable data must remain outside
program files. Record the selected data directory and a recovery path before
any JSON import or Database restore test.

## Offline first startup

Disconnect the network, launch the copied executable from File Explorer, and
record each result:

* No console window appears.
* The browser opens the local application.
* The interface identifies League Mastery Tracker 2.0.
* Bundled reference data is active, with Champion names and local icons.
* No Data Dragon update is required for first startup.
* No project files are required by the copied executable.

## Visual and responsive acceptance

Review every route/page at 1920x1080, 1366x768, 1280x720, and a narrow
browser window, then at Windows scaling of 100%, 125%, and 150%. Check
navigation, headers, cards, forms, tables, buttons, long names, large Mastery
values, Champion images, placeholders, focus rings, clipping, overlap, and
horizontal page scrolling.

## Accessibility smoke checks

Check keyboard-only navigation, visible focus, logical tab order, landmarks
and headings, status and error announcements, form labels, Champion image and
placeholder names, and confirmation clarity. An optional screen-reader smoke
test should record the tool used and its findings.

## Functional acceptance

Use only isolated disposable data. Verify:

* Create a Person.
* Add a Riot account.
* Synchronize Champion Mastery and inspect Mastery with local images.
* Create a Database backup.
* Perform JSON export and JSON import.
* Perform Database restore.
* Run a manual reference-data update.
* Restart and verify persistence.
* Exercise Unknown champion and Missing metadata behavior.

Adding a Riot account, synchronizing Champion Mastery, and manually updating
reference data are deliberate network actions. Perform those steps only with
explicitly supplied test credentials and network availability; do not request
or record real credentials in this checklist.

## Lifecycle acceptance

Verify single-instance behavior, tab lifecycle handling, Controlled shutdown,
restart after restore, and absence of orphaned processes. Confirm that startup
and navigation make no unexpected automatic network call.

## Failure ledger

Record failures without silently retrying or editing production during
acceptance.

| Check | Expected | Actual | Pass/fail | Evidence | Issue/follow-up |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

## Completion and final gate

After successful Windows acceptance:

1. Update `Step10-test-results.txt` with build and acceptance evidence.
2. Update `README.md` only if final claims change.
3. Rerun language verification and only tests required by documentation
   changes.
4. Confirm a clean Git state and review the remaining Step 11 backlog.
5. Commit the final handoff evidence.
6. Push only with explicit authorization in Step 10.19.

Prior audits identified no Step 11 candidates that require documentation.
Step 10 remains incomplete until the Windows build and acceptance succeed.
