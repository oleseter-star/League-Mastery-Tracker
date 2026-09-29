#!/usr/bin/env python3
"""Offline native-input verification; this is not the G2 freezer or collector."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
try:
    import resource
except ImportError:  # The offline validator itself supports Linux builders only.
    resource = None
import selectors
import signal
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
from urllib.parse import urlsplit


SCHEMA = 1
MIB = 1024 * 1024
MAX_JSON = 16 * MIB
MAX_INDEX = 256 * MIB
MAX_FILE = 512 * MIB
MAX_BUNDLE = 8192 * MIB
MAX_STREAM = 2048 * MIB
MAX_EXPANDED = 16384 * MIB
MAX_METADATA = MIB
MAX_MEMBERS = 100_000
MAX_PACKAGES = 512
MAX_REPOSITORIES = 8
MAX_RECORDS = 100_000
MAX_EDGES = 8192
MAX_FILES = 20_000
MAX_PATH = 4096
COMMAND_SECONDS = 30
VALIDATION_SECONDS = 1800
MAX_COMMANDS = 20_000
MAX_LINK_HOPS = 40
MAX_JSON_DEPTH = 64
NAME = r"[a-z0-9][a-z0-9+.-]+"
RELATION = re.compile(
    rf"^({NAME})(?::(any|native|amd64))?(?:\s*\(\s*(<<|<=|=|>=|>>)\s*([^ ()\s]+)\s*\))?$"
)
CLASSES = {"bundled-runtime", "build-only", "declared-host"}
HOST_PACKAGES = {"libc6", "libc-bin"}
TYPELIBS = {
    "Gtk-3.0", "Gdk-3.0", "GdkX11-3.0", "GdkPixbuf-2.0", "Gio-2.0",
    "GLib-2.0", "GObject-2.0", "Atk-1.0", "Pango-1.0", "HarfBuzz-0.0", "cairo-1.0",
}
NATIVE_ROLES = {
    "gtk": "libgtk-3.so", "gdk": "libgdk-3.so", "gdkpixbuf": "libgdk_pixbuf-2.0.so",
    "pango": "libpango-1.0.so", "atk": "libatk-1.0.so",
    "girepository": "libgirepository-1.0.so", "cairo": "libcairo.so",
}
PROJECT_RESOURCES = {
    "packaging/linux/resources/theme/LMT/gtk-3.0/gtk.css",
    "packaging/linux/resources/fonts.conf.in",
}
PACKAGE_FIELDS = (
    "Package", "Version", "Architecture", "Multi-Arch", "Depends", "Pre-Depends",
    "Provides", "Source",
)


class Invalid(ValueError):
    """Incomplete, unsupported, or contradictory supplied evidence."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict), "Expected an object")
    require(set(required) <= value.keys() <= set(required) | set(optional),
            "Missing or unknown schema fields")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            "Invalid SHA-256")
    return value


def relative(value):
    require(isinstance(value, str) and 0 < len(value.encode()) <= MAX_PATH,
            "Invalid path length")
    require(value.isprintable() and "\\" not in value, "Unsafe path characters")
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in {"", ".", ".."}
            for p in value.split("/")), "Unsafe relative path")
    return value


def absolute(value):
    require(isinstance(value, str) and value.startswith("/"), "Expected absolute path")
    relative(value[1:])
    return Path(value)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def json_data(content):
    require(len(content) <= MAX_JSON, "JSON exceeds limit")
    return json.loads(content, object_pairs_hook=no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid("Invalid JSON number")))


def deb822(content, budget=None):
    """Bounded, duplicate-rejecting Debian control paragraphs."""
    require(len(content) <= MAX_INDEX and b"\0" not in content, "Invalid control size/content")
    budget = budget or Budget()
    result, record, keys, key = [], {}, set(), None
    position, paragraph_bytes = 0, 0
    while position <= len(content):
        budget.check()
        end = content.find(b"\n", position, position + MAX_METADATA + 2)
        if end < 0:
            end = len(content)
        require(end - position <= MAX_METADATA, "Control line exceeds limit")
        line_bytes = end - position + (end < len(content))
        raw = content[position:end]
        position = end + 1
        require(position - 1 <= MAX_INDEX, "Cumulative control metadata exceeds limit")
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        if not raw:
            if record:
                result.append({name: "".join(parts) for name, parts in record.items()})
                record, keys, key, paragraph_bytes = {}, set(), None, 0
            continue
        require(record or len(result) < MAX_RECORDS, "Too many control records")
        paragraph_bytes += line_bytes
        require(paragraph_bytes <= MAX_METADATA, "Control paragraph exceeds limit")
        line = raw.decode("utf-8")
        if line[0] in " \t":
            require(key is not None, "Orphan control continuation")
            record[key].append("\n" + line[1:])
        else:
            key, sep, value = line.partition(":")
            require(sep and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", key), "Invalid control field")
            require(key.lower() not in keys and len(record) < 256, "Duplicate/excessive control fields")
            keys.add(key.lower())
            record[key] = [value.strip()]
    if record:
        result.append({name: "".join(parts) for name, parts in record.items()})
    return result


def one_record(content, budget=None):
    records = deb822(content, budget)
    require(len(records) == 1, "Expected one control paragraph")
    return records[0]


def checksums(value):
    require(isinstance(value, str), "Missing SHA-256 index")
    result = {}
    for line in value.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        require(len(parts) == 3, "Invalid checksum record")
        checksum, size, path = parts
        sha(checksum)
        relative(path)
        require(size.isdecimal() and len(size) < 12, "Invalid indexed size")
        require(path not in result and len(result) < MAX_RECORDS, "Duplicate/excessive checksums")
        result[path] = {"sha256": checksum, "size": int(size)}
    require(result, "Empty checksum index")
    return result


def identity(path, limit=MAX_FILE):
    path = Path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "Not a bounded regular file")
        size, hashed = 0, hashlib.sha256()
        while block := stream.read(min(MIB, limit - size + 1)):
            size += len(block)
            require(size <= limit, "File grew beyond limit")
            hashed.update(block)
        after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns) and size == before.st_size,
                "Input changed during inspection")
    return {"size": size, "sha256": hashed.hexdigest()}


class Budget:
    def __init__(self):
        self.expanded = 0
        self.started = time.monotonic()
        self.commands = 0

    def check(self):
        require(time.monotonic() - self.started <= VALIDATION_SECONDS, "Validation deadline exceeded")

    def charge(self, size):
        self.check()
        self.expanded += size
        require(self.expanded <= MAX_EXPANDED, "Total decompression budget exceeded")


class System:
    """Only read-only tools; no shell, package execution, or network adapters."""
    def __init__(self, budget):
        self.budget = budget

    @contextmanager
    def output(self, argv, limit=MAX_METADATA, accepted=(0,)):
        require(resource is not None and sys.platform.startswith("linux"), "Inspection tools require Linux")
        self.budget.check()
        self.budget.commands += 1
        require(self.budget.commands <= MAX_COMMANDS, "Too many external commands")
        require(Path(argv[0]).is_absolute(), "Tool must have an absolute path")

        def restrict():
            resource.setrlimit(resource.RLIMIT_AS, (1024 * MIB, 1024 * MIB))
            cpu_seconds = max(1, int(COMMAND_SECONDS) + 1)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))

        with tempfile.TemporaryDirectory(prefix="lmt-native-tool-", dir="/tmp") as home:
            with tempfile.TemporaryFile(dir=home) as result:
                process = subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": home},
                    cwd=home, start_new_session=True, preexec_fn=restrict,
                )
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ, "out")
                        selector.register(process.stderr, selectors.EVENT_READ, "err")
                        counts = {"out": 0, "err": 0}
                        deadline = time.monotonic() + COMMAND_SECONDS
                        while selector.get_map():
                            require(time.monotonic() < deadline, "External producer timed out")
                            self.budget.check()
                            for key, _ in selector.select(0.05):
                                block = os.read(key.fileobj.fileno(), 65536)
                                if not block:
                                    selector.unregister(key.fileobj)
                                    continue
                                counts[key.data] += len(block)
                                require(counts[key.data] <= (limit if key.data == "out" else MAX_METADATA),
                                        "External producer output exceeds limit")
                                self.budget.charge(len(block))
                                if key.data == "out":
                                    result.write(block)
                        code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                        require(code in accepted, "External producer failed")
                finally:
                    # Also terminate descendants retaining pipes after their leader exited.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    process.stdout.close()
                    process.stderr.close()
                result.seek(0)
                yield result, code

    def run(self, argv, limit=MAX_METADATA, accepted=(0,)):
        with self.output(argv, limit, accepted) as (stream, code):
            return stream.read(limit + 1), code

    def version(self, left, operator, right):
        for value in (left, right):
            require(isinstance(value, str) and 0 < len(value) <= 256 and
                    re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", value), "Invalid Debian version")
            self.run(["/usr/bin/dpkg", "--validate-version", value])
        require(operator in {"<<", "<=", "=", ">=", ">>"}, "Unsupported version operator")
        _, code = self.run(["/usr/bin/dpkg", "--compare-versions", left, operator, right], accepted=(0, 1))
        return code == 0

    def installed(self, package_id):
        names = ("Status", *PACKAGE_FIELDS)
        fmt = "".join(f"{name}: ${{{name}}}\n" for name in names)
        output, _ = self.run(["/usr/bin/dpkg-query", "--show", "--showformat=" + fmt, package_id])
        return one_record(output, self.budget)

    def builder(self):
        return {
            "os_release": Path("/etc/os-release").read_text(),
            "architecture": platform.machine(), "glibc": os.confstr("CS_GNU_LIBC_VERSION"),
            "implementation": platform.python_implementation(), "version": platform.python_version(),
            "interpreter": str(Path(sys.executable).resolve(strict=True)),
            "library": str((Path(sysconfig.get_config_var("LIBDIR")) /
                            sysconfig.get_config_var("LDLIBRARY")).resolve(strict=True)),
        }

    def committed(self, project, commit, path):
        return self.run(["/usr/bin/git", "-C", str(project), "show", f"{commit}:{path}"], MAX_FILE)[0]

    def authenticate(self, keyring, signature, release):
        with tempfile.TemporaryDirectory(prefix="lmt-native-gpg-", dir="/tmp") as home:
            output, _ = self.run(["/usr/bin/gpgv", "--homedir", home, "--keyring", str(keyring),
                                  "--status-fd", "1", str(signature), str(release)])
        valid = []
        for line in output.decode("ascii").splitlines():
            if line.startswith("[GNUPG:] VALIDSIG "):
                parts = line.split()
                require(len(parts) >= 11 and re.fullmatch(r"[0-9A-F]{40,64}", parts[2]),
                        "Malformed signature status")
                require(parts[9] in {"8", "9", "10"}, "Weak repository digest algorithm")
                valid.append(parts[2])
        require(valid, "No verified repository signature")
        return sorted(set(valid))


def tar_path(value):
    while value.startswith("./"):
        value = value[2:]
    return relative(value.rstrip("/"))


def link_destination(name, target, hard=False, allow_absolute=False):
    require(target and target.isprintable() and "\\" not in target and len(target.encode()) <= MAX_PATH,
            "Unsafe link target")
    require(allow_absolute or not target.startswith("/"), "Absolute source archive link is unsupported")
    # Binary package absolute links refer to the declared package root, never an
    # archive-controlled host path opened by this inspector.
    parts = [] if hard or target.startswith("/") else list(PurePosixPath(name).parent.parts)
    for part in target.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            require(parts, "Archive link escapes root")
            parts.pop()
        else:
            parts.append(part)
    require(parts, "Archive link resolves to root")
    return "/".join(parts)


def inspect_tar(stream, budget, wanted=(), allow_absolute_links=False):
    """Inspect streams without extracting paths; charge extended headers before decoding."""
    members, capture = {}, {}
    count, metadata, declared, pax_records, depth = 0, 0, 0, 0, 0
    stream.seek(0, os.SEEK_END)
    length = stream.tell()
    require(1024 <= length <= MAX_STREAM and length % 512 == 0, "Truncated/oversized tar stream")
    stream.seek(-1024, os.SEEK_END)
    require(stream.read(1024) == b"\0" * 1024, "Missing tar end markers")
    stream.seek(0)

    class Header(tarfile.TarInfo):
        def _proc_member(self, archive):
            nonlocal count, metadata, declared, pax_records, depth
            require(self.type != tarfile.GNUTYPE_SPARSE, "Sparse tar format is unsupported")
            require(self.size >= 0, "Negative tar size")
            count += 1
            declared += self.size
            budget.check()
            require(count <= MAX_MEMBERS and declared <= MAX_STREAM, "Tar traversal limit exceeded")
            pax_types = {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE}
            if self.type in {*pax_types, tarfile.GNUTYPE_LONGNAME,
                             tarfile.GNUTYPE_LONGLINK}:
                metadata += self.size
                require(metadata <= MAX_METADATA, "Extended tar metadata exceeds limit")
            if self.type in pax_types:
                # Check bounded raw records before tarfile can invoke any sparse
                # map handler (including maps stored outside the PAX payload).
                start = archive.fileobj.tell()
                payload = archive.fileobj.read(self.size)
                require(len(payload) == self.size, "Truncated PAX metadata")
                position = 0
                while position < len(payload):
                    budget.check()
                    if payload[position] == 0:
                        require(not payload[position:].strip(b"\0"), "Malformed PAX padding")
                        break
                    prefix = re.match(rb"([0-9]{1,10}) ", payload[position:position + 12])
                    require(prefix is not None, "Malformed PAX record")
                    size = int(prefix[1])
                    end = position + size
                    require(size >= 5 and end <= len(payload) and payload[end - 1] == 10, "Malformed PAX length")
                    equals = payload.find(b"=", position + prefix.end(), end - 1)
                    require(equals > position + prefix.end(), "Malformed PAX field")
                    pax_records += 1
                    require(pax_records <= MAX_RECORDS, "Too many PAX records")
                    keyword = payload[position + prefix.end():equals]
                    value = payload[equals + 1:end - 1]
                    require(not (keyword == b"GNU.sparse" or keyword.startswith(b"GNU.sparse.") or
                                 keyword in {b"SCHILY.realsize", b"SCHILY.holesdata"} or
                                 keyword == b"SCHILY.filetype" and value == b"sparse"),
                            "Sparse PAX format is unsupported")
                    position = end
                archive.fileobj.seek(start)
            depth += 1
            try:
                require(depth <= 40, "Too many nested extended tar headers")
                return super()._proc_member(archive)
            finally:
                depth -= 1

    with tarfile.open(fileobj=stream, mode="r:", tarinfo=Header) as archive:
        for member in archive:
            if member.name in {".", "./"} and member.isdir():
                continue
            name = tar_path(member.name)
            require(name not in members and member.size <= MAX_FILE and member.sparse is None,
                    "Duplicate, oversized, or sparse tar entry")
            if member.isdir():
                entry = {"type": "directory"}
            elif member.issym() or member.islnk():
                entry = {"type": "hardlink" if member.islnk() else "symlink", "target": member.linkname,
                         "resolved": link_destination(name, member.linkname, member.islnk(), allow_absolute_links)}
            elif member.isfile():
                hashed, size, content = hashlib.sha256(), 0, bytearray()
                with archive.extractfile(member) as payload:
                    while block := payload.read(MIB):
                        budget.check()
                        hashed.update(block)
                        size += len(block)
                        if name in wanted:
                            require(size <= MAX_METADATA, "Captured tar metadata exceeds limit")
                            content.extend(block)
                require(size == member.size, "Truncated tar payload")
                entry = {"type": "file", "size": size, "sha256": hashed.hexdigest()}
                if name in wanted:
                    capture[name] = bytes(content)
            else:
                raise Invalid("Unsupported special tar member")
            members[name] = entry
        end = archive.offset
    # Tarfile stops at the end marker; reject truncated padding or hidden concatenated archives.
    stream.seek(end)
    while block := stream.read(MIB):
        require(not block.strip(b"\0"), "Trailing tar content")
        budget.check()
    for name in members:
        for parent in PurePosixPath(name).parents:
            if str(parent) in members:
                require(members[str(parent)]["type"] == "directory", "Member beneath archive link/file")
    return members, capture


def payload_file(members, name):
    seen = set()
    while True:
        require(name in members and name not in seen and len(seen) < 40, "Missing or cyclic archive link")
        seen.add(name)
        entry = members[name]
        if entry["type"] == "file":
            return entry
        require(entry["type"] in {"symlink", "hardlink"}, "Expected file payload")
        name = entry["resolved"]


def consumed_chain(members, name):
    """Resolve a same-package chain component by component, without resolve()."""
    records, links, active = {}, [], set()
    steps = 0

    def entry(path):
        value = members.get(path)
        if value is None:
            # Tar directories may be implicit. A missing link or file never is.
            require(stat.S_ISDIR(os.lstat("/" + path).st_mode), "Missing authenticated chain hop")
            value = {"type": "directory"}
        records[path] = value
        return value

    def walk(parts, stack):
        nonlocal steps
        for index, part in enumerate(parts):
            steps += 1
            require(steps <= MAX_PATH * (MAX_LINK_HOPS + 1), "Consumed path traversal exceeds limit")
            if part in {"", "."}:
                continue
            if part == "..":
                require(stack, "Consumed link escapes root")
                stack.pop()
                continue
            path = "/".join([*stack, part])
            relative(path)
            archived, actual = entry(path), os.lstat("/" + path)
            if archived["type"] == "symlink":
                require(stat.S_ISLNK(actual.st_mode) and os.readlink("/" + path) == archived["target"],
                        "Consumed symlink hop differs from archive")
                require(path not in active and len(links) < MAX_LINK_HOPS, "Cyclic/excessive consumed links")
                active.add(path)
                hop = {"path": "/" + path, "target": archived["target"]}
                links.append(hop)
                target = archived["target"]
                # Validate characters/lexical escape; walk still resolves links
                # before subsequent '..', as the actual filesystem does.
                link_destination(path, target, allow_absolute=True)
                stack = walk(target.split("/"), [] if target.startswith("/") else stack.copy())
                active.remove(path)
                hop["resolved_path"] = "/" + "/".join(stack)
                require(stack, "Consumed link resolves to root")
                archived = entry("/".join(stack))
            else:
                require(stat.S_ISDIR(actual.st_mode) if archived["type"] == "directory" else
                        stat.S_ISREG(actual.st_mode) and archived["type"] in {"file", "hardlink"},
                        "Consumed path type differs from archive")
                stack.append(part)
            if index < len(parts) - 1:
                require(archived["type"] == "directory", "Consumed path passes through a file")
        return stack

    terminal = "/".join(walk(relative(name).split("/"), []))
    target, seen = terminal, set()
    while True:
        require(target in members and target not in seen and len(seen) < MAX_LINK_HOPS,
                "Missing/cyclic archive content target; cross-package links are unsupported")
        seen.add(target)
        archived = entry(target)
        if archived["type"] == "file":
            break
        require(archived["type"] == "hardlink", "Unsupported archive content target")
        target = archived["resolved"]
    require(identity("/" + terminal) == {k: archived[k] for k in ("size", "sha256")},
            "Installed/archive payload mismatch")
    return archived, {"records": records, "links": links, "terminal": "/" + terminal}


def package_metadata(record):
    name, version, arch = (record.get(k, "") for k in ("Package", "Version", "Architecture"))
    require(re.fullmatch(NAME, name) and arch in {"amd64", "all"}, "Unsupported package identity/architecture")
    require(record.get("Multi-Arch", "no") in {"", "no", "same", "foreign", "allowed"}, "Invalid Multi-Arch")
    require(version, "Missing exact package version")
    return name + ":" + arch


def relations(value):
    if not value:
        return []
    require(len(value) <= MAX_METADATA, "Dependency field exceeds limit")
    result = []
    for group in value.replace("\n", " ").split(","):
        options = []
        for option in group.split("|"):
            match = RELATION.fullmatch(option.strip())
            require(match is not None, "Unsupported binary dependency syntax")
            options.append(match.groups())
        result.append(options)
        require(len(result) <= MAX_EDGES, "Too many dependency groups")
    return result


def satisfies(option, provider, system):
    name, qualifier, operator, version = option
    arch = provider["Architecture"]
    if qualifier == "any" and provider.get("Multi-Arch") != "allowed":
        return False
    # Match dpkg's native-build KnownFacts architecture selection: an explicit
    # architecture is not Architecture: all, and :native excludes foreign.
    if qualifier == "amd64" and arch != "amd64":
        return False
    if qualifier == "native" and provider.get("Multi-Arch") == "foreign":
        return False
    if qualifier in {None, "native"} and arch not in {"amd64", "all"}:
        return False
    candidates = [(provider["Package"], provider["Version"])]
    for group in relations(provider.get("Provides", "")):
        require(len(group) == 1, "Provides cannot contain alternatives")
        p_name, p_arch, p_op, p_version = group[0]
        require(p_arch is None and p_op in {None, "="}, "Unsupported Provides syntax")
        if p_version is not None:
            require(system.version(p_version, "=", p_version), "Invalid provided version")
        candidates.append((p_name, p_version))
    return any(p_name == name and (operator is None or p_version is not None and
               system.version(p_version, operator, version)) for p_name, p_version in candidates)


def validate_closure(packages, seeds, system):
    edges, reached, queue = [], set(), list(seeds)
    while queue:
        package_id = queue.pop()
        if package_id in reached:
            continue
        require(package_id in packages, "Missing closure root/provider")
        reached.add(package_id)
        package = packages[package_id]
        groups = [(kind, alternatives) for kind in ("Pre-Depends", "Depends")
                  for alternatives in relations(package["metadata"].get(kind, ""))]
        require(len(package["selected"]) == len(groups), "Selected provider count differs from dependencies")
        for (kind, alternatives), chosen in zip(groups, package["selected"]):
            require(isinstance(chosen, str) and chosen in packages, "Missing selected dependency")
            require(any(satisfies(option, packages[chosen]["metadata"], system) for option in alternatives),
                    "Selected provider does not satisfy dependency")
            edges.append({"from": package_id, "kind": kind, "alternatives": alternatives, "to": chosen})
            require(len(edges) <= MAX_EDGES, "Dependency edge limit exceeded")
            queue.append(chosen)
    require(reached == packages.keys(), "Unrelated packages outside selected closure")
    return edges


class Bundle:
    def __init__(self, root, budget):
        self.root = Path(root).resolve(strict=True)
        require(self.root.is_dir(), "Bundle root is not a directory")
        self.budget, self.files, self.total = budget, {}, 0

    def path(self, name):
        path = self.root
        for part in relative(name).split("/"):
            path = path / part
            require(not path.is_symlink(), "Bundle paths must not traverse symlinks")
        return path

    def file(self, name, limit=MAX_FILE, expected=None):
        self.budget.check()
        path = self.path(name)
        observed = identity(path, limit)
        if expected is not None:
            require(observed == {k: expected[k] for k in ("sha256", "size")}, "File/index/G1 identity mismatch")
        if name not in self.files:
            self.total += observed["size"]
            require(self.total <= MAX_BUNDLE and len(self.files) < MAX_FILES, "Bundle byte/file limit exceeded")
            self.files[name] = observed
        require(self.files[name] == observed, "Bundle changed during inspection")
        return path

    def read(self, name, limit=MAX_METADATA, expected=None):
        path = self.file(name, limit, expected)
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
        require(len(content) <= limit and digest(content) == self.files[name]["sha256"], "Input changed")
        return content

    def finish(self):
        for name, expected in list(self.files.items()):
            self.file(name, expected=expected)


def source_identity(record):
    value = record.get("Source") or record["Package"]
    match = re.fullmatch(rf"({NAME})(?: \(([^ ()]+)\))?", value)
    require(match is not None, "Invalid source-package identity")
    return match[1], match[2] or record["Version"]


def repositories(entries, bundle, system, keyring):
    require(isinstance(entries, list) and 0 < len(entries) <= MAX_REPOSITORIES, "Invalid repository count")
    result = {}
    for item in entries:
        fields(item, {"id", "uri", "release", "signature", "packages", "sources", "packages_index", "sources_index"})
        name = relative(item["id"])
        require("/" not in name and name not in result, "Duplicate repository")
        uri = urlsplit(item["uri"])
        require(uri.scheme == "https" and uri.hostname and not uri.username and not uri.password and
                not uri.query and not uri.fragment, "Invalid declared repository URI")
        release = bundle.file(item["release"], MAX_METADATA)
        signature = bundle.file(item["signature"], MAX_METADATA)
        fingerprints = system.authenticate(keyring, signature, release)
        metadata = one_record(bundle.read(item["release"]), system.budget)
        require(metadata.get("Origin") == "Ubuntu" and metadata.get("Codename") == "jammy",
                "Repository is not Ubuntu jammy")
        require(metadata.get("Suite") in {"jammy", "jammy-updates", "jammy-security", "jammy-backports"},
                "Unsupported repository suite")
        require("amd64" in metadata.get("Architectures", "").split(), "Repository lacks amd64")
        timestamp = parsedate_to_datetime(metadata["Date"])
        require(timestamp.tzinfo is not None and timestamp <= datetime.now(timezone.utc), "Invalid Release date")
        if "Valid-Until" in metadata:
            expiry = parsedate_to_datetime(metadata["Valid-Until"])
            require(expiry.tzinfo is not None and timestamp <= expiry and datetime.now(timezone.utc) <= expiry,
                    "Expired repository metadata")
        indexes = checksums(metadata.get("SHA256"))
        rows = {}
        for kind in ("packages", "sources"):
            index = relative(item[kind + "_index"])
            component, _, suffix = index.partition("/")
            require(component in metadata.get("Components", "").split() and index in indexes and
                    suffix == ("binary-amd64/Packages" if kind == "packages" else "source/Sources"),
                    "Required uncompressed index is absent from Release")
            rows[kind] = deb822(bundle.read(item[kind], MAX_INDEX, indexes[index]), system.budget)
        result[name] = {"metadata": metadata, "fingerprints": fingerprints, "uri": item["uri"], **rows,
                        "release": item["release"], "signature": item["signature"],
                        "indexes": {k: item[k] for k in ("packages", "sources")}}
    return result


def inspect_deb(path, system, budget):
    with system.output(["/usr/bin/dpkg-deb", "--ctrl-tarfile", str(path)], MAX_METADATA) as (stream, _):
        _, captured = inspect_tar(stream, budget, {"control"})
    require("control" in captured, "Missing binary control record")
    control = one_record(captured["control"], system.budget)
    with system.output(["/usr/bin/dpkg-deb", "--fsys-tarfile", str(path)], MAX_STREAM) as (stream, _):
        members, _ = inspect_tar(stream, budget, allow_absolute_links=True)
    return control, members


def compare_metadata(left, right):
    for key in PACKAGE_FIELDS:
        def normalized(record):
            value = record.get(key, "")
            if key == "Multi-Arch":
                value = value or "no"
            if key == "Source":
                return source_identity(record)
            return " ".join(value.split())
        require(normalized(left) == normalized(right), "Archive/index/installed metadata mismatch: " + key)


def inspect_source(path, budget, system):
    """Source archives are authenticated first, then streamed under a global budget."""
    commands = {".gz": ["/usr/bin/gzip", "-cd"],
                ".xz": ["/usr/bin/xz", "--memlimit-decompress=512MiB", "-cd"],
                ".bz2": ["/usr/bin/bzip2", "-cd"]}
    require(path.suffix in commands, "Unsupported source compression")
    with system.output([*commands[path.suffix], "--", str(path)], MAX_STREAM) as (stream, _):
        if ".tar." in path.name:
            inspect_tar(stream, budget)
        else:
            require(path.name.endswith(".diff.gz"), "Unsupported source material")


def source_material(entries, repos, bundle, budget, system):
    require(isinstance(entries, list) and len(entries) <= MAX_PACKAGES, "Invalid source count")
    result = {}
    for item in entries:
        fields(item, {"repository", "name", "version", "files"})
        key = (item["repository"], item["name"], item["version"])
        require(key not in result and key[0] in repos, "Duplicate/unknown source identity")
        require(re.fullmatch(NAME, key[1]) and system.version(key[2], "=", key[2]), "Invalid source identity")
        records = [r for r in repos[key[0]]["sources"] if (r.get("Package"), r.get("Version")) == key[1:]]
        require(len(records) == 1, "Missing or conflicting source index record")
        record = records[0]
        relative(record["Directory"])
        expected = checksums(record.get("Checksums-Sha256"))
        require(isinstance(item["files"], dict) and set(item["files"]) == set(expected), "Incomplete source material")
        descriptors = [name for name in expected if name.endswith(".dsc")]
        require(len(descriptors) == 1, "Source descriptor missing/ambiguous")
        for name, checksum in expected.items():
            require("/" not in relative(name), "Unsafe source filename")
            path = bundle.file(item["files"][name], expected=checksum)
            require(path.name == name, "Source filename mismatch")
            if not name.endswith(".dsc"):
                inspect_source(path, budget, system)
        content = bundle.read(item["files"][descriptors[0]])
        if content.startswith(b"-----BEGIN PGP SIGNED MESSAGE-----\n"):
            # Authentication is the signed Sources -> .dsc digest, not this embedded signature.
            _, separator, content = content.partition(b"\n\n")
            require(separator and b"\n-----BEGIN PGP SIGNATURE-----" in content, "Malformed signed descriptor")
            content = content.split(b"\n-----BEGIN PGP SIGNATURE-----", 1)[0]
            content = b"\n".join(line[2:] if line.startswith(b"- ") else line for line in content.splitlines())
        descriptor = one_record(content, system.budget)
        require((descriptor.get("Source"), descriptor.get("Version")) == key[1:], "Source descriptor identity mismatch")
        require(descriptor.get("Format") in {"1.0", "3.0 (quilt)", "3.0 (native)"}, "Unsupported source format")
        require(checksums(descriptor.get("Checksums-Sha256")) ==
                {n: v for n, v in expected.items() if n != descriptors[0]}, "Source descriptor/index disagreement")
        result[key] = {"repository": key[0], "name": key[1], "version": key[2],
                       "directory": record["Directory"], "files": item["files"]}
    return result


def load_g1():
    path = Path(__file__).with_name("capture_tray_provenance.py")
    spec = importlib.util.spec_from_file_location("lmt_g1_native_validation", path)
    module = importlib.util.module_from_spec(spec)
    original = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = original
    return module


def validate_g1(item, bundle, expected_digest, project, commit, system):
    fields(item, {"report", "requirements", "sources", "wheels", "toolchain", "trace", "verification",
                  "compiler_evidence", "proxies"})
    raw = bundle.read(item["report"], MAX_JSON)
    require(digest(raw) == sha(expected_digest), "G1 report differs from trusted run digest")
    report, g1 = json_data(raw), load_g1()
    require(report["native_package_archives"] == {"availability": "unavailable", "required_before": "G2-freeze"},
            "G1 archive statement must remain unchanged")
    require(report["builder_os"] == "ubuntu-22.04" and report["architecture"] == "x86_64" and
            report["distributions"] == g1.EXPECTED_DISTRIBUTIONS, "G1 baseline/pins mismatch")
    require(set(item["requirements"]) == g1.EXPECTED_REQUIREMENTS, "Incomplete G1 requirements")
    by_name = {r["filename"]: r for r in report["requirements"]}
    require(len(by_name) == 2 and set(by_name) == g1.EXPECTED_REQUIREMENTS, "Ambiguous G1 requirements")
    requirement_paths = []
    for name, path in item["requirements"].items():
        content = bundle.read(path, MAX_METADATA, by_name[name])
        require(content == system.committed(project, commit, name), "Requirements differ from selected source")
        require(bundle.path(path).name == name, "Requirement filename mismatch")
        requirement_paths.append(bundle.path(path))
    g1._requirements_inventory(requirement_paths)
    source_hashes, wheel_hashes = {}, {}
    for kind in ("sources", "wheels"):
        require(set(item[kind]) == set(report[kind]) == g1.REQUIRED_SOURCES, "Incomplete binding inputs")
        for name, path in item[kind].items():
            file = bundle.file(path, g1.MAX_ARCHIVE_BYTES, report[kind][name])
            require(file.name == report[kind][name]["filename"], "G1 binding filename mismatch")
            if kind == "sources":
                metadata = g1._source_metadata(file, name, g1.EXPECTED_DISTRIBUTIONS[name])
                source_hashes[name] = metadata["source_input_hashes"]
                require(report[kind][name]["official_project_url"] == g1.EXPECTED_SOURCE_URLS[name] and
                        report[kind][name]["build_backend"] == metadata["build_backend"], "G1 source metadata mismatch")
            else:
                wheel_hashes[name] = g1._wheel_metadata(file, name, g1.EXPECTED_DISTRIBUTIONS[name])
    records = {r["filename"]: r for r in report["toolchain_artifacts"]}
    require(len(records) == len(report["toolchain_artifacts"]) == len(g1.EXPECTED_TOOLCHAIN_DISTRIBUTIONS) and
            set(item["toolchain"]) == set(records), "Incomplete/duplicate toolchain artifacts")
    names = set()
    for name, path in item["toolchain"].items():
        file = bundle.file(path, g1.MAX_ARCHIVE_BYTES, records[name])
        require(file.name == name, "Toolchain filename mismatch")
        distribution, version, _, _ = g1.parse_wheel_filename(name)
        require(distribution not in names and str(version) == g1.EXPECTED_TOOLCHAIN_DISTRIBUTIONS.get(distribution),
                "Toolchain pin mismatch")
        names.add(distribution)
        g1._wheel_metadata(file, distribution, str(version))
    trace = bundle.file(item["trace"], g1.MAX_TRACE_BYTES, report["tool_trace"])
    pending = bundle.path(item["trace"] + ".pending")
    require(pending.is_dir(), "Missing G1 recording state")
    sections = g1._tool_trace(trace, {k: bundle.path(v) for k, v in item["sources"].items()},
                             {k: bundle.path(v) for k, v in item["wheels"].items()}, source_hashes, wheel_hashes)
    require(sections == report["tool_trace_sections"], "G1 trace/report disagreement")
    verification = json_data(bundle.read(item["verification"], MAX_METADATA, report["verification_file"]))
    require(verification == report["verification"] and verification["bindings"] ==
            {n: g1.EXPECTED_DISTRIBUTIONS[n] for n in g1.REQUIRED_SOURCES} and
            verification["required_namespaces"] == g1.EXPECTED_NAMESPACES, "G1 verification mismatch")
    require(set(item["compiler_evidence"]) == {"PyGObject"} and set(item["proxies"]) == g1.REQUIRED_BUILD_TOOLS,
            "Incomplete G1 tool evidence")
    for name, path in item["proxies"].items():
        bundle.file(path, MAX_METADATA, report["tool_proxies"][name])
    entry = report["compiler_evidence"]["PyGObject"]
    compiler = json_data(bundle.read(item["compiler_evidence"]["PyGObject"], MAX_METADATA, entry["file"]))
    require(compiler == entry["evidence"], "Compiler evidence mismatch")
    g1._compiler_evidence(compiler, compiler["host"]["c"]["exelist"][0], "bfd",
                          report["build_tools"]["cc"]["version"], report["build_tools"]["ld"]["version"])
    require(set(report["native_packages"]) == g1.REQUIRED_NATIVE_PACKAGES, "G1 seeds incomplete")
    return report, g1


def native_packages(entries, repos, sources, bundle, system, g1_report):
    require(isinstance(entries, list) and 0 < len(entries) <= MAX_PACKAGES, "Invalid package count")
    packages, seeds, used_sources, roles = {}, set(), set(), set()
    consumed_paths = set()
    required_roles = {"typelib:" + n for n in TYPELIBS} | {"native:" + n for n in NATIVE_ROLES} | {"font:dejavu-sans"}
    for item in entries:
        fields(item, {"id", "repository", "archive", "classification", "selected", "consumed"})
        require(item["classification"] in CLASSES and isinstance(item["selected"], list), "Invalid package policy")
        require(item["repository"] in repos, "Unknown package repository")
        # Authenticate compressed bytes before invoking any archive parser/decompressor.
        path = bundle.path(item["archive"])
        candidates = [r for r in repos[item["repository"]]["packages"]
                      if PurePosixPath(r.get("Filename", "")).name == path.name]
        require(len(candidates) == 1, "Missing/conflicting binary archive index")
        authenticated = candidates[0]
        require(authenticated["Size"].isdecimal() and len(authenticated["Size"]) < 12, "Invalid archive size")
        path = bundle.file(item["archive"], expected={"sha256": sha(authenticated["SHA256"]),
                                                      "size": int(authenticated["Size"])})
        control, members = inspect_deb(path, system, bundle.budget)
        package_id = package_metadata(control)
        require(package_id == item["id"] and package_id not in packages, "Conflicting package identity")
        require(control["Package"] not in {p["metadata"]["Package"] for p in packages.values()},
                "Conflicting installed architectures for one package")
        require(system.version(control["Version"], "=", control["Version"]), "Invalid version")
        indexed = [r for r in repos[item["repository"]]["packages"] if
                   (r.get("Package"), r.get("Version"), r.get("Architecture")) ==
                   tuple(control[k] for k in ("Package", "Version", "Architecture"))]
        require(len(indexed) == 1, "Missing/conflicting binary index record")
        indexed = indexed[0]
        relative(indexed["Filename"])
        require(path.name == PurePosixPath(indexed["Filename"]).name, "Binary archive filename mismatch")
        require(indexed["Size"].isdecimal(), "Invalid archive size")
        bundle.file(item["archive"], expected={"sha256": sha(indexed["SHA256"]), "size": int(indexed["Size"])})
        installed = system.installed(package_id)
        require(installed.get("Status") == "install ok installed", "Required package is not installed")
        compare_metadata(control, indexed)
        compare_metadata(control, installed)
        # Validate every Provides record, even when no dependency selects it.
        satisfies((control["Package"], None, None, None), control, system)
        source_key = (item["repository"], *source_identity(control))
        require(source_key in sources, "Missing exact source-package material")
        used_sources.add(source_key)
        if item["classification"] == "declared-host":
            require(control["Package"] in HOST_PACKAGES and not item["consumed"], "Unsupported declared host package")
        if control["Package"] in g1_report["native_packages"]:
            require(control["Version"] == g1_report["native_packages"][control["Package"]], "Installed package differs from G1")
            seeds.add(package_id)
        require(isinstance(item["consumed"], list) and len(item["consumed"]) <= MAX_FILES, "Invalid consumed-file list")
        consumed = []
        for use in item["consumed"]:
            fields(use, {"path", "archive_path", "role", "transformation"})
            require(use["transformation"] == "identity", "Only unchanged input bytes/links are supported")
            live, name = absolute(use["path"]), relative(use["archive_path"])
            require(use["path"] == "/" + name, "Installed/archive pathname mismatch")
            require(use["path"] not in consumed_paths and len(consumed_paths) < MAX_FILES, "Duplicate/excessive consumed files")
            consumed_paths.add(use["path"])
            resolved, chain = consumed_chain(members, name)
            role = use["role"]
            if role in required_roles:
                require(item["classification"] == "bundled-runtime" and role not in roles, "Invalid/duplicate resource role")
                if role.startswith("typelib:"):
                    require(live.name == role[8:] + ".typelib", "Typelib role mismatch")
                elif role.startswith("native:"):
                    require(live.name.startswith(NATIVE_ROLES[role[7:]]), "Native library role mismatch")
                else:
                    require(control["Package"] == "fonts-dejavu-core" and live.name == "DejaVuSans.ttf", "Font role mismatch")
                roles.add(role)
                seeds.add(package_id)
            elif role.startswith("build:"):
                tool = role[6:]
                require(tool in {"cc", "ld", "ninja", "pkg-config"}, "Unknown native build-tool role")
                record = g1_report["build_tools"][tool]
                require(str(live.resolve()) == record["resolved_path"] and
                        identity(live.resolve()) == {k: record[k] for k in ("size", "sha256")}, "Build tool differs from G1")
                require(role not in roles, "Duplicate build-tool role")
                roles.add(role)
                seeds.add(package_id)
            else:
                require(role == "dependency", "Unknown consumed-file role")
            consumed.append({**use, "identity": resolved, "chain": chain,
                             "link_target": os.readlink(live) if live.is_symlink() else None})
        require(item["classification"] != "bundled-runtime" or consumed, "Bundled package has no declared consumed files")
        packages[package_id] = {**item, "metadata": control, "consumed": consumed,
                                "origin": {"repository": item["repository"], "filename": indexed["Filename"]}}
    require(required_roles | {"build:" + n for n in ("cc", "ld", "ninja", "pkg-config")} <= roles, "Missing required resource/tool roles")
    require(set(g1_report["native_packages"]) <= {p["metadata"]["Package"] for p in packages.values()}, "Missing G1 seed")
    require(used_sources == sources.keys(), "Unrelated or missing source packages")
    return packages, validate_closure(packages, seeds, system)


def non_dpkg(entries, bundle, builder, report, project, commit, system):
    require(isinstance(entries, list) and len(entries) == 4, "Expected CPython/library and two project resources")
    seen, result = set(), []
    for item in entries:
        fields(item, {"kind", "path", "bundle_path", "transformation"}, {"project_path"})
        require(item["transformation"] == "identity", "Unsupported non-dpkg transformation")
        live = absolute(item["path"])
        file = bundle.file(item["bundle_path"])
        observed = identity(live)
        require(observed == bundle.files[item["bundle_path"]], "Non-dpkg copy differs from actual input")
        kind = item["kind"]
        if kind in {"cpython", "cpython-library"}:
            require(set(item) == {"kind", "path", "bundle_path", "transformation"}, "Unexpected CPython fields")
            expected = builder["interpreter" if kind == "cpython" else "library"]
            require(str(live) == expected, "CPython input is not the running trusted interpreter/library")
            if kind == "cpython":
                require(observed == {k: report["interpreter"]["binary"][k] for k in ("size", "sha256")}, "CPython differs from G1")
            key = kind
        else:
            require(kind == "project-resource" and item.get("project_path") in PROJECT_RESOURCES, "Unknown project resource")
            key = item["project_path"]
            require(live == project / key, "Resource path differs from selected project")
            require(observed == {"sha256": digest(system.committed(project, commit, key)), "size": file.stat().st_size},
                    "Resource differs from committed source")
        require(key not in seen, "Duplicate non-dpkg input")
        seen.add(key)
        result.append({**item, **observed})
    require(seen == PROJECT_RESOURCES | {"cpython", "cpython-library"}, "Incomplete non-dpkg inputs")
    return result


def recheck_installed(packages, other, system):
    """Detect ordinary package/file drift before publication; not an OS snapshot lock."""
    for package_id, package in packages.items():
        installed = system.installed(package_id)
        require(installed.get("Status") == "install ok installed", "Installed package state changed")
        compare_metadata(package["metadata"], installed)
        for item in package["consumed"]:
            expected, chain = consumed_chain(item["chain"]["records"], item["archive_path"])
            require(chain == item["chain"] and expected == item["identity"],
                    "Consumed chain changed before publication")
    for item in other:
        require(identity(item["path"]) == {k: item[k] for k in ("size", "sha256")},
                "Non-dpkg input changed before publication")


def validate(bundle_root, keyring, expected_g1_sha256, project_root, source_commit, system=None):
    budget = Budget()
    system = system or System(budget)
    bundle = Bundle(bundle_root, budget)
    project, keyring = Path(project_root).resolve(strict=True), absolute(str(keyring))
    require(not keyring.resolve().is_relative_to(bundle.root), "Trusted keyring must be outside the bundle")
    key_identity = identity(keyring, MAX_METADATA)
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit), "Expected full selected source commit")
    manifest = json_data(bundle.read("bundle.json", MAX_JSON))
    fields(manifest, {"schema_version", "g1", "repositories", "sources", "packages", "non_dpkg"})
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == SCHEMA, "Unsupported schema version")
    builder = system.builder()
    release = dict(re.findall(r'^([A-Z_]+)=["\']?([^"\'\n]+)["\']?$', builder["os_release"], re.MULTILINE))
    require(release.get("ID") == "ubuntu" and release.get("VERSION_ID") == "22.04" and
            builder["architecture"] == "x86_64" and builder["glibc"] == "glibc 2.35" and
            builder["implementation"] == "CPython" and re.fullmatch(r"3\.12\.\d+", builder["version"]),
            "Unsupported actual builder baseline")
    report, _ = validate_g1(manifest["g1"], bundle, expected_g1_sha256, project, source_commit, system)
    require(report["verification"]["python"] == {"implementation": "CPython", "version": builder["version"]},
            "G1 interpreter version differs from builder")
    repos = repositories(manifest["repositories"], bundle, system, keyring)
    sources = source_material(manifest["sources"], repos, bundle, budget, system)
    packages, edges = native_packages(manifest["packages"], repos, sources, bundle, system, report)
    other = non_dpkg(manifest["non_dpkg"], bundle, builder, report, project, source_commit, system)
    bundle.finish()
    recheck_installed(packages, other, system)
    require(identity(keyring, MAX_METADATA) == key_identity, "Trusted keyring changed")
    return {
        "schema_version": SCHEMA, "kind": "linux-tray-native-inputs", "source_commit": source_commit,
        "g1_report": {"path": manifest["g1"]["report"], "sha256": expected_g1_sha256},
        "g1_inputs": manifest["g1"],
        "native_package_archives": {"availability": "validated-offline", "scope": "declared-input-closure"},
        "builder": builder, "trusted_keyring": key_identity,
        "repositories": {name: {"release": r["release"], "signature": r["signature"], "indexes": r["indexes"],
                                 "signers": r["fingerprints"],
                                 "origin": r["metadata"]["Origin"], "suite": r["metadata"]["Suite"],
                                 "date": r["metadata"]["Date"], "declared_uri": r["uri"],
                                 "snapshot_sha256": bundle.files[r["release"]]["sha256"]}
                         for name, r in repos.items()},
        "packages": packages, "dependency_edges": edges, "sources": list(sources.values()),
        "non_dpkg": other, "files": bundle.files,
        "deferred": "G2 must reconcile actual PyInstaller inputs and final archive against this declared set.",
    }


def check_json_size(value):
    """Bound compact encoded size before an encoder can allocate a large token.

    Pretty-print whitespace is charged separately while streaming. This pass
    allocates no encoded strings and stops as soon as its lower bound is too big.
    """
    remaining = MAX_JSON

    def charge(size):
        nonlocal remaining
        require(size <= remaining, "Output manifest exceeds limit")
        remaining -= size

    def visit(item, depth):
        require(depth <= MAX_JSON_DEPTH, "Output nesting exceeds limit")
        if isinstance(item, str):
            charge(2)
            require(len(item) <= remaining, "Output string exceeds limit")
            for character in item:
                code = ord(character)
                charge(2 if character in '\\"\b\f\n\r\t' else
                       1 if 32 <= code < 127 else 6 if code <= 0xffff else 12)
        elif item is None or isinstance(item, bool):
            charge(4 if item is None or item is True else 5)
        elif isinstance(item, (int, float)):
            if isinstance(item, int):
                require(item.bit_length() <= 4 * remaining, "Output integer exceeds limit")
            charge(len(json.dumps(item, allow_nan=False)))
        elif isinstance(item, (list, tuple, dict)):
            charge(2 + max(0, len(item) - 1))
            if isinstance(item, dict):
                charge(len(item))
                for key, member in item.items():
                    require(isinstance(key, str), "Output keys must be strings")
                    visit(key, depth + 1)
                    visit(member, depth + 1)
            else:
                for member in item:
                    visit(member, depth + 1)
        else:
            raise Invalid("Unsupported output value")

    visit(value, 0)


def publish(output, report):
    """Complete bytes first, then exclusive atomic publication; never replace evidence."""
    output = absolute(str(output))
    descriptor, temporary = tempfile.mkstemp(prefix=".lmt-native-", dir=output.parent)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            check_json_size(report)
            encoder = json.JSONEncoder(sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
            size = 0
            for chunk in encoder.iterencode(report):
                # ensure_ascii makes character count equal to encoded byte count;
                # check before making the bytes allocation or writing the chunk.
                size += len(chunk)
                require(size <= MAX_JSON, "Output manifest exceeds limit")
                stream.write(chunk.encode("ascii"))
            require(size < MAX_JSON, "Output manifest exceeds limit")
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output, follow_symlinks=False)
        published = True
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            if not published:
                raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bundle", "trusted-keyring", "g1-sha256", "project-root", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        project = Path(args.project_root).resolve(strict=True)
        output = absolute(args.output)
        require(not output.parent.resolve().is_relative_to(project) and not os.path.lexists(output),
                "Output must be new and outside the project")
        report = validate(args.bundle, args.trusted_keyring, args.g1_sha256, project, args.source_commit)
        publish(output, report)
    except (ValueError, OSError, KeyError, TypeError, tarfile.TarError, EOFError, subprocess.SubprocessError) as error:
        print("Native-input validation failed: " + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
