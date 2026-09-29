#!/usr/bin/env python3
"""Create bounded, deterministic provenance for Linux tray inputs."""

import argparse
import base64
import ctypes
from email.parser import BytesParser
from email.policy import compat32
import gzip
import hashlib
import importlib.metadata
import json
import os
import re
import secrets
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.tags import parse_tag, sys_tags
from packaging.utils import (
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import Version


REQUIRED_SOURCES = frozenset({"PyGObject", "pycairo"})
REQUIRED_WHEELS = frozenset({"PyGObject", "pycairo"})
EXPECTED_DISTRIBUTIONS = {
    "PyGObject": "3.48.2",
    "altgraph": "0.17.4",
    "meson": "1.4.1",
    "meson-python": "0.16.0",
    "packaging": "24.0",
    "pip": "24.0",
    "pycairo": "1.26.1",
    "pyinstaller": "6.21.0",
    "pyinstaller-hooks-contrib": "2026.6",
    "pyproject-metadata": "0.8.0",
    "setuptools": "69.5.1",
    "wheel": "0.43.0",
}
EXPECTED_SOURCE_URLS = {
    "PyGObject": "https://pypi.org/project/PyGObject/3.48.2/",
    "pycairo": "https://pypi.org/project/pycairo/1.26.1/",
}
EXPECTED_BUILD_BACKENDS = {
    "PyGObject": "mesonpy",
    "pycairo": "setuptools.build_meta",
}
EXPECTED_NAMESPACES = {
    "GdkPixbuf": "2.0",
    "Gio": "2.0",
    "GLib": "2.0",
    "Gtk": "3.0",
}
REQUIRED_NATIVE_PACKAGES = frozenset(
    {
        "build-essential",
        "fontconfig",
        "fonts-dejavu-core",
        "gobject-introspection",
        "libcairo2-dev",
        "libffi-dev",
        "libgdk-pixbuf2.0-bin",
        "libgirepository1.0-dev",
        "libglib2.0-bin",
        "libgtk-3-dev",
        "ninja-build",
        "pkg-config",
    }
)
REQUIRED_VERIFICATION_KEYS = frozenset(
    {"bindings", "native", "python", "required_namespaces"}
)
REQUIRED_NATIVE_VERSION_FIELDS = frozenset(
    {"cairo", "gdk_pixbuf", "glib", "gtk"}
)
REQUIRED_BUILD_TOOLS = frozenset(
    {"cc", "ld", "meson", "ninja", "pkg-config"}
)
EXPECTED_TOOLCHAIN_DISTRIBUTIONS = {
    name: version
    for name, version in EXPECTED_DISTRIBUTIONS.items()
    if name not in REQUIRED_SOURCES
}
EXPECTED_REQUIREMENTS = frozenset(
    {"requirements-linux-tray.txt", "requirements-linux-tray-build.txt"}
)
PYTHON_VERSION_PATTERN = re.compile(r"^3\.12\.\d+$")
NATIVE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000
MAX_ARCHIVE_CONTENT_BYTES = 512 * 1024 * 1024
MAX_SOURCE_STREAM_BYTES = 128 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
MAX_TRACE_BYTES = 4 * 1024 * 1024
MAX_TRACE_RECORDS = 50_000
MAX_TRACE_DETAIL_BYTES = 32 * 1024
MAX_NATIVE_MEMBER_BYTES = 64 * 1024 * 1024
TRACE_REQUIREMENTS = {
    "PyGObject": frozenset(
        {
            ("cc", "compile"),
            ("cc", "link"),
            ("ld", "link"),
            ("meson", "run"),
            ("ninja", "run"),
            ("pkg-config", "run"),
        }
    ),
    "pycairo": frozenset(
        {
            ("cc", "compile"),
            ("cc", "link"),
            ("ld", "link"),
            ("pkg-config", "run"),
        }
    ),
}


def _arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--interpreter", required=True)
    parser.add_argument("--interpreter-invocation", required=True)
    parser.add_argument("--verification", required=True)
    parser.add_argument("--requirements", action="append", default=[])
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--source-url", action="append", default=[])
    parser.add_argument("--wheel", action="append", default=[])
    parser.add_argument("--toolchain-artifact", action="append", default=[])
    parser.add_argument("--distribution", action="append", default=[])
    parser.add_argument("--native-package", action="append", default=[])
    parser.add_argument("--build-tool", action="append", default=[])
    parser.add_argument("--build-tool-version", action="append", default=[])
    parser.add_argument("--tool-proxy", action="append", default=[])
    parser.add_argument("--linker-selector", required=True)
    parser.add_argument("--linker-discovery", required=True)
    parser.add_argument("--tool-trace", required=True)
    parser.add_argument("--compiler-evidence", action="append", default=[])
    parser.add_argument(
        "--native-archive-provenance",
        choices=("unavailable",),
        required=True,
    )
    parser.add_argument("--builder-os", required=True)
    parser.add_argument("--architecture", required=True)
    return parser.parse_args(argv)


def _named_values(values, option):
    result = {}
    for value in values:
        name, separator, entry = value.partition("=")
        if not separator or not name or not entry or name in result:
            raise ValueError(f"Invalid or duplicate {option} entry.")
        result[name] = entry
    return result


def _require_single_line_values(values, message):
    if any(
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.isprintable()
        or "\n" in value
        or "\r" in value
        for value in values
    ):
        raise ValueError(message)


def _require_version_values(values, pattern, message):
    if any(
        not isinstance(value, str) or pattern.fullmatch(value) is None
        for value in values
    ):
        raise ValueError(message)


def _metadata_identity(content, label):
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError(f"{label} metadata is oversized.")
    message = BytesParser(policy=compat32).parsebytes(content)
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        raise ValueError(f"{label} metadata identity is incomplete.")
    return canonicalize_name(names[0]), str(Version(versions[0]))


def _check_archive_file(path):
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("An artifact is not a bounded regular file.")


class _BudgetedReader:
    def __init__(self, source, limit):
        self._source = source
        self._remaining = limit

    def read(self, size=-1):
        if self._remaining < 0:
            raise ValueError("Source archive traversal exceeded its limit.")
        requested = self._remaining + 1 if size < 0 else min(size, self._remaining + 1)
        content = self._source.read(requested)
        self._remaining -= len(content)
        if self._remaining < 0:
            raise ValueError("Source archive traversal exceeded its limit.")
        return content


def _source_metadata(path_value, expected_name, expected_version):
    path = Path(path_value)
    try:
        filename_name, filename_version = parse_sdist_filename(path.name)
    except (TypeError, ValueError) as error:
        raise ValueError("Source artifact filename metadata is invalid.") from error
    if (
        canonicalize_name(filename_name) != canonicalize_name(expected_name)
        or str(filename_version) != expected_version
    ):
        raise ValueError("Source artifact filename does not match its pin.")
    _check_archive_file(path)
    if not path.name.endswith(".tar.gz"):
        raise ValueError("Source artifact compression is unsupported.")
    metadata_contents = []
    project_contents = []
    source_input_hashes = set()
    member_count = 0
    declared_content = 0
    metadata_bytes = 0
    extension_types = {
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    }

    class BudgetedTarInfo(tarfile.TarInfo):
        def _proc_member(self, archive):
            nonlocal member_count, declared_content, metadata_bytes
            member_count += 1
            if member_count > MAX_ARCHIVE_MEMBERS:
                raise ValueError("An artifact contains too many members.")
            if self.type in extension_types:
                declared_content += self.size
                metadata_bytes += self.size
                if (
                    declared_content > MAX_ARCHIVE_CONTENT_BYTES
                    or metadata_bytes > MAX_METADATA_BYTES
                ):
                    raise ValueError("Source extended metadata is oversized.")
            return super()._proc_member(archive)

    try:
        with path.open("rb") as raw_file:
            with gzip.GzipFile(fileobj=raw_file) as decompressed:
                bounded = _BudgetedReader(decompressed, MAX_SOURCE_STREAM_BYTES)
                with tarfile.open(
                    fileobj=bounded, mode="r|", tarinfo=BudgetedTarInfo
                ) as archive:
                    for member in archive:
                        declared_content += member.size
                        if declared_content > MAX_ARCHIVE_CONTENT_BYTES:
                            raise ValueError(
                                "An artifact expands beyond the inspection limit."
                            )
                        member_path = PurePosixPath(member.name)
                        if member_path.is_absolute() or ".." in member_path.parts:
                            raise ValueError("Source archive contains path traversal.")
                        if not member.isfile():
                            continue
                        if member_path.suffix == ".c":
                            if member.size > MAX_NATIVE_MEMBER_BYTES:
                                raise ValueError("Source compilation input is oversized.")
                            source_file = archive.extractfile(member)
                            if source_file is None:
                                raise ValueError("Source compilation input cannot be read.")
                            digest = hashlib.sha256()
                            for block in iter(lambda: source_file.read(1024 * 1024), b""):
                                digest.update(block)
                            source_input_hashes.add(digest.hexdigest())
                        if (
                            len(member_path.parts) != 2
                            or member_path.name not in {"PKG-INFO", "pyproject.toml"}
                        ):
                            continue
                        metadata_bytes += member.size
                        if metadata_bytes > MAX_METADATA_BYTES:
                            raise ValueError("Source metadata is oversized.")
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            raise ValueError("Source metadata cannot be read.")
                        content = extracted.read(MAX_METADATA_BYTES + 1)
                        if len(content) > MAX_METADATA_BYTES:
                            raise ValueError("Source metadata is oversized.")
                        if member_path.name == "PKG-INFO":
                            metadata_contents.append(content)
                        else:
                            project_contents.append(content)
    except (EOFError, gzip.BadGzipFile, OSError, tarfile.TarError) as error:
        raise ValueError("Source artifact is not a valid bounded archive.") from error
    if len(metadata_contents) != 1 or len(project_contents) != 1:
        raise ValueError("Source metadata is missing or ambiguous.")
    identity = _metadata_identity(metadata_contents[0], "Source")
    expected = canonicalize_name(expected_name), expected_version
    if identity != expected:
        raise ValueError("Source archive metadata does not match its pin.")
    try:
        project = tomllib.loads(project_contents[0].decode("utf-8"))
        backend = project["build-system"]["build-backend"]
    except (KeyError, TypeError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("Source build-backend metadata is invalid.") from error
    if backend != EXPECTED_BUILD_BACKENDS[expected_name]:
        raise ValueError("Source build backend does not match the pinned contract.")
    return {"build_backend": backend, "source_input_hashes": source_input_hashes}


def _elf_text_digest(content):
    """Fingerprint executable code across a wheel's copy/ELF metadata edits."""
    if (
        len(content) < 64
        or content[:6] != b"\x7fELF\x02\x01"
        or len(content) > MAX_NATIVE_MEMBER_BYTES
    ):
        raise ValueError("A native extension is not a bounded x86-64 ELF file.")
    try:
        if struct.unpack_from("<H", content, 18)[0] != 62:
            raise ValueError("A native extension is not x86-64 ELF.")
        section_offset = struct.unpack_from("<Q", content, 40)[0]
        section_size, section_count, names_index = struct.unpack_from(
            "<HHH", content, 58
        )
        if (
            section_size < 64
            or section_count == 0
            or names_index >= section_count
            or section_offset + section_size * section_count > len(content)
        ):
            raise ValueError("A native extension has invalid ELF sections.")
        headers = [
            struct.unpack_from("<IIQQQQIIQQ", content, section_offset + n * section_size)
            for n in range(section_count)
        ]
        string_header = headers[names_index]
        names_start, names_length = string_header[4:6]
        if names_start + names_length > len(content):
            raise ValueError("A native extension has invalid ELF section names.")
        names = content[names_start:names_start + names_length]
        matches = []
        for header in headers:
            name_offset = header[0]
            if name_offset < len(names) and names[name_offset:].split(b"\0", 1)[0] == b".text":
                start, length = header[4:6]
                if not length or start + length > len(content):
                    raise ValueError("A native extension has invalid executable code.")
                matches.append(hashlib.sha256(content[start:start + length]).hexdigest())
        if len(matches) != 1:
            raise ValueError("A native extension has ambiguous executable code.")
        return matches[0]
    except struct.error as error:
        raise ValueError("A native extension has invalid ELF structure.") from error


def _wheel_metadata(path_value, expected_name, expected_version):
    path = Path(path_value)
    try:
        filename_name, filename_version, _build, filename_tags = (
            parse_wheel_filename(path.name)
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Wheel filename metadata is invalid.") from error
    expected = canonicalize_name(expected_name), expected_version
    if (canonicalize_name(filename_name), str(filename_version)) != expected:
        raise ValueError("Wheel filename does not match its pin.")
    compatible_tags = set(sys_tags())
    if not set(filename_tags).intersection(compatible_tags):
        raise ValueError("Wheel filename tags are incompatible.")
    _check_archive_file(path)
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if (
                len(members) > MAX_ARCHIVE_MEMBERS
                or sum(member.file_size for member in members)
                > MAX_ARCHIVE_CONTENT_BYTES
                or any(member.flag_bits & 0x1 for member in members)
            ):
                raise ValueError("Wheel is not a bounded regular archive.")
            if archive.testzip() is not None:
                raise ValueError("Wheel archive integrity is invalid.")
            metadata_members = [
                member for member in members
                if member.filename.endswith(".dist-info/METADATA")
            ]
            wheel_members = [
                member for member in members
                if member.filename.endswith(".dist-info/WHEEL")
            ]
            if len(metadata_members) != 1 or len(wheel_members) != 1:
                raise ValueError("Wheel metadata is missing or ambiguous.")
            metadata_parent = PurePosixPath(metadata_members[0].filename).parent
            if PurePosixPath(wheel_members[0].filename).parent != metadata_parent:
                raise ValueError("Wheel metadata directories are inconsistent.")
            if (
                metadata_members[0].file_size > MAX_METADATA_BYTES
                or wheel_members[0].file_size > MAX_METADATA_BYTES
            ):
                raise ValueError("Wheel metadata is oversized.")
            metadata_content = archive.read(metadata_members[0])
            wheel_content = archive.read(wheel_members[0])
            native_text_hashes = set()
            for member in members:
                if ".so" not in PurePosixPath(member.filename).name:
                    continue
                if member.file_size > MAX_NATIVE_MEMBER_BYTES:
                    raise ValueError("Wheel native extension is oversized.")
                native_text_hashes.add(_elf_text_digest(archive.read(member)))
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("Wheel is not a valid bounded archive.") from error
    if _metadata_identity(metadata_content, "Wheel") != expected:
        raise ValueError("Wheel archive metadata does not match its pin.")
    wheel_message = BytesParser(policy=compat32).parsebytes(wheel_content)
    wheel_versions = wheel_message.get_all("Wheel-Version", [])
    if wheel_versions != ["1.0"]:
        raise ValueError("Wheel format metadata is unsupported.")
    wheel_tags = wheel_message.get_all("Tag", [])
    if not wheel_tags:
        raise ValueError("Wheel compatibility metadata is incomplete.")
    try:
        archive_tags = {tag for value in wheel_tags for tag in parse_tag(value)}
    except ValueError as error:
        raise ValueError("Wheel compatibility metadata is invalid.") from error
    if set(filename_tags) != archive_tags or not archive_tags.intersection(
        compatible_tags
    ):
        raise ValueError("Wheel compatibility metadata is inconsistent.")
    return native_text_hashes


def _regular_file_record(path_value):
    path = Path(path_value)
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("A provenance input is not a regular file.")
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "filename": path.name,
        "sha256": digest.hexdigest(),
        "size": file_stat.st_size,
    }


def _requirements_inventory(paths):
    if len(paths) != len(EXPECTED_REQUIREMENTS):
        raise ValueError("Requirement-file provenance is incomplete or duplicated.")
    by_name = {}
    for path_value in paths:
        path = Path(path_value)
        if path.name in by_name or path.name not in EXPECTED_REQUIREMENTS:
            raise ValueError("Requirement-file provenance is inconsistent.")
        requirements = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#"):
                raise ValueError("A requirement file contains an unsupported line.")
            requirement = Requirement(line)
            canonical_name = canonicalize_name(requirement.name)
            if (
                canonical_name in requirements
                or requirement.extras
                or requirement.marker is not None
                or requirement.url is not None
            ):
                raise ValueError("A requirement pin is ambiguous.")
            specifiers = list(requirement.specifier)
            if len(specifiers) != 1 or specifiers[0].operator != "==":
                raise ValueError("A requirement is not exactly pinned.")
            requirements[canonical_name] = specifiers[0].version
        by_name[path.name] = requirements
    expected = {
        "requirements-linux-tray.txt": {
            canonicalize_name(name): EXPECTED_DISTRIBUTIONS[name]
            for name in REQUIRED_SOURCES
        },
        "requirements-linux-tray-build.txt": {
            canonicalize_name(name): version
            for name, version in EXPECTED_TOOLCHAIN_DISTRIBUTIONS.items()
        },
    }
    if by_name != expected:
        raise ValueError("Requirement contents do not match the declared pins.")
    return by_name


def _distribution_inventory(names, distribution_version):
    expected = {
        canonicalize_name(name): version
        for name, version in EXPECTED_DISTRIBUTIONS.items()
    }
    if len(names) != len(expected):
        raise ValueError("Distribution provenance is incomplete or duplicated.")
    observed_names = [canonicalize_name(name) for name in names]
    if len(set(observed_names)) != len(observed_names) or set(observed_names) != set(
        expected
    ):
        raise ValueError("Distribution provenance is inconsistent.")
    observed = {
        canonical: distribution_version(name)
        for canonical, name in zip(observed_names, names)
    }
    if observed != expected:
        raise ValueError("Resolved build distributions do not match the pins.")
    return dict(sorted(EXPECTED_DISTRIBUTIONS.items()))


def _compiler_evidence(
    evidence,
    cc_proxy,
    linker_selector,
    cc_version,
    linker_version,
):
    if not isinstance(evidence, dict) or set(evidence) != {"host", "build"}:
        raise ValueError("Compiler evidence schema is invalid.")
    host = evidence["host"]
    build = evidence["build"]
    if not isinstance(host, dict) or not isinstance(build, dict) or set(host) != {"c"}:
        raise ValueError("Compiler evidence does not describe the selected C toolchain.")
    if build not in ({}, host):
        raise ValueError("Build-machine compiler evidence is inconsistent.")
    compiler = host["c"]
    required = {
        "default_suffix",
        "exelist",
        "file_suffixes",
        "full_version",
        "id",
        "linker_exelist",
        "linker_id",
        "version",
    }
    if not isinstance(compiler, dict) or set(compiler) != required:
        raise ValueError("Compiler evidence fields are incomplete.")
    if (
        compiler["id"] != "gcc"
        or compiler["linker_id"] != "ld.bfd"
        or compiler["exelist"] != [cc_proxy]
        or compiler["linker_exelist"] != [cc_proxy]
    ):
        raise ValueError("Compiler evidence does not match the selected tools.")
    _require_single_line_values(
        [compiler["version"], compiler["full_version"]],
        "Compiler evidence versions are invalid.",
    )
    if (
        compiler["version"] not in cc_version
        or compiler["full_version"] != cc_version
        or "GNU ld" not in linker_version
    ):
        raise ValueError("Compiler evidence versions do not match tool identities.")
    if (
        not isinstance(compiler["file_suffixes"], list)
        or not compiler["file_suffixes"]
        or not isinstance(compiler["default_suffix"], str)
        or not compiler["default_suffix"]
    ):
        raise ValueError("Compiler evidence suffixes are invalid.")
    return compiler


def _trace_lines(path_value):
    path = Path(path_value)
    if os.path.lexists(str(path) + ".failed"):
        raise ValueError("Build-tool execution trace has a producer failure.")
    pending_directory = Path(str(path) + ".pending")
    try:
        pending_stat = pending_directory.lstat()
        if not stat.S_ISDIR(pending_stat.st_mode):
            raise ValueError("Build-tool recording state is invalid.")
        with os.scandir(pending_directory) as entries:
            if next(entries, None) is not None:
                raise ValueError("Build-tool recording is incomplete.")
    except OSError as error:
        raise ValueError("Build-tool recording state is unavailable.") from error
    file_stat = path.lstat()
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_TRACE_BYTES:
        raise ValueError("Build-tool execution trace is not a bounded regular file.")
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or len(lines) > MAX_TRACE_RECORDS:
        raise ValueError("Build-tool execution trace has an invalid record count.")
    return lines


def _trace_event(line, binding):
    fields = line.split("|")
    status_value = (
        int(fields[4])
        if len(fields) == 8 and fields[4].isdigit() and len(fields[4]) <= 3
        else -1
    )
    if (
        len(fields) != 8
        or fields[0] != "result"
        or fields[1] != binding
        or fields[2] not in {"cc", "ld", "meson", "ninja", "pkg-config"}
        or fields[3] not in {"probe", "query", "compile", "link", "run"}
        or status_value < 0
        or status_value > 255
        or (
            status_value == 0
            and fields[5] not in {"complete", "missing-output", "unattributed"}
            or (status_value != 0 and fields[5] != "failed")
        )
        or (
            fields[6] != "-"
            and (not fields[6].isdigit() or len(fields[6]) > 20)
        )
        or len(fields[7]) > MAX_TRACE_DETAIL_BYTES
    ):
        raise ValueError("Build-tool execution trace contains an invalid event.")
    completed = status_value == 0 and fields[5] == "complete"
    detail = None
    if fields[7] != "-":
        try:
            encoded = base64.b64decode(fields[7], altchars=b"-_", validate=True)
            detail = json.loads(encoded)
        except (ValueError, TypeError) as error:
            raise ValueError("Build-tool operation identity is invalid.") from error
        if not isinstance(detail, dict) or set(detail) != {
            "inputs", "output", "text", "produced"
        } or detail["produced"] is not True:
            raise ValueError("Build-tool operation identity is incomplete.")
        if not isinstance(detail["inputs"], list) or not detail["inputs"]:
            raise ValueError("Build-tool operation identity is invalid.")
        pairs = [*detail["inputs"], detail["output"]]
        if (
            any(
                not isinstance(pair, list) or len(pair) != 2
                or not isinstance(pair[0], str) or not Path(pair[0]).is_absolute()
                or not isinstance(pair[1], str)
                or re.fullmatch(r"[0-9a-f]{64}", pair[1]) is None
                for pair in pairs
            )
            or (detail["text"] is not None and (
                not isinstance(detail["text"], str)
                or re.fullmatch(r"[0-9a-f]{64}", detail["text"]) is None
            ))
        ):
            raise ValueError("Build-tool operation identity is invalid.")
    if completed and fields[2] in {"cc", "ld"} and fields[3] in {"compile", "link"}:
        if detail is None or (fields[3] == "link") != (detail["text"] is not None):
            raise ValueError("Completed native operation lacks output evidence.")
    elif detail is not None:
        raise ValueError("Non-build operation contains native output evidence.")
    return fields[2], fields[3], fields[6], completed, detail


def _require_driver_link(events):
    cc_tokens = {
        token for tool, action, token, completed, _detail in events
        if completed and tool == "cc" and action == "link" and token != "-"
    }
    ld_tokens = {
        token for tool, action, token, completed, _detail in events
        if completed and tool == "ld" and action == "link" and token != "-"
    }
    if not cc_tokens or cc_tokens != ld_tokens:
        raise ValueError("Compiler-driver linker evidence is incomplete.")


def _require_native_chain(events, source_hashes, wheel_text_hashes):
    compilations = [
        detail for tool, action, _token, completed, detail in events
        if completed and tool == "cc" and action == "compile"
        and any(item[1] in source_hashes for item in detail["inputs"])
    ]
    object_hashes = {detail["output"][1] for detail in compilations}
    for tool, action, token, completed, cc_link in events:
        if not (completed and tool == "cc" and action == "link" and token != "-"):
            continue
        if not any(item[1] in object_hashes for item in cc_link["inputs"]):
            continue
        if cc_link["text"] not in wheel_text_hashes:
            continue
        if any(
            other_tool == "ld" and other_action == "link" and other_token == token
            and other_completed and other_detail["text"] == cc_link["text"]
            and other_detail["output"] == cc_link["output"]
            and any(item[1] in object_hashes for item in other_detail["inputs"])
            for other_tool, other_action, other_token, other_completed, other_detail in events
        ):
            return
    raise ValueError("Native build outputs do not connect source, object, link, and wheel.")


def _tool_trace(path_value, sources, wheels, source_hashes, wheel_text_hashes):
    lines = _trace_lines(path_value)
    sections = {}
    position = 0

    if lines[:1] != ["phase|driver-check|start"]:
        raise ValueError("Compiler-driver check trace is missing.")
    try:
        driver_end = lines.index("phase|driver-check|end", 1)
    except ValueError as error:
        raise ValueError("Compiler-driver check trace is incomplete.") from error
    driver_lines = lines[1:driver_end]
    driver_events = [_trace_event(line, "driver-check") for line in driver_lines]
    if not any(
        tool == "cc" and action == "compile" and completed
        for tool, action, _token, completed, _detail in driver_events
    ):
        raise ValueError("Compiler-driver compilation check is incomplete.")
    _require_driver_link(driver_events)
    sections["driver-check"] = driver_lines
    position = driver_end + 1

    for name in ("pycairo", "PyGObject"):
        start = f"phase|{name}|start"
        source = f"artifact|{name}|source|{Path(sources[name]).name}"
        wheel = f"artifact|{name}|wheel|{Path(wheels[name]).name}"
        end = f"phase|{name}|end"
        if lines[position:position + 2] != [start, source]:
            raise ValueError("Build-tool execution trace input is invalid.")
        position += 2
        try:
            wheel_position = lines.index(wheel, position)
        except ValueError as error:
            raise ValueError("Build-tool execution trace output is missing.") from error
        event_lines = lines[position:wheel_position]
        events = [_trace_event(line, name) for line in event_lines]
        position = wheel_position + 1
        if position >= len(lines) or lines[position] != end:
            raise ValueError("Build-tool execution trace phase is incomplete.")
        observed = {
            (tool, action)
            for tool, action, _token, completed, _detail in events
            if completed
        }
        if name == "pycairo" and any(
            tool in {"meson", "ninja"}
            for tool, _action, _token, _completed, _detail in events
        ):
            raise ValueError("Build-tool execution trace uses the wrong backend.")
        if not TRACE_REQUIREMENTS[name].issubset(observed):
            raise ValueError("Build-tool execution trace lacks completed build operations.")
        _require_driver_link(events)
        _require_native_chain(events, source_hashes[name], wheel_text_hashes[name])
        sections[name] = event_lines
        position += 1
    if position != len(lines):
        raise ValueError("Build-tool execution trace contains unrelated events.")
    return sections


def create_report(args, distribution_version=importlib.metadata.version):
    sources = _named_values(args.source, "source")
    source_urls = _named_values(args.source_url, "source-url")
    wheels = _named_values(args.wheel, "wheel")
    native_packages = _named_values(
        args.native_package,
        "native-package",
    )
    build_tools = _named_values(args.build_tool, "build-tool")
    build_tool_versions = _named_values(
        args.build_tool_version,
        "build-tool-version",
    )
    tool_proxies = _named_values(args.tool_proxy, "tool-proxy")

    if set(sources) != REQUIRED_SOURCES:
        raise ValueError("Required source provenance is incomplete.")
    if set(source_urls) != REQUIRED_SOURCES:
        raise ValueError("Required source URLs are incomplete.")
    if set(wheels) != REQUIRED_WHEELS:
        raise ValueError("Required wheel provenance is incomplete.")
    if set(native_packages) != REQUIRED_NATIVE_PACKAGES:
        raise ValueError("Required native package provenance is incomplete.")
    _require_single_line_values(
        native_packages.values(),
        "A native package version is not a single text line.",
    )
    if set(build_tools) != REQUIRED_BUILD_TOOLS:
        raise ValueError("Required build-tool identities are incomplete.")
    if set(build_tool_versions) != REQUIRED_BUILD_TOOLS:
        raise ValueError("Required build-tool versions are incomplete.")
    if set(tool_proxies) != REQUIRED_BUILD_TOOLS:
        raise ValueError("Required build-tool proxies are incomplete.")
    if args.linker_selector != "bfd":
        raise ValueError("The GCC linker selector is unsupported.")
    expected_proxy_names = {
        "cc": "cc",
        "ld": "ld.bfd",
        "meson": "meson",
        "ninja": "ninja",
        "pkg-config": "pkg-config",
    }
    resolved_proxies = []
    for name, path_value in tool_proxies.items():
        path = Path(path_value)
        file_stat = path.lstat()
        if (
            path.name != expected_proxy_names[name]
            or not stat.S_ISREG(file_stat.st_mode)
            or not os.access(path, os.X_OK)
        ):
            raise ValueError("A build-tool proxy identity is invalid.")
        resolved_proxies.append(str(path.resolve(strict=True)))
    if len(set(resolved_proxies)) != len(resolved_proxies):
        raise ValueError("Build-tool proxy identities are not distinct.")
    if (
        str(Path(args.linker_discovery).resolve(strict=True))
        != str(Path(tool_proxies["ld"]).resolve(strict=True))
    ):
        raise ValueError("Compiler-driver linker discovery is inconsistent.")
    resolved_build_tools = []
    for path_value in build_tools.values():
        path = Path(path_value)
        file_stat = path.lstat()
        if not stat.S_ISREG(file_stat.st_mode) or not os.access(path, os.X_OK):
            raise ValueError("A build-tool executable identity is invalid.")
        resolved_build_tools.append(str(path.resolve(strict=True)))
    if len(set(resolved_build_tools)) != len(resolved_build_tools):
        raise ValueError("Build-tool executable identities are not distinct.")
    if set(resolved_build_tools).intersection(resolved_proxies):
        raise ValueError("A build-tool proxy would delegate recursively.")
    _require_single_line_values(
        build_tool_versions.values(),
        "A build-tool version is not a single text line.",
    )
    requirements = _requirements_inventory(args.requirements)
    distributions = _distribution_inventory(
        args.distribution,
        distribution_version,
    )
    if args.builder_os != "ubuntu-22.04":
        raise ValueError("The builder OS is not Ubuntu 22.04.")
    if args.architecture != "x86_64":
        raise ValueError("The builder architecture is not x86-64.")
    if not Path(args.interpreter_invocation).is_absolute():
        raise ValueError("The interpreter invocation path is not absolute.")

    verification_path = Path(args.verification)
    verification = json.loads(
        verification_path.read_text(encoding="utf-8")
    )
    if set(verification) != REQUIRED_VERIFICATION_KEYS:
        raise ValueError("Binding verification evidence is incomplete.")
    if verification["bindings"] != {
        "PyGObject": "3.48.2",
        "pycairo": "1.26.1",
    }:
        raise ValueError("Binding versions do not match the G1 pins.")
    if verification["required_namespaces"] != EXPECTED_NAMESPACES:
        raise ValueError("Required GI namespace versions were not verified.")
    if verification["python"].get("implementation") != "CPython":
        raise ValueError("The verified interpreter is not CPython.")
    if PYTHON_VERSION_PATTERN.fullmatch(
        verification["python"].get("version", "")
    ) is None:
        raise ValueError("The verified interpreter is not Python 3.12.")
    if not isinstance(verification["native"], dict):
        raise ValueError("Required native version evidence is incomplete.")
    if set(verification["native"]) != REQUIRED_NATIVE_VERSION_FIELDS or not all(
        isinstance(value, str) and value
        for value in verification["native"].values()
    ):
        raise ValueError("Required native version evidence is incomplete.")
    _require_version_values(
        verification["native"].values(),
        NATIVE_VERSION_PATTERN,
        "Required native version evidence is invalid.",
    )
    if source_urls != EXPECTED_SOURCE_URLS:
        raise ValueError("Official source identities do not match the pins.")

    compiler_evidence_paths = _named_values(
        args.compiler_evidence, "compiler-evidence"
    )
    if set(compiler_evidence_paths) != {"PyGObject"}:
        raise ValueError("Compiler evidence is incomplete.")
    tool_trace_path = Path(args.tool_trace)
    compiler_evidence = {}
    for name, path in compiler_evidence_paths.items():
        evidence_path = Path(path)
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("Compiler evidence is invalid.") from error
        compiler = _compiler_evidence(
            evidence,
            tool_proxies["cc"],
            args.linker_selector,
            build_tool_versions["cc"],
            build_tool_versions["ld"],
        )
        compiler_evidence[name] = (evidence_path, evidence, compiler)

    source_metadata = {}
    source_hashes = {}
    wheel_text_hashes = {}
    for name, expected_version in {
        "PyGObject": "3.48.2",
        "pycairo": "1.26.1",
    }.items():
        source_metadata[name] = _source_metadata(
            sources[name], name, expected_version
        )
        source_hashes[name] = source_metadata[name].pop("source_input_hashes")
        wheel_text_hashes[name] = _wheel_metadata(wheels[name], name, expected_version)
    trace_sections = _tool_trace(
        tool_trace_path, sources, wheels, source_hashes, wheel_text_hashes
    )

    toolchain_artifacts = [
        _regular_file_record(path)
        for path in sorted(args.toolchain_artifact)
    ]
    if len(args.toolchain_artifact) != len(EXPECTED_TOOLCHAIN_DISTRIBUTIONS) or len(
        {str(Path(path).resolve(strict=True)) for path in args.toolchain_artifact}
    ) != len(args.toolchain_artifact):
        raise ValueError("Pinned toolchain artifacts are not distinct.")
    expected_toolchain = {
        canonicalize_name(name): version
        for name, version in EXPECTED_TOOLCHAIN_DISTRIBUTIONS.items()
    }
    observed_toolchain = {}
    for path in args.toolchain_artifact:
        try:
            name, version, _build, _tags = parse_wheel_filename(Path(path).name)
        except (TypeError, ValueError) as error:
            raise ValueError("Pinned toolchain artifact metadata is invalid.") from error
        canonical_name = canonicalize_name(name)
        if (
            canonical_name not in expected_toolchain
            or str(version) != expected_toolchain[canonical_name]
            or canonical_name in observed_toolchain
        ):
            raise ValueError("Pinned toolchain artifact metadata is inconsistent.")
        observed_toolchain[canonical_name] = str(version)
        _wheel_metadata(
            path,
            canonical_name,
            expected_toolchain[canonical_name],
        )
    if observed_toolchain != expected_toolchain:
        raise ValueError("Pinned toolchain artifact inventory is incomplete.")

    return {
        "architecture": args.architecture,
        "builder_os": args.builder_os,
        "distributions": distributions,
        "build_tools": {
            name: {
                **_regular_file_record(build_tools[name]),
                "resolved_path": str(Path(build_tools[name]).resolve(strict=True)),
                "version": build_tool_versions[name],
            }
            for name in sorted(build_tools)
        },
        "interpreter": {
            "binary": _regular_file_record(args.interpreter),
            "invocation_path": args.interpreter_invocation,
        },
        "native_package_archives": {
            "availability": args.native_archive_provenance,
            "required_before": "G2-freeze",
        },
        "native_packages": dict(sorted(native_packages.items())),
        "requirements": [
            {
                **_regular_file_record(path),
                "pins": requirements[Path(path).name],
            }
            for path in sorted(args.requirements)
        ],
        "sources": {
            name: {
                **_regular_file_record(sources[name]),
                **source_metadata[name],
                "official_project_url": source_urls[name],
            }
            for name in sorted(sources)
        },
        "toolchain_artifacts": toolchain_artifacts,
        "tool_trace": _regular_file_record(args.tool_trace),
        "tool_trace_sections": trace_sections,
        "tool_proxies": {
            name: _regular_file_record(tool_proxies[name])
            for name in sorted(tool_proxies)
        },
        "compiler_evidence": {
            name: {
                "evidence": evidence,
                "file": _regular_file_record(path),
                "validated_compiler": compiler,
            }
            for name, (path, evidence, compiler) in compiler_evidence.items()
        },
        "tool_selection": {
            "basis": "configured-and-traced-build-tools",
            "actual_build_evidence": "backend-contract-wheel-and-completed-trace",
            "compiler_driver_linker_discovery": args.linker_discovery,
            "linker_selector": args.linker_selector,
        },
        "verification": verification,
        "verification_file": _regular_file_record(verification_path),
        "wheels": {
            name: _regular_file_record(wheels[name])
            for name in sorted(wheels)
        },
    }


def write_report_exclusively(output_path, report):
    encoded = (
        json.dumps(
            report,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")
    descriptor = os.open(
        output_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as output_file:
        output_file.write(encoded)


def _proxy_output_watch(output):
    if output is None:
        return None
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if descriptor < 0:
        return None
    watched = libc.inotify_add_watch(
        descriptor,
        os.fsencode(str(output.parent)),
        0x00000008 | 0x00000080,  # close-write, moved-to
    )
    if watched < 0:
        os.close(descriptor)
        return None
    return descriptor


def _proxy_output_produced(descriptor, output):
    if descriptor is None or output is None:
        return False
    produced = False
    try:
        while True:
            try:
                batch = os.read(descriptor, 65536)
            except BlockingIOError:
                break
            if not batch:
                return False
            cursor = 0
            while cursor < len(batch):
                if len(batch) - cursor < 16:
                    return False
                watch, mask, _, name_length = struct.unpack_from("iIII", batch, cursor)
                if name_length % 4 or name_length > len(batch) - cursor - 16:
                    return False
                if (watch < 0 or mask == 0 or mask & (0x00004000 | 0x00008000 |
                                        0x00002000 | 0x00000400 | 0x00000800)):
                    # Overflow, ignored watch, unmount, delete-self, move-self.
                    return False
                raw_name = batch[cursor + 16:cursor + 16 + name_length]
                if not raw_name or b"\0" not in raw_name:
                    return False
                name, padding = raw_name.split(b"\0", 1)
                if not name or padding.strip(b"\0"):
                    return False
                if name == os.fsencode(output.name) and mask & 0x00000088:
                    produced = True
                cursor += 16 + name_length
    finally:
        os.close(descriptor)
    return produced


def _proxy_file_identity(path):
    if not path.is_file() or path.stat().st_size > MAX_NATIVE_MEMBER_BYTES:
        return None
    return [str(path.resolve()), _regular_file_record(path)["sha256"]]


def _encode_operation_detail(inputs, output, text_digest, produced):
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {"inputs": inputs, "output": output, "text": text_digest,
             "produced": produced},
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii")
    if len(encoded) > MAX_TRACE_DETAIL_BYTES:
        raise ValueError("Build-tool operation exceeds the trace detail limit.")
    return encoded


def _proxy_mark_trace_failure():
    trace = os.environ.get("G1_TOOL_TRACE")
    if not trace:
        return
    try:
        descriptor = os.open(
            trace + ".failed", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
    except FileExistsError:
        return
    except OSError:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _proxy_pending_start(binding, phase):
    directory = Path(os.environ["G1_TOOL_TRACE"] + ".pending")
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise OSError("Build-tool recording directory is invalid.")
    for _ in range(3):
        path = directory / (
            f"{binding}-{phase}-{os.getpid()}-{secrets.token_hex(8)}"
        )
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(descriptor)
        return path
    raise OSError("Could not allocate a unique build-tool recording entry.")


def _run_proxy(tool, target_variable, proxy_path, arguments):
    targets = {
        "cc": "G1_REAL_CC",
        "ld": "G1_REAL_CC_LD",
        "meson": "G1_REAL_MESON",
        "ninja": "G1_REAL_NINJA",
        "pkg-config": "G1_REAL_PKG_CONFIG",
    }
    binding = os.environ.get("G1_BUILD_BINDING")
    phase = os.environ.get("G1_BUILD_OPERATION")
    if tool not in targets or (binding, phase) not in {
        ("driver-check", "driver-check"),
        *((name, operation) for name in ("pycairo", "PyGObject")
          for operation in ("metadata", "wheel", "install")),
    }:
        return 96
    if not re.fullmatch(r"G1_[A-Z_]+", target_variable):
        return 96
    target = os.environ.get(target_variable)
    if not target or Path(target).resolve() == Path(proxy_path).resolve():
        return 96
    query = any(
        arg in {"--version", "-dumpversion", "-dumpfullversion", "-Wl,--version"}
        or arg.startswith("-print-prog-name=")
        for arg in arguments
    )
    output = None
    for index, arg in enumerate(arguments[:-1]):
        if arg == "-o":
            output = Path(arguments[index + 1]).absolute()
    if tool == "cc":
        if query:
            action = "query"
        elif "-c" in arguments and output and output.name.endswith(".o") and any(
            arg.endswith(".c") and Path(arg).is_file() for arg in arguments
        ):
            action = "compile"
        elif "-shared" in arguments and output and ".so" in output.name and any(
            arg.endswith(".o") and Path(arg).is_file() for arg in arguments
        ):
            action = "link"
        else:
            action = "probe"
    elif tool == "ld":
        action = "query" if query else "link"
    else:
        action = "query" if query else "run"
    token = "-"
    if tool == "cc" and action == "link":
        token = str(os.getpid())
        os.environ["G1_DRIVER_OPERATION_ID"] = token
    elif tool == "ld" and action == "link":
        token = os.environ.get("G1_DRIVER_OPERATION_ID", "-")
        if not token.isdigit() or len(token) > 20:
            token = "-"
    else:
        os.environ.pop("G1_DRIVER_OPERATION_ID", None)
    inputs = []
    if action in {"compile", "link"}:
        suffix = ".c" if action == "compile" else ".o"
        for arg in arguments:
            if arg.endswith(suffix) and Path(arg).is_file():
                identity = _proxy_file_identity(Path(arg))
                if identity is not None:
                    inputs.append(identity)
    command = [target, *arguments]
    if tool == "cc":
        command = [
            target,
            f"-B{os.environ['G1_LINKER_PROXY_DIRECTORY']}/",
            f"-fuse-ld={os.environ['G1_LINKER_SELECTOR']}",
            *arguments,
        ]
    watch = _proxy_output_watch(output) if action in {"compile", "link"} else None
    try:
        pending_path = _proxy_pending_start(binding, phase)
    except Exception:
        if watch is not None:
            os.close(watch)
        _proxy_mark_trace_failure()
        return 74
    child = None
    interrupted = None
    interrupted_at = None

    def forward(signum, _frame):
        nonlocal interrupted, interrupted_at
        if interrupted is None:
            interrupted, interrupted_at = signum, time.monotonic()
        if child is not None:
            try:
                os.killpg(child.pid, signum)
            except ProcessLookupError:
                pass

    handled = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)
    original_handlers = {number: signal.getsignal(number) for number in handled}
    for number in handled:
        signal.signal(number, forward)
    try:
        if interrupted is None:
            child = subprocess.Popen(command, start_new_session=True)
        if child is not None and interrupted is not None:
            forward(interrupted, None)
        if child is None:
            returncode = -interrupted
        else:
            while True:
                try:
                    returncode = child.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if interrupted_at is not None and time.monotonic() - interrupted_at > 2:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
    finally:
        for number, original in original_handlers.items():
            signal.signal(number, original)
    status = (
        128 + interrupted if interrupted is not None
        else 128 - returncode if returncode < 0
        else returncode
    )
    signum = interrupted or (-returncode if returncode < 0 else None)
    evidence_failed = False
    try:
        produced = _proxy_output_produced(watch, output)
        outcome = "complete" if returncode == 0 and interrupted is None else "failed"
        detail = "-"
        if action in {"compile", "link"} and outcome == "complete":
            output_identity = _proxy_file_identity(output) if output else None
            if not produced or output_identity is None or not inputs:
                outcome = "missing-output"
            elif tool == "ld" and token == "-":
                outcome = "unattributed"
            else:
                text_digest = None
                if action == "link":
                    try:
                        text_digest = _elf_text_digest(output.read_bytes())
                    except ValueError:
                        outcome = "missing-output"
                if outcome == "complete":
                    detail = _encode_operation_detail(
                        inputs, output_identity, text_digest, produced
                    )
        if outcome == "missing-output":
            evidence_failed = True
            _proxy_mark_trace_failure()
        if phase in {"wheel", "driver-check"}:
            line = f"result|{binding}|{tool}|{action}|{status}|{outcome}|{token}|{detail}\n"
            descriptor = os.open(
                os.environ["G1_TOOL_TRACE"],
                os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600,
            )
            try:
                encoded_line = line.encode("utf-8")
                if os.write(descriptor, encoded_line) != len(encoded_line):
                    raise OSError("Build-tool trace write was incomplete.")
            finally:
                os.close(descriptor)
        if not evidence_failed:
            pending_path.unlink()
    except Exception:
        evidence_failed = True
        _proxy_mark_trace_failure()
    finally:
        if signum is not None:
            if signum not in {signal.SIGKILL, signal.SIGSTOP}:
                signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)
    if evidence_failed and status == 0:
        return 74
    return status


def main(argv=None, distribution_version=importlib.metadata.version):
    try:
        args = _arguments(argv)
        report = create_report(args, distribution_version=distribution_version)
        write_report_exclusively(args.output, report)
    except Exception as error:
        print(
            f"Linux tray provenance failed: {type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "--proxy":
        raise SystemExit(_run_proxy(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]))
    raise SystemExit(main())
