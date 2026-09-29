# Planned standalone Linux GTK3/XEmbed tray

## Status and scope

This document specifies a planned Linux tray implementation. The current
application does not implement this design. The initial Slice 1A status was
"G1 has not run". Subsequently supplied run evidence identifies G1 run
34900930843, attempt 1, source
`33517676f8c7a3b3d47a4a53d0afc0f3a127aa25`, and reported exit status 0.
Its retained artifact contains only `provenance.json`, `source-commit.txt`,
`preflight.log`, and `g1-status.txt`, not reusable build inputs. This is
historical compilation/binding evidence, not a claim of a standalone frozen
package, native menu interaction, or completed redistribution review.

The target is a standalone Ubuntu 22.04-compatible x86-64 onefile package with
an interactive tray menu on XFCE/X11. The menu retains the existing **Open**
and **Shut down** actions. Windows continues to use pystray unchanged. Linux
environments outside the supported target retain controlled trayless startup.
Users must not need Python, PyGObject, GTK, or an automatic runtime download.

The design uses a supervised same-executable helper because GTK and its GLib
loop need coherent main-thread ownership, while the application server already
occupies the application process. It also gives the parent a process boundary
for bounded shutdown escalation when a native call does not return.

## Process and import boundaries

The intended onefile topology is:

```text
B: PyInstaller extraction parent
└─ P: application process; owns server and instance lock
   └─ H: same-executable GTK helper; owns GTK and the GLib loop
```

P creates H from P's main thread with `sys.executable`, a private versioned
helper option, one inherited Unix-domain control socket, `close_fds=True`, and
a new process group. The instance-lock descriptor is never inherited. H must
not request `PYINSTALLER_RESET_ENVIRONMENT=1`: it is a PyInstaller worker using
the same extraction, not an independent onefile instance.

An early root-level bootstrap handles the private helper and read-only tray
status options before importing the `application` package. GTK imports are
lazy and occur only in H's main thread after its identity and CONFIG packet are
validated. A custom runtime hook establishes the child environment before
standard GI/GTK runtime hooks.

PyInstaller documents the onefile parent/application-worker topology, private
worker variables, and user-runtime-hook ordering here:

* https://pyinstaller.org/en/v6.21.0/advanced-topics.html
* https://pyinstaller.org/en/v6.21.0/common-issues-and-pitfalls.html

Gate G2 must prove that `Popen.pid` is H, rather than another extraction
parent. A different topology blocks production integration.

## Linux selection and display eligibility

Eligibility is evaluated only after the existing second-instance early return,
so a duplicate invocation does not import GTK or start a helper.

The executable predicate and precedence are exact:

1. Non-Linux platforms use their existing implementation. Windows continues
   to use pystray.
2. On Linux, an unset `PYSTRAY_BACKEND`, an empty value, or exactly `gtk`
   selects the planned adapter subject to display checks.
3. `xorg`, `dummy`, `appindicator`, and every unrecognized nonempty value are
   controlled tray-unavailable outcomes. There is no implicit fallback.
4. Missing or whitespace-only `DISPLAY` is controlled trayless startup and H
   is not spawned.
5. Nonempty `DISPLAY` is only an X11 candidate. It is forwarded unchanged to H.

`XDG_SESSION_TYPE` is not evidence that X11 works. `WAYLAND_DISPLAY` does not
veto an XWayland candidate when `DISPLAY` exists. Pure Wayland without DISPLAY
is trayless. Wayland plus XWayland attempts the X11 adapter. An X11 session
with an absent, stale, or unauthorized DISPLAY remains unavailable.

Only H receives `GDK_BACKEND=x11` and has `WAYLAND_DISPLAY` removed. It retains
the resolved Xauthority access. It performs module-policy checks, calls
`Gtk.init_check()`, requires an X11 GDK display, constructs the icon and menu,
then requires both a dispatched GLib idle and actual XEmbed embedding before
reporting READY. Failure is controlled only after H has been cleaned up; an
incompletely cleaned helper enters `CLEANUP_FAILED`.

GTK initialization and runtime environment references:

* https://docs.gtk.org/gtk3/func.init_check.html
* https://docs.gtk.org/gtk3/running.html

## GTK adapter

H uses public GTK3 APIs:

* `Gtk.StatusIcon.new_from_pixbuf()`, title, tooltip, and visibility setters;
* `activate` for Open;
* `popup-menu` for a `Gtk.Menu` containing Open, a separator, and Shut down;
* `Gtk.Menu.popup()` with `Gtk.StatusIcon.position_menu`, the supplied button,
  and event time;
* `notify::embedded` to observe loss and recovery of panel embedding;
* one actual `GLib.MainLoop` owned by H's main thread.

API references:

* https://docs.gtk.org/gtk3/class.StatusIcon.html
* https://docs.gtk.org/gtk3/signal.StatusIcon.activate.html
* https://docs.gtk.org/gtk3/signal.StatusIcon.popup-menu.html
* https://docs.gtk.org/gtk3/method.Menu.popup.html
* https://docs.gtk.org/gtk3/type_func.StatusIcon.position_menu.html
* https://docs.gtk.org/glib/method.MainLoop.run.html
* https://pygobject.gnome.org/guide/threading.html

P generates the 64-by-64 RGBA icon using the existing Pillow drawing code,
copies its bytes, and closes the Pillow image. H constructs the pixbuf in
memory with `GdkPixbuf.Pixbuf.new_from_bytes()`; no image file is created.
Reference: https://docs.gtk.org/gdk-pixbuf/ctor.Pixbuf.new_from_bytes.html

All GTK work and GUI callbacks remain on H's main thread. Callbacks enqueue a
fixed action record and return; they never wait indefinitely for IPC. P's one
supervisor thread handles IPC and child reaping. It dispatches the existing
quick browser-background and idempotent shutdown entry points outside its state
lock. Callback exceptions become fixed protocol failures without arbitrary
exception text.

During teardown H removes GLib sources, disconnects signals, pops down and
destroys the menu, hides the StatusIcon, releases references, and quits the
loop. `Gtk.StatusIcon` is not assumed to have a `destroy()` method. The widget
destroy contract is documented at:
https://docs.gtk.org/gtk3/method.Widget.destroy.html

Loss of embedding changes READY to DETACHED but does not start another helper.
The same icon and loop may return to READY if embedding returns. Panel-restart
behavior remains an empirical desktop gate.

## Control protocol

The transport is a private inherited nonblocking `AF_UNIX` `SOCK_SEQPACKET`
socketpair. Each record is exactly one packet and is limited to 32,768 bytes,
including a 16-byte network-order header `!4sBBHII`:

```text
magic LMTT, version 1, type, flags 0, payload length, sequence
```

Each direction has a sequence starting at one and increasing strictly. A
sequence is allocated at send time so dropped or coalesced queued records do
not create gaps.

CONFIG begins with `!HHHBBHHHH`: width, height, rowstride, channels,
bits-per-sample, and the byte lengths of title, Open label, and Shut down
label, followed by a zero reserved field. Values are fixed at 64, 64, 256,
four channels, and eight bits. Each UTF-8 label is nonempty, contains no NUL or
control character, and is at most 256 encoded bytes. It is followed by exactly
16,384 raw RGBA bytes. The maximum packet is:

```text
16 + 16 + (3 × 256) + (64 × 64 × 4) = 17,184 bytes
```

That leaves 15,584 bytes below the packet limit. There is no JSON, base64,
compression, file path, or image decoder in CONFIG.

Protocol order is HELLO from H, CONFIG from P, LOOP_READY from a dispatched
GLib callback, and EMBEDDING. LOOP_READY plus positive embedding establishes
READY. Other fixed records are OPEN, SHUTDOWN, ACTION_RESULT, STOP, STOPPED,
and ERROR. OPEN carries no URL. SHUTDOWN and STOP are idempotent. STOP is valid
during startup and takes priority over normal queued work. STOPPED is only an
acknowledgement; child exit and reaping prove termination.

Only one Open request may be outstanding; repeats are coalesced until its fixed
result. Once shutdown is latched, later Open requests are rejected. Valid late
records cannot resurrect a stopping worker.

Both ends use `recvmsg(32768)`. `MSG_TRUNC`, `MSG_CTRUNC`, ancillary data,
invalid header fields, size mismatch, illegal order, invalid UTF-8, or bad
sequence causes a fixed protocol failure. Received descriptors are closed and
never used. EOF means disconnection. At most one nonblocking fixed ERROR is
attempted; payloads are never logged.

Sends are whole-record nonblocking `sendmsg()` operations with `MSG_NOSIGNAL`,
never `sendall()`. Each side has an eight-record, 64-KiB queue, flushes at most
four records per dispatch, coalesces embedding/Open records, and prioritizes
STOP. A record unsent for two seconds, overflow, or transport failure starts
controlled cleanup. Writable watches exist only while required.

The underlying socket contracts are documented at:

* https://man7.org/linux/man-pages/man7/unix.7.html
* https://docs.python.org/3.12/library/socket.html

## Parent death and identity

The first helper hook validates its private arguments and socket, checks that
`getppid()` equals the supplied P PID, installs `PR_SET_PDEATHSIG` with SIGKILL,
then checks the parent again to close the setup race. The parent validates the
HELLO PID, parent PID, and process group against the `Popen` result. A socketpair
peer credential is not treated as proof of H's PID because P created both ends.

Linux ties the death signal to the creating parent thread, so P's main thread,
not its supervisor, must spawn H. The kernel contract is documented at:
https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html

The mechanism cannot promise prompt exit for an uninterruptible kernel task.
H cannot initialize GTK until CONFIG, limiting the pre-arm race consequence.

## Lifecycle and `CLEANUP_FAILED`

The planned states are:

```text
STARTING → READY ↔ DETACHED → STOPPING → STOPPED
STARTING/STOPPING → CLEANUP_FAILED → CLEANED_AFTER_FAILURE
```

Monotonic deadlines are 15 seconds for startup, two seconds for cooperative
STOP, one second after SIGTERM, two seconds after SIGKILL for exit/reaping, and
one second to join the supervisor. These bound application waits; Python cannot
forcibly terminate a blocked native thread.

P's main thread owns the application instance lock. If server shutdown finishes
but H or the supervisor cannot be confirmed clean after escalation, P's main
thread enters an explicit cleanup-quarantine loop and retains its open lock
descriptor. The existing supervisor continues nonblocking process monitoring.
The main thread checks at most once per second. It neither respawns nor repeats
signals, browser actions, or log messages.

There is no automatic total quarantine timeout. Eventual H exit is reaped by
the supervisor; after the supervisor joins and resources close, the state
becomes CLEANED_AFTER_FAILURE, the lock is released, and P exits with a
controlled failure. If H is gone but the supervisor cannot join, the distinct
supervisor failure remains quarantined.

Lifecycle state is stored next to the existing lock as a private regular
`application-instance-<digest>.tray-state.json` file. It has mode 0600 and a
bounded schema containing state/reason codes, P/H PIDs, process-start identities
and boot identity only. It contains no URL, credential, environment value, or
exception text. Unsafe ownership, symlinks, oversized input, or inability to
establish the initial record prevents helper startup. H's identity is recorded
before CONFIG permits GTK initialization.

An early read-only `LeagueMasteryTracker --tray-status` path validates that
record without importing GTK/application code and tells the user that HTTP is
closed, cleanup still owns the lock, which process remains, and whether to wait
or deliberately terminate P. A single fixed stderr notice points to that
command. Record-write failure after startup never reports a false clean state.

SIGINT/SIGTERM during quarantine marks explicit abandonment, makes one final
nonblocking termination attempt, leaves unresolved status, and exits nonzero.
An explicitly documented `os._exit()` is reserved for that path if a stuck
non-daemon thread prevents normal exit. SIGKILL/crash cannot guarantee Python
cleanup or a final status update.

The lock cannot survive P's exit. A later first instance therefore validates
the retained helper birth identity before starting another helper. A matching
live H blocks startup; PID reuse alone does not. It never adopts or signals an
unverifiable process. The launcher's final cleanup must release the lock only
after confirmed cleanup. Windows lock behavior and the normal second-instance
browser behavior remain unchanged.

## Browser boundary

Only the environment passed at the Linux external-browser process-launch
boundary is sanitized. It begins as a copy of P's environment. If
`LD_LIBRARY_PATH_ORIG` exists, its value becomes the child's
`LD_LIBRARY_PATH`; otherwise the child has no `LD_LIBRARY_PATH`. The child does
not receive PyInstaller's private `_PYI_*` worker variables. P's global
environment is not mutated.

The child retains `BROWSER`, `DISPLAY`, `WAYLAND_DISPLAY`, `XAUTHORITY`, and the
desktop session-bus value needed by a normal browser. This preserves the
committed private no-op `BROWSER` acceptance contract. Existing duplicate
suppression and background opening remain in force, and the sanitation occurs
only when the known browser action actually launches its child. Windows
behavior is unchanged. PyInstaller's external-program environment guidance is:
https://pyinstaller.org/en/v6.21.0/common-issues-and-pitfalls.html

## Dependencies and frozen resources

The proposed Python pins are `pycairo==1.26.1` and `PyGObject==3.48.2`, using
the existing `pyinstaller==6.21.0` and pinned hook collection. G1 builds pycairo
with its declared `setuptools.build_meta` backend, installs it, and only then
allows PyGObject metadata preparation and its declared `mesonpy` wheel build.
Build isolation is disabled. Published metadata and upstream build definitions
support attempting this combination; Ubuntu 22.04 with the selected CPython
3.12 required the G1 proof described above; future inputs must be linked to
their own validated build evidence:

* https://pypi.org/project/pycairo/1.26.1/
* https://raw.githubusercontent.com/pygobject/pycairo/v1.26.1/pyproject.toml
* https://raw.githubusercontent.com/pygobject/pycairo/v1.26.1/setup.py
* https://pypi.org/project/PyGObject/3.48.2/
* https://raw.githubusercontent.com/GNOME/pygobject/3.48.2/meson.build
* https://gnome.pages.gitlab.gnome.org/pygobject/guide/imports.html
* https://bugzilla.gnome.org/show_bug.cgi?id=686828
* https://raw.githubusercontent.com/mesonbuild/meson-python/0.16.0/mesonpy/__init__.py
* https://raw.githubusercontent.com/pypa/pip/24.0/src/pip/_internal/configuration.py

The pinned GTK override initializes GTK on a normal `gi.repository.Gtk`
import. G1 instead uses PyGObject's unoverridden
`gi.module.get_introspection_module()` after exact `require_version()` calls.
That proves the installed distributions, raw namespace/typelib loading and
native version symbols without exercising overrides, initializing GTK or
opening a display. The real override is tested only inside G3's restricted
native environment.

The following is the exact collection contract to implement in Slice 2. Paths
below are relative to the frozen extraction root. G2 records the resolved file
manifest and fails on a missing or additional resource; the table is a design
contract, not evidence that collection already works.

| Resource | Builder source and collection | Destination and discovery | Omission/escape check |
| --- | --- | --- | --- |
| Python GI | Built `PyGObject==3.48.2` wheel; collect `gi`, `_gi` and the overrides imported by the listed namespaces | normal frozen Python package layout; standard frozen import mechanism | isolated imports plus archive allowlist; reject host `site-packages` |
| Cairo binding | Built `pycairo==1.26.1` wheel | normal frozen `cairo` package/extension layout | raw-pixbuf probe imports cairo with host Python paths hidden |
| GI typelibs | Ubuntu packages owning the dependency closure of `Gtk-3.0`, `Gdk-3.0`, `GdkX11-3.0`, `GdkPixbuf-2.0`, `Gio-2.0`, `GLib-2.0`, `GObject-2.0`, `Atk-1.0`, `Pango-1.0`, `HarfBuzz-0.0` and `cairo-1.0`; copy only the closure selected by GIRepository | `lib/girepository-1.0`; H gets `GI_TYPELIB_PATH` containing only that directory | enumerate loaded namespaces and typelib paths; hide host typelib roots in G2/G3 |
| Native libraries | PyInstaller binary-dependency closure rooted at `_gi`, cairo, GTK/GDK/GdkPixbuf/Pango/Atk/GIRepository; record every owning package and hash | `lib`; early runtime hook prepends only this directory to H's loader path | archive/readelf closure plus restricted execution with host GTK/GI libraries hidden |
| GTK theme | project-owned minimal CSS committed as `packaging/linux/resources/theme/LMT/gtk-3.0/gtk.css` | `share/themes/LMT/gtk-3.0`; H alone gets `GTK_THEME=LMT` and private `XDG_DATA_DIRS` | G3 traces theme opens and rejects paths outside the extraction root |
| Fontconfig/font | exact `packaging/linux/resources/fonts.conf.in` template plus the Ubuntu `fonts-dejavu-core` DejaVu Sans regular font, with ownership/version/hash recorded | `etc/fonts/fonts.conf` and `share/fonts/DejaVuSans.ttf`; H gets `FONTCONFIG_FILE` and `FONTCONFIG_PATH` | render assertion plus file-open trace with host font directories hidden |
| GSettings schemas | none required by StatusIcon/Menu as designed | H gets `GSETTINGS_SCHEMA_DIR` pointing to an empty private directory | any schema lookup failure in G2/G3 blocks and requires an explicit manifest revision |
| Image loaders/cache | none: CONFIG supplies raw RGBA to `Pixbuf.new_from_bytes()` | no loader path or cache is set | archive rejects loader modules/cache; native probe proves raw icon construction |
| Optional GTK modules | none | H gets private empty `GTK_PATH`; module requests are denied by the Slice 2 policy | G3 exercises environment and XSettings basename/absolute requests using inert markers |

The runtime hook creates no resources; it resolves the frozen root, validates
the listed private paths, and prepares an H-only environment. The build hook
uses explicit manifests and PyInstaller dependency analysis rather than an
indiscriminate `collect_all()`.

No arbitrary system theme, icon theme, input-method module, accessibility
module, print backend, or host GI/GTK path is intended as an application
dependency. The X server/Xauthority, XEmbed tray manager, font/rendering kernel
facilities, libc/kernel ABI, and permitted desktop services are intentional host
dependencies.

GTK can obtain modules from environment and desktop settings, and accepts
absolute module paths. Therefore environment path changes alone do not prove
host-module exclusion. Gate G3 must test initial and updated XSettings values,
basename and absolute module requests, and harmless host markers against the
exact collected GTK build. Failure blocks production integration.

Relevant GTK sources and settings contract:

* https://raw.githubusercontent.com/GNOME/gtk/gtk-3-24/gtk/gtkmodules.c
* https://raw.githubusercontent.com/GNOME/gtk/gtk-3-24/gtk/gtksettings.c
* https://docs.gtk.org/gtk3/class.Settings.html

## Provenance and redistribution

### Slice A: offline native-input manifest (schema 1)

This is a new pre-G2 validation implementation, not a change to the approved
resource table or the G1 collector. `capture_tray_native_inputs.py` reads an
explicit offline bundle on the disposable builder. It neither acquires inputs
nor freezes anything. It publishes a separate manifest; the original G1 report
and its `availability: unavailable` / `required_before: G2-freeze` remain
unchanged. Historical report-only artifacts cannot satisfy this validator.

The CLI, using an operator-supplied trusted CPython 3.12 environment with the
existing G1 collector's Python dependencies, is:

```bash
/absolute/trusted/python3.12 -I -B packaging/linux/capture_tray_native_inputs.py \
  --bundle /absolute/offline-bundle \
  --trusted-keyring /absolute/operator-trusted/ubuntu-archive.gpg \
  --g1-sha256 INDEPENDENTLY_VERIFIED_G1_REPORT_SHA256 \
  --project-root /absolute/selected-checkout \
  --source-commit FULL_SELECTED_SOURCE_COMMIT \
  --output /absolute/external-evidence/native-inputs.json
```

Paths here are parameters, not assertions that these inputs already exist.
The output must be new and outside the project. No files are written inside
the bundle or checkout by inspection; bounded subprocess spools use `/tmp`.
Production adapters invoke fixed system `gpgv`, `dpkg`, `dpkg-query`,
`dpkg-deb`, `git`, `gzip`, `xz`, and `bzip2` without a shell. Their absence,
failure, timeout, or excessive output rejects the bundle. No package scripts
or supplied Python code are executed, and no application/GI/GTK is imported.

The operator trusts the interpreter, installed inspection tools and package
database, selected Git commit, and an independently established G1 report
digest/source-commit pair. The digest is not itself a signature. The curated
repository keyring must be a regular file outside the untrusted bundle;
claimed bundle fingerprints or authentication flags confer no trust. `gpgv`
verifies detached `Release.gpg` against the actual `Release`, requiring a
successful result and a strong-digest `VALIDSIG`. Keyring curation includes
revocation/expiry policy: `gpgv` alone does not supply that policy. The builder
must actually be Ubuntu 22.04, x86-64, glibc 2.35, CPython 3.12, with its exact
interpreter bytes/version matching G1. Inspection is not an OS snapshot lock;
the builder and bundle must remain quiescent through later freeze integration.

`bundle.json` has exactly these top-level fields; unknown fields and duplicate
JSON keys are rejected. All bundle filenames are relative, traversal-free,
bounded paths without symlink components. SHA-256 and byte counts in the
published manifest are calculated from files, not accepted as declarations.

| Field | Required schema-1 content |
| --- | --- |
| `schema_version` | Integer `1` |
| `g1` | `report`; `requirements` mapping both pinned filenames to files; `sources` and `wheels` mappings keyed by `pycairo` and `PyGObject`; `toolchain` mapping every recorded wheel filename to a file; `trace`, `verification`, `compiler_evidence` keyed by `PyGObject`, and `proxies` keyed by `cc`, `ld`, `meson`, `ninja`, `pkg-config` |
| `repositories` | List of `{id, uri, release, signature, packages, sources, packages_index, sources_index}`; file values point to supplied bytes, index values to signed Release paths |
| `sources` | List of `{repository, name, version, files}`; `files` maps every exact indexed source basename to a bundle file |
| `packages` | List of `{id, repository, archive, classification, selected, consumed}`; `id` is `name:amd64` or `name:all` |
| `non_dpkg` | Exactly one `cpython`, one `cpython-library`, and the two resource records described below |

G1's trace also requires its empty sibling `.pending` directory and no failure
marker. All actual G1 sources, binding wheels, ten toolchain wheels, requirements,
verification, trace, proxies, and Meson evidence must match the immutable
report. Existing G1 bounded metadata/backend/wheel/trace validators are reused.
An empty trace or substituted wheel cannot be repaired by native declarations.
The selected commit's two requirements files must equal the supplied bytes.

Repository `uri` is a declared HTTPS retrieval location, not proof of where
offline files were downloaded. Authenticated origin comes from signed Release
metadata: Ubuntu, jammy, an admitted jammy pocket, amd64, and component/index
paths. Signed SHA-256 entries must identify the actual uncompressed `Packages`
and `Sources` bytes. Release Date must not be future; Valid-Until is enforced
when present. Release hash identifies the snapshot; absent Valid-Until does not
establish freshness beyond its signed date. Indexes in compressed-only form
are unsupported in schema 1. Separate repository entries can describe different
components/pockets. No replacement versions or mirrors are resolved online.

Each binary archive must match one exact index record's package, version,
architecture, size, SHA-256 and filename. `dpkg-deb` supplies bounded control
and payload tar streams. Control metadata, authenticated Packages metadata,
and live `dpkg-query` installed state must agree, including dependencies and
Provides. Source/Version selects the exact source index record, all its files,
and one `.dsc`; its SHA-256 list and identity must agree with Sources. The
signed index authenticates `.dsc` bytes, not its optional developer signature.
Supported source formats are 1.0 and 3.0 (native/quilt), using tar.gz/tar.xz/
tar.bz2 and legacy diff.gz; no source is extracted, applied, or executed.

Closure roots are the twelve exact-version G1 build seeds plus package owners
of every declared resource-table root and the recorded native build tools.
The seeds alone are not closure evidence. `selected` gives one supplied
provider ID per installed Pre-Depends group followed by each Depends group,
in metadata order. Alternatives and virtual/versioned Provides are evaluated
against that provider's actual metadata; Debian version validation/comparison
uses `dpkg`, including epochs and revisions. amd64/all, `:amd64`, `:native`,
and `:any` with Multi-Arch allowed are supported. An explicit `:amd64` requires
amd64 rather than all, and `:native` excludes Multi-Arch foreign, following
dpkg's native-build architecture selection. Foreign architectures and
unexpanded source-only dependency restrictions are rejected. Every selected
provider is traversed, including cycles; unrelated supplied packages and
unreferenced source packages are rejected. Recommends/Suggests are not mandatory
installed dependency edges. Files actually consumed outside this closure must
be declared by later integration, not silently treated as optional packages.

Classifications are `bundled-runtime` (requires declared consumed files),
`build-only`, and `declared-host` (only libc6/libc-bin, no consumed files).
The latter records the resource contract's libc ABI exception, not permission
to treat GTK, GI, fonts, or desktop packages as available on the target.
X11/Xauthority, kernel and permitted desktop services remain later host checks.
Each `consumed` record is `{path, archive_path, role, transformation}`: an
absolute installed path, identical root-relative archive path, and
`transformation: identity`. Required roles are `typelib:NAME-VERSION` for all
eleven table namespaces, `native:gtk|gdk|gdkpixbuf|pango|atk|girepository|cairo`,
`font:dejavu-sans`, and `build:cc|ld|ninja|pkg-config`. Additional consumed files
use `dependency`, which cannot seed an unrelated package. Roles constrain
basenames/ownership and build-tool identities; they do not prove runtime loading.

Consumed regular bytes and every symlink hop must match archive payloads. The
manifest records each link location, exact target text and resolved target,
including links in path components and relative targets. Resolution checks
components in filesystem order (including `..` after a link); matching final
bytes cannot substitute for matching intermediate links. Implicit tar parent
directories must be actual directories, never unrecorded links. The same chain
and final regular-file identity are checked again before publication. Binary
absolute symlinks are interpreted within the package root, never extracted;
source absolute links, escaping links, special/sparse files and members below
links are rejected. A consumed link must resolve within the same package's
payload, with at most 40 hops; cross-package consumed links are unsupported
and must not be replaced with guessed bytes. Canonical real-file declarations
can avoid an unnecessary alias. No stripping or template rendering is allowed
in this input manifest. Later G2 must record permitted transformations and
their actual output identities separately.

`non_dpkg` records contain `{kind, path, bundle_path, transformation}` with
identity-only copies of the running canonical interpreter and its sysconfig
shared library. Each `project-resource` additionally has `project_path`, exactly
the CSS or fonts.conf.in resource-table path; bytes must match both the live
file and `git show` for the selected commit. Python wheels are separately
identified under G1, never assigned invented dpkg ownership. These records are
not a claim that the complete CPython standard-library or final frozen set has
been inventoried. The two project resources are not implemented by Slice A;
their absence blocks a real complete manifest until their implementation slice.

| Bound | Schema-1 limit |
| --- | --- |
| JSON input/output; uncompressed index | 16 MiB each; 256 MiB each |
| Regular input/archive/member; unique bundle bytes | 512 MiB each; 8 GiB total |
| Repositories; packages/source identities; bundle/consumed files | 8; 512 each; 20,000 each |
| Index/checksum records; dependency edges; pathname | 100,000; 8,192; 4,096 UTF-8 bytes |
| Metadata paragraph/line, captured control, signatures/keyring | 1 MiB each; 256 fields per paragraph; control budgets count encoded bytes |
| Tar traversal; declared content/decompressed stream | 100,000 headers; 2 GiB per stream |
| PAX local/global and GNU long-name/link payloads | 1 MiB cumulative per tar, charged before internal decoding; 100,000 PAX records; 40 nested extended headers |
| Consumed link traversal; JSON output nesting | 40 hops; 64 levels |
| External stdout/stderr; cumulative produced bytes | Metadata 1 MiB or tar 2 GiB (Git input 512 MiB); stderr 1 MiB; 16 GiB cumulative |
| External execution | 20,000 commands; 30 seconds each; 1 GiB child address space; 31 CPU seconds; xz dictionary 512 MiB |
| Validation | 30-minute cooperative overall deadline, checked while reading/inspecting |

Compressed size and authenticated hash precede archive subprocesses; output
bounds precede tar parsing. Tar inspection iterates without `getmembers()` or
extraction, charges hidden extended headers, and rejects truncation and hidden
concatenated content. GNU sparse headers and GNU/SCHILY PAX sparse markers,
including empty maps, are rejected before internal sparse processing. Ordinary
PAX record lengths/counts are validated before the library decodes them.
Control indexes are consumed line by line, with line/paragraph byte budgets,
field and record counts checked before further allocation. LF/CRLF records and
space/tab continuations remain supported; bounded continuation fragments are
joined only when the paragraph completes. Paragraph budgets include field names
and encoded line terminators. Limits are fail-closed supported-input limits,
not an empirical assertion that an as-yet-uncollected full native corpus fits them.
Consumed files, installed metadata, trusted keyring and supplied file hashes
are rechecked before publication to detect ordinary drift.

Only a fully validated report gains `native_package_archives.availability:
validated-offline`, scoped to `declared-input-closure` in the new manifest.
Completion checks encoded JSON size without constructing large string tokens,
then streams deterministic, sorted, ASCII-escaped JSON to a private adjacent
temporary file under a running byte budget. Escapes, non-ASCII characters,
pretty-print whitespace and the final newline count toward the 16-MiB limit.
Only complete output is fsynced and exclusively hard-linked to the new output
name. Failure returns nonzero and never replaces existing evidence or publishes
partial JSON.
Temporary cleanup is best effort after successful publication; no directory
fsync/crash-durability or concurrent-modifier guarantees are claimed.

Later G2 integration must compare PyInstaller's actual collected inputs,
GIRepository selection, ELF dependency closure, CPython files, destinations,
spec/hooks, and transformed outputs with this declared set and selected source
commit before freezing/publication. Any extra, missing or changed input blocks
that integration. Slice A cannot prove that reconciliation, standalone
operation, the helper topology, redistribution completeness, or native tray
interaction. It does not enable G2–G7 in the existing runner.

### Existing G1 and release evidence

G1 records resolved Python distributions; selected native package versions;
requirement, downloaded-source and built-wheel hashes; source identities; raw
GI/native versions; and the canonical executable/hash/version identities of
the selected compiler, linker, Meson, Ninja and pkg-config. The explicitly
selected interpreter invocation is retained even when its canonical binary is
also recorded. These newly observed hashes are build evidence, not a
pre-existing trust lock. Missing required G1 evidence fails the gate.

Installed native package versions do not prove the hashes or sources of the
downloaded `.deb` archives. G1 records that archive provenance as unavailable.
Exact native archives, repository snapshot identities and hashes become
mandatory before G2 freezes any package; their absence does not masquerade as
G1 evidence. Slice 8 assembles the final release provenance from that earlier
evidence; it does not defer the G2 prerequisite.

G1's tool-selection report is evidence only when configured executable
identities, compiler-driver linker evidence, backend-appropriate evidence, and
the execution trace are all present and consistent.
A host `ld` lookup is not proof of the linker selected by the compiler.
Pycairo's setuptools build has no Meson directory or compiler introspection;
its evidence is the validated source backend, completed compiler/linker trace,
and resulting wheel. PyGObject uses its persistent Meson-Python `build-dir`, so
G1 collects Meson's compiler introspection immediately after that wheel build.
Missing backend evidence or a trace for the wrong executable fails G1;
configured candidates remain descriptive until observed in a completed build.
For the pinned GCC path, `CC_LD=bfd` is the supported Meson selector. Meson
records the compiler proxy alone in `linker_exelist`; its `linker_id=ld.bfd`
records the detected linker family. A private `ld.bfd` proxy records actual
linker execution and delegates unchanged to the canonical linker. The compiler
proxy supplies GCC's documented first-precedence `-B` search prefix together
with `-fuse-ld=bfd`; an explicit G1 compile/link fixture and per-operation token
prove that the driver, rather than a direct proxy call, reached that linker.
Proxies preserve arguments and standard streams, distinguish an ordinary exit
143 from actual SIGTERM, forward catchable termination to their child process
group, and reap it; SIGKILL cannot be handled by a killed proxy. A successful
child whose evidence recording fails yields proxy exit 74: this is an
instrumentation failure, not transparent preservation of child exit 0.
Existing nonzero and signal dispositions remain preserved. Meson's
`cc -Wl,--version` query completes normally without becoming build evidence.
Each binding's wheel phase records its source and produced wheel and accepts
only completed operations with freshly produced outputs. A watched output-write
event distinguishes an identical-byte rebuild from unchanged stale output;
overflow, premature watch loss, and malformed events invalidate freshness.
Each proxy invocation creates a uniquely named pending entry before child
launch and clears it only after any required completion record is written.
An incomplete entry or separate recording-failure marker blocks provenance
publication even when the backend ignores proxy status; no persistence beyond
the observed work-root filesystem state is claimed. The canonical G1 work root
is limited to 128 bytes and printable ASCII before building; complete encoded
native records have a 32-KiB limit, sufficient for the pinned 38-object
PyGObject target, within the 4-MiB trace budget.
Captured content identities connect source-archive C bytes to compiled objects,
driver/linker output and the wheel extension's ELF `.text` section. The code
fingerprint survives backend copying and ELF metadata edits; it is bounded
evidence, not a substitute for native G1 compilation. Pycairo requires pkg-config, C
compilation, compiler-driver linking, and linker execution, but rejects Meson
or Ninja evidence. PyGObject additionally requires Meson setup, Ninja execution,
and Meson's compiler schema naming the same compiler proxy and `ld.bfd` choice.
Queries, probes, failed or output-less commands, stale sections, and unmatched
driver/linker tokens cannot satisfy build evidence.

G1 streams each regular size-bounded `.tar.gz` through member-count, declared
content, metadata, and decompression/traversal budgets. PAX local/global and GNU
long-name/link headers are charged before the archive library decodes them;
the overall decompressed-stream cap still applies. G1 reads exactly one
`PKG-INFO` and `pyproject.toml`, without extraction or execution. It reads
`METADATA` plus `WHEEL` from each bounded wheel and requires exactly one valid
`Wheel-Version` header. Those backend identities, compatible wheel tags, exact
requirement pins, installed versions, filenames, and hashes must agree.
Duplicate, substituted, malformed, oversized, ambiguous, or incompatible
inputs fail before the exclusive success report is created.

The eventual distribution must include exact source provenance and applicable
copyright/license notices, plus corresponding-source and replacement/rebuild
materials required by the dependency set and linking model. A notices file by
itself is not proof of compliance. Final legal interpretation and redistribution
clearance remain an explicit release gate.

## Dependency-ordered implementation slices

Every proposed file is named here so a later implementer does not have to
invent a harness. Existing files are marked “modify”; all others are new.

| Slice | Exact files | Scope and prerequisite gate | Independently committable; remaining gap |
| --- | --- | --- | --- |
| 1A | new `docs/linux-tray-design.md`, `docs/linux-tray-acceptance.md`, `requirements-linux-tray.txt`, `requirements-linux-tray-build.txt`, `packaging/linux/provision_tray_lab.sh`, `packaging/linux/run_tray_gates.sh`, `packaging/linux/probe/verify_bindings.py`, `packaging/linux/capture_tray_provenance.py`, and `tests/test_linux_tray_gate_configuration.py` | contract, pins, provisioning, G1 runner/verifier/provenance and mocks | yes; at initial Slice 1A publication, G1 was still unexecuted |
| 1B | no repository change; evidence below the operator's G1 work root | run G1 on disposable Ubuntu 22.04/x86-64 with trusted CPython 3.12 | evidence gate only; no frozen package |
| 2 | new `packaging/linux/tray_resource_manifest.py`, `packaging/linux/hooks/hook-gi.py`, `packaging/linux/runtime_hooks/pyi_rth_linux_tray.py`, `packaging/linux/resources/theme/LMT/gtk-3.0/gtk.css`, `packaging/linux/resources/fonts.conf.in`, `application/services/linux_tray_protocol.py`, root `linux_tray_bootstrap.py`, and corresponding `tests/test_linux_tray_protocol.py`, `tests/test_linux_tray_packaging_contract.py` | implement the table above, collect the G2-required native archive/source/hash evidence, establish the H-only environment, protocol codec, and early private-helper dispatch; requires G1 and native archive evidence | yes; no executable probe or production GTK adapter |
| 3A | new `packaging/linux/probe/linux_tray_probe.py`, `packaging/linux/LinuxTrayProbe.spec`, `packaging/linux/inspect_tray_probe.py`; modify `packaging/linux/run_tray_gates.sh`; add `tests/test_linux_tray_probe_tooling.py` | build/archive/topology driver and G2 | yes; no native interaction |
| 3B | new `packaging/linux/lab/run_restricted_tray_lab.sh`, `xsettings_fixture.py`, `native_tray_driver.py`, `host_module_fixture.c`, `parent_death_probe.py`; modify gate runner/provisioner; add `tests/test_linux_tray_lab_configuration.py` | restricted mount/network/display lab, inert module and actual XTEST/AT-SPI driver for G3; requires G2 | yes; probe only, production tray absent |
| 4 | new `application/services/linux_gtk_tray_adapter.py`, `linux_tray_supervisor_service.py`, `linux_tray_status_service.py`; modify `application_instance_service.py`; add three matching test modules | H main loop, P supervisor, state record, cleanup quarantine, initially unselected | yes; application still uses existing tray |
| 5 | modify `application_browser_service.py`; strengthen `tests/test_application_browser_service.py` | Linux external-browser child environment only | yes; GTK adapter still unselected |
| 6 | modify `run.py`, `application_launcher_service.py`, `application_tray_service.py`, `LeagueMasteryTracker-linux-onefile.spec`, gate runner and existing matching tests; add `tests/test_linux_gtk_tray_integration.py` | deterministic selection and production integration; run G4 then restricted packaged G5 | yes only after G4/G5; clean desktop and Windows pending |
| 7 | new `packaging/windows/run_tray_gate.ps1`; modify `.github/workflows/linux-ci.yml` only after recorded manual G6/G7 procedures pass | implement the exact Windows regression driver, admit repeatable noninteractive portions to CI, and record manual results separately | yes; release still blocked on provenance/licensing |
| 8 | new `THIRD_PARTY_NOTICES.md`, `packaging/linux/tray-sources.json`, `packaging/linux/rebuild_linux_tray.md`; release artifacts outside Git | source/hash/notices/relink/rebuild deliverables and legal review | final distribution gate |

No architectural choice in the control flow is intentionally delegated to the
implementer. Compilation, exact onefile topology, standalone completeness,
host-module exclusion, XWayland support, panel re-embedding, native interaction,
and redistribution clearance remain empirical gates, not asserted outcomes.
