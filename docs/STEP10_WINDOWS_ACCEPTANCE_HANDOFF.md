# Step 10 Windows Build and Acceptance Handoff

This checklist completes the native Windows work that remains after the
source implementation through Step 10.15. Step 10.14 language verification
and Step 10.15 regression verification are complete. Steps 10.16 through
10.19 remain pending; the Step 10.16 build now has a recording script and a
CI build job. No Windows build or Windows acceptance result is claimed by
this document.

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

All Step 10 work, including the Linux compatibility branch, is merged into
`main` on GitHub. Transfer the source by cloning the repository on the Windows
machine and checking out the exact commit to be accepted:

```powershell
git clone https://github.com/oleseter-star/League-Mastery-Tracker.git
cd League-Mastery-Tracker
git checkout <commit>
git status
```

Record the commit hash before any Windows work and require a clean working
tree. The build script below refuses to run from a dirty tree and records the
commit it built.

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

Prefer running the build through the recording script, which performs the
primary onefile build and collects the build evidence:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\record_windows_build.ps1
```

Pass `-Spec LeagueMasteryTracker.spec` for the comparison target. The script
refuses to overwrite an existing `dist\LeagueMasteryTracker.exe`; record or
move it first, or pass `-RemovePriorOutput` to record its hash and remove it.

The script exits nonzero unless PyInstaller exits with code 0 and the
executable at `dist\LeagueMasteryTracker.exe` is an x64 Windows GUI
(console-free) program whose version metadata matches
`application/config/__init__.py`. It does not check the application icon,
bundled templates and static assets, bundled reference data, or local
Champion images; those are confirmed by the offline first-startup checks
below and by inspecting the icon in File Explorer.

The `windows-onefile` job in `.github/workflows/linux-ci.yml` runs the same
script on a GitHub-hosted Windows Server 2022 runner and uploads the
executable with its evidence. Treat that artifact as an early build check
only; it does not replace the native build and acceptance recorded here.

## Build evidence

Record one row for every build attempt. The recording script prints a
ready-made row and writes it, with `evidence.json`, the PyInstaller logs, and
the extracted warning lines, to `build\windows-build-evidence\<UTC time>\`.
Fill in the icon column by hand.

| Windows version | Python version | Commit | Spec | Command | Start/end time | Exit code | Warnings | Executable path | Executable size | SHA-256 | Version metadata | Icon result | Console-window result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Microsoft Windows 11 Home 10.0.26200 build 26200 | 3.12.10 (64bit) | ec7d3434a325 | LeagueMasteryTracker-onefile.spec | `python -m PyInstaller --clean --noconfirm LeagueMasteryTracker-onefile.spec` | 2026-09-29 18:30:03Z to 2026-09-29 18:30:24Z | 0 | 3 | dist\LeagueMasteryTracker.exe | 32908384 | 61FB43B2ACEB67FA8751A235E023A1D4B634CA345F457E0DAAA24D13C3B4FE08 | League Mastery Tracker 2.0.0 / file 2.0.0 | Application icon shown in File Explorer | Windows GUI (no console window) |

The script computes the SHA-256 itself. To recheck a copied executable, use:

```powershell
Get-FileHash .\dist\LeagueMasteryTracker.exe -Algorithm SHA256
```

## Isolated program and data setup

Copy the executable outside the source and project directories. Use a fresh,
isolated Application data directory; do not reuse normal user data. Set the
supported override before launch. A variable set with `$env:` applies only to
programs started from that terminal, so for launches from File Explorer set it
for the Windows user and remove it after acceptance:

```powershell
[Environment]::SetEnvironmentVariable("LEAGUE_MASTERY_TRACKER_DATA_DIR", "C:\Step10-Acceptance\data", "User")
# After acceptance:
[Environment]::SetEnvironmentVariable("LEAGUE_MASTERY_TRACKER_DATA_DIR", $null, "User")
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

Result (2026-09-29, build `61FB43B2…C3B4FE08` from commit `ec7d3434a325`,
copied to `C:\Step10-Acceptance\app`, data in `C:\Step10-Acceptance\data`,
network disconnected): failed on bundled reference data. The console, browser,
2.0 identity, tray (Open and Shut down), isolated data directory, and clean
shutdown items passed. A later fresh-data-directory start showed
"Database-only fallback" with 0 champions in the database: Git for Windows had
checked out `champions.json` with CRLF line endings, so its SHA-256 no longer
matched the manifest and the bundled dataset was rejected. Fixed by
`.gitattributes` marking `application/bundled_reference_data/**` as `-text`;
repeat this section with a rebuilt executable.

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
