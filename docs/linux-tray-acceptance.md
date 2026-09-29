# Linux GTK3/XEmbed tray acceptance plan

## Current status

At initial Slice 1A publication, "G1 has not run" was the recorded status.
Subsequently supplied evidence reports G1 run 34900930843, attempt 1, source
`33517676f8c7a3b3d47a4a53d0afc0f3a127aa25`, with exit status 0. Its retained
artifact contains only `provenance.json`, `source-commit.txt`, `preflight.log`,
and `g1-status.txt`; it does not retain wheels, sources, toolchain artifacts,
or native archives. This is historical compilation/binding evidence, not a
reusable build-input bundle. Slice A now defines offline native-input validation.
G2 through G7 are required to fail as unimplemented until their prerequisite
implementation slices land. Nothing in this document certifies a functioning
or standalone package.

The gate entry point is:

```bash
bash packaging/linux/run_tray_gates.sh G1 \
  --python /opt/lmt-cpython312/bin/python3.12 \
  --work-root /var/tmp/lmt-tray-lab-UNIQUE
```

The canonical work root must be a new absolute path of at most 128 bytes,
containing only printable ASCII characters, outside the repository and its
`.venv`. Canonicalization and this path check precede builder operations. The
runner creates only its own private environment, downloads, sources, wheels,
and reports below that root. It never provisions packages.

Provision a disposable Ubuntu 22.04/x86-64 builder separately:

```bash
sudo bash packaging/linux/provision_tray_lab.sh \
  --disposable-builder --build
```

Later native-lab provisioning is separately selected:

```bash
sudo bash packaging/linux/provision_tray_lab.sh \
  --disposable-builder --native-lab
```

The provisioning script does not supply CPython 3.12. The operator must provide
an explicit trusted CPython 3.12 interpreter with development headers. G1 does
not silently use another Python, OS baseline, or architecture.

## G1 — builder and binding feasibility

G1 passes only when all of these are true:

* `/etc/os-release` identifies Ubuntu 22.04 exactly;
* `uname -m` is `x86_64`;
* the explicit interpreter is CPython 3.12, has `Python.h`, and has pip;
* every documented build prerequisite is installed;
* all build-tool inputs resolve from the exact pinned requirement file as
  binary distributions without dependency resolution;
* the isolated environment contains the exact toolchain pins;
* pycairo source is fetched, built and installed before PyGObject source
  metadata preparation is allowed to execute its backend;
* build isolation is disabled and no unpinned build dependency is downloaded;
* pycairo is built and installed before PyGObject is built;
* the verifier requires Gtk 3.0, GdkPixbuf 2.0, Gio 2.0 and GLib 2.0, then uses
  `gi.module.get_introspection_module()` to read raw typelib/native versions;
* it deliberately does not import `gi.repository.Gtk` or exercise overrides;
  real override initialization remains a restricted later gate;
* compiler, linker, Meson, Ninja and pkg-config executable hashes and version
  lines identify the configured tools; bounded status-bearing traces cover only
  each binding's wheel phase and correlate its source and resulting wheel;
* pycairo's validated `setuptools.build_meta` source requires completed
  pkg-config, compilation, compiler-driver link and linker-proxy operations; it
  neither requires nor permits Meson/Ninja evidence or Meson introspection;
* PyGObject's validated `mesonpy` source uses the pinned Meson-Python persistent
  `build-dir`; completed Meson, Ninja, pkg-config, compilation and linked output
  evidence is required, and compiler introspection is collected immediately;
* GCC uses Meson's supported `CC_LD=bfd` selector plus GCC's documented
  first-precedence `-B` search and `-fuse-ld=bfd`. A harmless G1 driver fixture
  and matched driver/linker operation tokens prove that linking reaches the
  transparent `ld.bfd` proxy. Proxies preserve arguments and streams, observe
  actual child disposition, forward catchable termination and reap children;
  SIGKILL itself cannot be caught or forwarded;
* version/configuration probes, failed or output-less operations, direct linker
  calls, stale sections, and mismatched driver/linker tokens are not build proof;
  the `cc -Wl,--version` linker query is allowed but excluded from build evidence;
  output-write events and bounded content identities connect a pinned source C
  input to its object, driver/linker output, and the wheel extension's ELF code
  section, allowing an identical-byte rebuild or backend copy/ELF metadata edit
  while rejecting unchanged pre-existing outputs; any lost output watch or
  trace-recording failure leaves detectable incomplete recording state that
  blocks the validator even if a build backend ignores a proxy's status.
  Each proxy invocation establishes its own pending entry before launching its
  child and clears it only after any required trace record is written. If a
  child exits 0 but evidence recording fails, proxy exit 74 reports an
  instrumentation failure; this does not transparently preserve child exit 0.
  Existing nonzero and signal dispositions remain preserved.
  Ordinary exit 143 remains an ordinary exit; actual SIGTERM remains signal termination.
  Complete native
  operation details, including PyGObject's 38 object inputs, are capped at
  32 KiB per encoded record and 4 MiB for the trace;
* bounded source `PKG-INFO` and `pyproject.toml`, wheel `METADATA`/`WHEEL`, one
  valid `Wheel-Version`, compatible tags, exact requirement pins, installed
  versions, filenames and hashes all agree; source inspection checks regular
  compressed files before streaming under member/metadata/decompression limits,
  including PAX and GNU extended-header entries and bytes before their decoding;
* required provenance is complete and written exclusively to a new report;
* any failed command makes the gate fail and prevents a success record.

The provenance report records separate hashes for downloaded sources and built
wheels, exact requirement-file hashes, official project identities, actual
Python/binding/native versions, native build-package versions, and resolved
build distributions. Newly recorded hashes are evidence from that run rather
than pre-existing trusted lock material.

G1 is a compatibility and compilation gate only. A successful import or `ldd`
result does not prove standalone runtime completeness or a native menu.

Native package versions are required G1 evidence. Native archive/source hashes
are explicitly recorded as unavailable at G1 and are required before G2 freezes
the first package; a version string is not a substitute for those hashes.

## Gate execution matrix

All work roots are new, explicit paths outside the repository. “Planned” means
the named later-slice driver must exist before the invocation is enabled.

| Gate | Where and privileges | Invocation | Required evidence |
| --- | --- | --- | --- |
| G1 | disposable Ubuntu 22.04/x86-64 builder; unprivileged after separate root provisioning | `bash packaging/linux/run_tray_gates.sh G1 --python /opt/lmt-cpython312/bin/python3.12 --work-root /var/tmp/lmt-g1-UNIQUE` | sources/wheels/tool identities and hashes, pins, raw namespace/native versions, explicit native-archive gap |
| G2 | same builder, unprivileged | planned `bash packaging/linux/run_tray_gates.sh G2 --python /opt/lmt-cpython312/bin/python3.12 --work-root /var/tmp/lmt-g2-UNIQUE --g1-evidence /var/tmp/lmt-g1-UNIQUE/reports/provenance.json` | probe hash/archive manifest, dependency closure, hook order and worker topology |
| G3 | disposable VM; root only for namespace/mount/network setup, artifact under ordinary UID | planned `sudo bash packaging/linux/run_tray_gates.sh G3 --work-root /var/tmp/lmt-g3-UNIQUE --probe /var/tmp/lmt-g2-UNIQUE/dist/LinuxTrayProbe --g2-evidence /var/tmp/lmt-g2-UNIQUE/reports/g2.json` | restricted-root trace, native clicks/menu/actions, module exclusion, parent death and cleanup |
| G4 | repository test environment on Linux and Windows; no display privilege | planned `bash packaging/linux/run_tray_gates.sh G4 --python /absolute/python3.12 --work-root /var/tmp/lmt-g4-UNIQUE` | unit/process results for protocol, lifecycle, selection, browser and Windows regressions |
| G5 | G3 disposable VM/lab; same restricted-root privileges | planned `sudo bash packaging/linux/run_tray_gates.sh G5 --work-root /var/tmp/lmt-g5-UNIQUE --executable /absolute/LeagueMasteryTracker --g3-evidence /var/tmp/lmt-g3-UNIQUE/reports/g3.json` | production onefile interaction, HTTP, duplicate/start/stop/quarantine/no-network evidence |
| G6 | clean supported XFCE/X11 machine; normal desktop user | planned `bash packaging/linux/run_tray_gates.sh G6 --work-root /var/tmp/lmt-g6-UNIQUE --executable /absolute/LeagueMasteryTracker` plus recorded manual checklist | artifact hash, host facts, click/menu/panel/restart observations and process cleanup |
| G7 | Windows 2022 test/build runner plus normal interactive Windows desktop | planned PowerShell equivalent documented in Slice 7; it must not be added until its driver exists | automated Windows regression plus separately signed interactive pystray result |

G2–G7 currently reject with nonzero status; the planned invocations above are
contracts for their listed implementation slices, not working commands.

## G2 — frozen probe inventory

### Slice A prerequisite: offline native inputs

The new `packaging/linux/capture_tray_native_inputs.py` implements only the
schema-1 prerequisite documented in the design's "Slice A: offline native-input
manifest" section. It does not implement the frozen probe or acquire packages.
Supply the actual G1 artifacts, authenticated repository metadata, exact binary
and source archives, selected dependency providers, consumed installed files,
CPython copies and project resources on the matching disposable builder.
The historical report-only artifact is insufficient, and its immutable native
archive `unavailable` label is not changed. Missing project resources also block
a complete real manifest until their later implementation.

Acceptance checks for this slice are bounded offline fixtures, not G2 execution:

* valid actual archive/index/payload parsing, hashing, selected closure and
  exclusive new-manifest publication; G1 remains byte-for-byte unchanged;
* alternatives, versioned virtual providers, Pre-Depends, amd64/all and explicit
  architecture qualification use actual supplied metadata and dpkg comparison;
* missing/conflicting providers, exact versions, indexes, source material,
  invalid signature verification, modified installed files, G1/wheel inputs,
  and unsupported transformations prevent publication;
* unsafe links/paths, malformed/truncated archives, extended-header and stream
  expansion, metadata/count limits, failed or timed-out producers fail closed;
* multi-hop and path-component links retain every authenticated location,
  target text and resolved target; changed intermediate links to byte-identical
  files fail both initial validation and the final chain recheck;
* GNU/PAX sparse encodings, including empty maps, fail before internal sparse
  parsing; ordinary PAX lengths/counts are bounded before decoding;
* incremental control parsing enforces encoded line/paragraph, field, record
  and total index limits; JSON size preflight and streamed publication bound
  individual escaped values and total bytes without whole-output serialization;
* existing evidence is never overwritten, including publication I/O failure.

Trust comes from the external curated keyring, trusted inspection environment,
and independently established G1 digest/selected-commit pair, not bundle flags.
Live installed metadata and consumed bytes are compared with authenticated
archive contents; twelve G1 packages are roots, not the complete closure.
The schema admits only identity transformations. Child exit/output/timeout
limits apply before archive inspection; archive-controlled paths are never
extracted. The separate `validated-offline` manifest covers declared inputs
only, with the exact limits and unsupported cases specified in the design.

Required later integration: compare every actual frozen input and destination,
including CPython files, selected typelibs/native libraries and spec/hook
transformations, against this manifest before freezing/publication. Extra,
missing or changed inputs fail; a declaration alone is not evidence that
PyInstaller consumed it. No Slice A result proves G2 or native interaction.

### Frozen probe (not implemented by Slice A)

Implementation prerequisite: reusable narrow PyInstaller hooks, resource
collector, runtime environment hook, protocol/bootstrap, archive inspector, and
the disposable probe spec/entry point.

Run in the unprivileged Ubuntu builder. Pass criteria:

* the probe freezes using the same hook and resource rules intended for the
  application;
* archive inventory contains only the selected GI namespaces, extensions,
  typelibs, native libraries, schemas, loaders/cache, fontconfig/font and
  minimal theme resources;
* every expected destination and runtime discovery mapping is present;
* forbidden host paths and indiscriminate collection are absent;
* a direct same-executable worker uses the existing extraction, and the
  `Popen` PID is the Python helper process;
* custom runtime hooks execute in the required order.

G2 does not claim a display or menu works.

## G3 — restricted native feasibility

Implementation prerequisite: restricted-root script, Xvfb/Xauthority/XFCE
panel fixture, private test/accessibility bus, XSettings fixture, harmless host
module markers, native XTEST/AT-SPI driver, and parent-death fixture. Namespace
and mount setup requires root or equivalent privileges in a disposable VM; the
artifact runs as an ordinary UID.

Pass criteria:

* host Python, GI, GTK, typelibs, resource directories, and loader caches are
  unavailable to the probe, while only explicit base-system and desktop
  services remain available;
* only loopback networking exists and no Secret Service is present;
* GTK initializes against the private X11 display and the icon embeds;
* real XTEST left and right clicks reach the icon;
* the menu visibly maps and AT-SPI exposes exactly Open and Shut down;
* real pointer selection emits the corresponding fixed protocol actions;
* initial and changed XSettings, basename module requests, and absolute module
  requests cannot load harmless host marker modules;
* the helper's parent-death signal and identity race checks work for the actual
  frozen process topology;
* cooperative stop and bounded TERM/KILL escalation reap every owned process;
* absence or restart of the tray manager follows the documented state policy.

Inability to construct the required supported-Linux state fails rather than
skips. Host-module exclusion failure blocks production integration and requires
an explicit architecture review.

## G4 — production contract verification

After the production helper and browser-boundary slices are integrated, run all
unit and bounded process tests. Verify exact platform selection; empty/missing
DISPLAY behavior; protocol order, limits and malformed input; stop-before-ready;
callback isolation; cleanup deadlines; CLEANUP_FAILED quarantine and status;
eventual reaping; stale process identities; duplicate-instance behavior; browser
environment isolation; Windows pystray behavior; and full existing regressions.

No mocked result substitutes for G3 or G5 native evidence.

## G5 — restricted production package

Run the real onefile application in the G3 restricted environment with isolated
synthetic application data and no real credentials. Pass criteria include:

* the headless path starts without GTK when DISPLAY is absent;
* eligible X11 startup reaches dispatched-loop and embedded readiness;
* actual clicks map the menu and select Open and Shut down;
* Open reaches the existing browser boundary using the controlled no-op BROWSER
  handler at most once and performs no external network action;
* the browser child's `LD_LIBRARY_PATH` is restored from
  `LD_LIBRARY_PATH_ORIG`, or removed when no original exists, and private
  `_PYI_*` worker values do not cross that boundary;
* BROWSER, display, Xauthority, and desktop session-bus controls needed by the
  selected handler remain available without mutating the application process;
* the local HTTP server remains responsive while the tray is active;
* Shut down closes HTTP, reaps H and its process group, joins the supervisor,
  releases the instance lock, and leaves no owned process;
* startup failure and a missing manager are controlled and cleaned;
* duplicate-instance and rapid-restart behavior remain correct;
* a forced incomplete cleanup retains P and its lock, exposes actionable status,
  then exits and releases the lock only after H is reaped;
* no user data, real credential, Secret Service, or external network is used.

## G6 — clean XFCE/X11 target

Run the exact verified artifact as a normal user in a clean supported target,
without host Python/GI/GTK development components. A person must confirm the
icon is visible, left-click Open works, right-click opens the correctly placed
menu, both actions respond, menu dismissal is normal, panel restart behavior is
acceptable, HTTP stays responsive, shutdown completes, and rapid restart works.

The gate records artifact hash, OS/desktop/session facts, accepted host services,
process termination, and the manual observations. XWayland is a separate result;
it is not inferred from environment variables.

## G7 — Windows regression and CI admission

From a repository checkout on a disposable Windows x86-64 lab with CPython
3.12, invoke the proposed Slice 7 driver exactly as:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File packaging/windows/run_tray_gate.ps1 -Gate G7 -WorkRoot C:\lmt-tray-g7 -Executable C:\lmt-tray-g7\artifact\LeagueMasteryTracker.exe
```

That driver runs the complete Windows test/build regression and guides an
interactive packaged Windows tray check. It records tool and artifact
identities plus the manual result. Verify pystray selection,
menu/default action, callbacks, single-instance behavior, browser opening, and
shutdown remain unchanged. The lab requires ordinary-user desktop interaction;
building uses the normal repository toolchain and no administrator privilege.

Only after G1 through G7 have their required evidence may the proven commands
be wired into CI. A noninteractive Windows runner is not native tray evidence.

## Standalone and redistribution gates

Successful imports, archive listing, or `ldd` output are insufficient. The
restricted native and production gates must prove operation without host
Python/GI/GTK resources while retaining only declared X11/XEmbed and operating
system services.

Before distribution, record exact dependency sources and hashes; preserve the
rebuild procedure and replacement materials; provide applicable license and
copyright notices; and review corresponding-source obligations for the exact
onefile linking/redistribution result. A notices document alone is not legal
clearance.

Official contracts used by this plan:

* PyGObject build definition:
  https://raw.githubusercontent.com/GNOME/pygobject/3.48.2/meson.build
* PyGObject PEP 517 backend history and pinned Meson-Python implementation:
  https://github.com/GNOME/pygobject/blob/main/NEWS and
  https://raw.githubusercontent.com/mesonbuild/meson-python/0.16.0/mesonpy/__init__.py
* pycairo 1.26.1 backend and build implementation:
  https://raw.githubusercontent.com/pygobject/pycairo/v1.26.1/pyproject.toml and
  https://raw.githubusercontent.com/pygobject/pycairo/v1.26.1/setup.py
* GCC compiler-subprogram search and BFD linker selection:
  https://gcc.gnu.org/onlinedocs/gcc/Directory-Options.html and
  https://gcc.gnu.org/onlinedocs/gcc/Link-Options.html
* PyInstaller bootstrap and worker environment:
  https://pyinstaller.org/en/v6.21.0/advanced-topics.html
* PyInstaller external-process environment:
  https://pyinstaller.org/en/v6.21.0/common-issues-and-pitfalls.html
* GTK runtime variables and settings:
  https://docs.gtk.org/gtk3/running.html
  https://docs.gtk.org/gtk3/class.Settings.html
* GTK module-loading source:
  https://raw.githubusercontent.com/GNOME/gtk/gtk-3-24/gtk/gtkmodules.c
* GTK StatusIcon and menu APIs:
  https://docs.gtk.org/gtk3/class.StatusIcon.html
  https://docs.gtk.org/gtk3/method.Menu.popup.html
  https://docs.gtk.org/gtk3/type_func.StatusIcon.position_menu.html
* Parent-death and Unix socket contracts:
  https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html
  https://man7.org/linux/man-pages/man7/unix.7.html

Compilation, packaged completeness, native interaction, module exclusion,
clean-desktop compatibility, and redistribution approval remain pending until
their gates actually execute.
