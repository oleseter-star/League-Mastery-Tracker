import base64
import hashlib
import importlib.util
import io
import json
import os
import signal
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename


class LinuxTrayGateConfigurationTests(unittest.TestCase):
    PYGOBJECT_GI_SOURCES = (
        "pygboxed", "pygenum", "pygflags", "pyginterface", "pygobject-object",
        "pygparamspec", "pygpointer", "pygoptioncontext", "pygoptiongroup",
        "pygspawn", "gimodule", "pygi-repository", "pygi-info", "pygi-foreign",
        "pygi-struct", "pygi-source", "pygi-argument", "pygi-resulttuple",
        "pygi-type", "pygi-boxed", "pygi-closure", "pygi-ccallback", "pygi-util",
        "pygi-property", "pygi-signal-closure", "pygi-invoke", "pygi-cache",
        "pygi-marshal-cleanup", "pygi-basictype", "pygi-list", "pygi-array",
        "pygi-error", "pygi-object", "pygi-fundamental", "pygi-value",
        "pygi-enum-marshal", "pygi-struct-marshal", "pygi-hashtable",
    )

    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.runner = (
            cls.project_root
            / "packaging"
            / "linux"
            / "run_tray_gates.sh"
        )
        cls.provisioner = (
            cls.project_root
            / "packaging"
            / "linux"
            / "provision_tray_lab.sh"
        )
        cls.verifier_path = (
            cls.project_root
            / "packaging"
            / "linux"
            / "probe"
            / "verify_bindings.py"
        )
        cls.provenance_path = (
            cls.project_root
            / "packaging"
            / "linux"
            / "capture_tray_provenance.py"
        )
        cls.runner_source = cls.runner.read_text(encoding="utf-8")
        cls.provisioner_source = cls.provisioner.read_text(
            encoding="utf-8"
        )

    def test_binding_and_build_inputs_are_exactly_pinned(self):
        binding_requirements = self._requirement_map(
            "requirements-linux-tray.txt"
        )
        self.assertEqual(
            binding_requirements,
            {
                "PyGObject": "3.48.2",
                "pycairo": "1.26.1",
            },
        )
        build_requirements = self._requirement_map(
            "requirements-linux-tray-build.txt"
        )
        self.assertEqual(build_requirements["pyinstaller"], "6.21.0")
        self.assertEqual(
            build_requirements["pyinstaller-hooks-contrib"],
            "2026.6",
        )
        self.assertTrue(
            all(version for version in build_requirements.values())
        )

    def test_runner_rejects_every_unimplemented_gate(self):
        for gate in ("G2", "G3", "G4", "G5", "G6", "G7"):
            result = subprocess.run(
                ["bash", str(self.runner), gate],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn(
                f"{gate} is not implemented in Slice 1A.",
                result.stderr,
            )
            self.assertNotIn("passed", result.stderr.lower())

    def test_runner_rejects_repository_and_project_venv_work_roots(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker = Path(temporary_directory) / "downstream-called"
            for rejected_root in (
                self.project_root / "gate-output",
                self.project_root / ".venv" / "gate-output",
            ):
                command = (
                    'source "$1"; shift; DOWNSTREAM_MARKER=$1; shift; '
                    'verify_builder_platform() { return 0; }; '
                    'verify_interpreter() { : >"$DOWNSTREAM_MARKER"; '
                    'return 97; }; set +e; '
                    'value="$(run_g1 /never-used "$1")"; status=$?; '
                    '[[ $status -ne 0 && -z $value && '
                    '! -e $DOWNSTREAM_MARKER ]]'
                )
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        command,
                        "gate-test",
                        str(self.runner),
                        str(marker),
                        str(rejected_root),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("outside the repository", result.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse(rejected_root.exists())

    def test_work_root_validation_succeeds_for_one_safe_new_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate = Path(temporary_directory) / "new-work-root"
            command = (
                'source "$1"; value="$(validate_work_root "$2")"; '
                '[[ $value == "$2" && ! -e $value ]]'
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "gate-test",
                    str(self.runner),
                    str(candidate),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(candidate.exists())

    def test_runner_requires_explicit_interpreter_and_new_absolute_root(self):
        for arguments in (["G1"], ["G1", "--python"]):
            result = subprocess.run(
                ["bash", str(self.runner), *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
        for helper, value in (
            ("verify_interpreter", "python3"),
            ("validate_work_root", "relative"),
        ):
            result = subprocess.run(
                [
                    "bash", "-c", 'source "$1"; "$2" "$3"',
                    "gate-test", str(self.runner), helper, value,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_artifact_selection_propagates_zero_and_multiple_matches(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for count in (0, 2):
                for path in root.glob("*.whl"):
                    path.unlink()
                for index in range(count):
                    (root / f"artifact-{index}.whl").touch()
                command = (
                    'source "$1"; set +e; '
                    'value="$(one_file_matching "$2" "*.whl")"; '
                    'status=$?; [[ $status -ne 0 && -z $value ]]'
                )
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        command,
                        "gate-test",
                        str(self.runner),
                        str(root),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("expected exactly one artifact", result.stderr)

    def test_artifact_selection_has_a_single_match_positive_control(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "only.whl"
            artifact.touch()
            command = (
                'source "$1"; value="$(one_file_matching "$2" "*.whl")"; '
                '[[ $value == "$2/only.whl" ]]'
            )
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "gate-test",
                    str(self.runner),
                    str(artifact.parent),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_builder_checks_reject_missing_prerequisites(self):
        command = (
            'source "$1"; '
            'cc() { return 0; }; '
            'dpkg-query() { return 1; }; '
            'ninja() { return 0; }; '
            'pkg-config() { return 0; }; '
            "verify_build_prerequisites"
        )
        result = subprocess.run(
            ["bash", "-c", command, "gate-test", str(self.runner)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("required G1 build package", result.stderr)

    def test_builder_checks_reject_wrong_platform_and_architecture(self):
        cases = (
            'read_builder_release() { printf "debian 12\\n"; }; '
            'builder_architecture() { printf "x86_64\\n"; };',
            'read_builder_release() { printf "ubuntu 22.04\\n"; }; '
            'builder_architecture() { printf "aarch64\\n"; };',
        )
        for setup in cases:
            command = f'source "$1"; {setup} verify_builder_platform'
            result = subprocess.run(
                ["bash", "-c", command, "gate-test", str(self.runner)],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("G1 requires", result.stderr)

    def test_platform_reader_failure_after_valid_output_stops_downstream(self):
        command = (
            'source "$1"; '
            'read_builder_release() { printf "ubuntu 22.04\\n"; return 23; }; '
            'builder_architecture() { printf "x86_64\\n"; }; '
            'set +e; verify_builder_platform; status=$?; '
            '[[ $status -eq 23 ]]'
        )
        result = subprocess.run(
            ["bash", "-c", command, "gate-test", str(self.runner)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_artifact_inventory_failure_has_no_success_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "inventory"
            command = (
                'source "$1"; '
                'find() { printf "valid\\0"; return 23; }; '
                'set +e; write_artifact_inventory "$2" "$3"; status=$?; '
                '[[ $status -eq 23 && ! -e $3 ]]'
            )
            result = subprocess.run(
                [
                    "bash", "-c", command, "gate-test", str(self.runner),
                    str(root), str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_stubbed_g1_orchestration_stops_before_evidence_on_binding_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "work"
            marker = Path(temporary_directory) / "events"
            command = r'''
source "$1"
TRACE=$2
FAKE_MESON="$2.meson"
printf '#!/bin/sh\nprintf "{}"\n' >"$2.meson"
chmod +x "$2.meson"
FAKE_MESON="$2.meson"
record() { printf '%s\n' "$1" >>"$TRACE"; }
validate_work_root() { printf '%s\n' "$1"; }
verify_builder_platform() { record platform; }
verify_interpreter() { record interpreter; }
verify_build_prerequisites() { record prerequisites; }
select_build_tools() {
  record tools
  G1_CC_PATH=/cc G1_LD_PATH=/ld G1_MESON_PATH="$FAKE_MESON"
  G1_NINJA_PATH=/ninja G1_PKG_CONFIG_PATH=/pkg
  G1_CC_VERSION=cc G1_LD_VERSION=ld G1_MESON_VERSION=meson
  G1_NINJA_VERSION=ninja G1_PKG_CONFIG_VERSION=pkg
}
configure_traced_build_tools() { record trace; }
verify_compiler_driver_linker() { record driver; }
acquire_and_build_bindings() { record bindings; return 23; }
run_isolated_pip() { record pip; }
run_isolated_python() {
  record python
  for arg in "$@"; do
    if [[ ${previous:-} == --output ]]; then : >"$arg"; fi
    previous=$arg
  done
}
write_artifact_inventory() { record inventory; }
dpkg-query() { printf '1\n'; }
set +e
run_g1 "$3" "$4"
status=$?
printf 'status=%s\n' "$status"
[[ $status -eq 23 && ! -e "$4/reports/provenance.json" ]]
'''
            result = subprocess.run(
                [
                    "bash", "-c", command, "gate-test", str(self.runner),
                    str(marker), sys.executable, str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=23", result.stdout)
            self.assertNotIn("G1 passed", result.stdout)

    def test_stubbed_g1_orchestration_reaches_success_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "work"
            result = self._run_stubbed_g1(
                Path(temporary_directory), root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("G1 passed", result.stdout)
            report = json.loads(
                (root / "reports" / "provenance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                report["tool_selection"]["actual_build_evidence"],
                "backend-contract-wheel-and-completed-trace",
            )
            self.assertTrue(report["sources"])
            self.assertTrue(report["wheels"])
            self.assertEqual(
                report["sources"]["pycairo"]["build_backend"],
                "setuptools.build_meta",
            )
            self.assertEqual(
                report["sources"]["PyGObject"]["build_backend"],
                "mesonpy",
            )
            self.assertEqual(set(report["compiler_evidence"]), {"PyGObject"})
            self.assertFalse(
                any(
                    "|meson|" in event or "|ninja|" in event
                    for event in report["tool_trace_sections"]["pycairo"]
                )
            )
            self.assertTrue(any(
                "|cc|query|0|complete|-|-" in event
                for event in report["tool_trace_sections"]["PyGObject"]
            ))
            self.assertTrue(any(
                "|ld|query|0|complete|-|-" in event
                for event in report["tool_trace_sections"]["PyGObject"]
            ))

    def test_unchanged_stale_outputs_cannot_publish_g1_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            case = Path(temporary_directory) / "stale"
            work = case / "work"
            result = self._run_stubbed_g1(case, work, "stale-output")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("G1 passed", result.stdout)
            self.assertFalse((work / "reports" / "provenance.json").exists())
            self.assertIn("|PyGObject|cc|compile|0|missing-output|",
                          (work / "tmp" / "build-tool-trace.txt").read_text())

    def test_identical_byte_rebuild_still_counts_as_fresh_output(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            case = Path(temporary_directory) / "same-byte"
            work = case / "work"
            result = self._run_stubbed_g1(case, work, "same-byte-rebuild")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((work / "reports" / "provenance.json").is_file())

    def test_stubbed_g1_failures_cannot_publish_success(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            expectations = {
                "platform": ("platform", ("pip", "binding:pycairo:metadata", "collector")),
                "tool-identity": (
                    "tool:cc:--version",
                    ("binding:pycairo:metadata", "collector"),
                ),
                "metadata": ("binding:PyGObject:metadata", ("collector",)),
                "inventory": ("introspect", ("collector",)),
                "provenance": ("collector", ()),
                "driver-bypass": ("collector", ()),
                "version-only": ("collector", ()),
                "wrong-backend": ("collector", ()),
            }
            for failure, (last_required, prohibited) in expectations.items():
                with self.subTest(failure=failure):
                    case = base / failure
                    root = case / "work"
                    result = self._run_stubbed_g1(case, root, failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("G1 passed", result.stdout)
                    self.assertFalse(
                        (root / "reports" / "provenance.json").exists()
                    )
                    events = (case / "orchestration-events").read_text(
                        encoding="utf-8"
                    ).splitlines()
                    self.assertIn(last_required, events)
                    for event in prohibited:
                        self.assertNotIn(event, events)

    def test_interpreter_check_rejects_non_cpython_312(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_interpreter = Path(temporary_directory) / "python"
            fake_interpreter.write_text(
                "#!/bin/sh\nexit 1\n",
                encoding="utf-8",
            )
            fake_interpreter.chmod(0o700)
            command = 'source "$1"; verify_interpreter "$2"'
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    command,
                    "gate-test",
                    str(self.runner),
                    str(fake_interpreter),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("CPython 3.12", result.stderr)

    def test_platform_and_interpreter_contract_has_no_fallback(self):
        self.assertIn("builder_id == ubuntu", self.runner_source)
        self.assertIn("builder_version == 22.04", self.runner_source)
        self.assertIn("architecture == x86_64", self.runner_source)
        self.assertIn(
            'platform.python_implementation() != "CPython"',
            self.runner_source,
        )
        self.assertIn(
            "sys.version_info[:2] != (3, 12)",
            self.runner_source,
        )
        self.assertNotIn("command -v python", self.runner_source)
        self.assertNotIn("python3 -", self.runner_source)

    def test_runner_never_provisions_or_returns_placeholder_success(self):
        for prohibited in (
            "apt-get",
            "provision_tray_lab.sh",
            "sudo ",
            "return 0 #",
        ):
            self.assertNotIn(prohibited, self.runner_source)
        self.assertIn("case \"$gate\"", self.runner_source)
        self.assertIn("not implemented in Slice 1A", self.runner_source)
        self.assertIn("set -euo pipefail", self.runner_source)

    def test_binding_build_executes_pycairo_before_pygobject_metadata(self):
        command = (
            'source "$1"; '
            'run_binding_pip() { printf "%s\\n" "$*"; }; '
            'record_build_phase() { printf "phase %s %s\\n" "$1" "$2"; }; '
            'record_build_artifact() { printf "artifact %s %s %s\\n" "$@"; }; '
            'one_file_matching() { '
            'case "$2" in pycairo-*.whl) printf "/wheels/pycairo.whl\\n";; '
            'pycairo-*) printf "/sources/pycairo.tar.gz\\n";; '
            'pygobject-*.whl) printf "/wheels/pygobject.whl\\n";; '
            'pygobject-*) printf "/sources/pygobject.tar.gz\\n";; esac; }; '
            'acquire_and_build_bindings /env/python /sources /wheels /build'
        )
        result = subprocess.run(
            ["bash", "-c", command, "gate-test", str(self.runner)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        events = result.stdout.splitlines()
        cairo_download = next(
            index for index, event in enumerate(events)
            if "download" in event and "pycairo==1.26.1" in event
        )
        cairo_install = next(
            index for index, event in enumerate(events)
            if "install" in event and "pycairo.whl" in event
        )
        pygobject_download = next(
            index for index, event in enumerate(events)
            if "download" in event and "PyGObject==3.48.2" in event
        )
        self.assertLess(cairo_download, cairo_install)
        self.assertLess(cairo_install, pygobject_download)
        cairo_wheel = next(
            event for event in events if event.startswith("pycairo wheel ")
        )
        pygobject_wheel = next(
            event for event in events if event.startswith("PyGObject wheel ")
        )
        self.assertNotIn("build-dir", cairo_wheel)
        self.assertIn("--config-settings=build-dir=/build/pygobject", pygobject_wheel)
        self.assertEqual(sum(" download " in f" {e} " for e in events), 2)
        self.assertEqual(
            sum(
                event.split()[:2]
                in (["pycairo", "wheel"], ["PyGObject", "wheel"])
                for event in events
            ),
            2,
        )
        self.assertEqual(sum(" install " in f" {e} " for e in events), 2)

    def test_binding_build_stops_at_a_mocked_metadata_failure(self):
        command = (
            'source "$1"; set +e; '
            'run_binding_pip() { printf "%s\\n" "$*"; '
            '[[ $* != *"PyGObject==3.48.2"* ]]; }; '
            'record_build_phase() { printf "phase %s %s\\n" "$1" "$2"; }; '
            'record_build_artifact() { printf "artifact %s %s %s\\n" "$@"; }; '
            'one_file_matching() { '
            'case "$2" in *.whl) printf "/wheels/result.whl\\n";; '
            '*) printf "/sources/result.tar.gz\\n";; esac; }; '
            'acquire_and_build_bindings /env/python /sources /wheels /build; '
            'status=$?; printf "status=%s\\n" "$status"; '
            '[[ $status -ne 0 ]]'
        )
        result = subprocess.run(
            ["bash", "-c", command, "gate-test", str(self.runner)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PyGObject==3.48.2", result.stdout)
        events = [
            line for line in result.stdout.splitlines()
            if not line.startswith("status=")
        ]
        self.assertEqual(len(events), 8)
        self.assertIn("download", events[-1])
        self.assertIn("PyGObject==3.48.2", events[-1])

    def test_pip_and_backend_environment_is_explicitly_isolated(self):
        for required in (
            "PIP_CONFIG_FILE=/dev/null",
            "PYTHONDONTWRITEBYTECODE=1",
            "-u MESON",
            "-u PYTHONHOME",
            "-u PYTHONPATH",
            "-u GI_TYPELIB_PATH",
            "-u DISPLAY",
            "-u DBUS_SESSION_BUS_ADDRESS",
            '"MESON=$G1_MESON_PATH"',
            '"PATH=$environment_bin:/usr/bin:/bin"',
            "--native-archive-provenance unavailable",
        ):
            self.assertIn(required, self.runner_source)
        self.assertIn("-I -S -B -c", self.runner_source)
        self.assertNotIn('interpreter="$(realpath', self.runner_source)
        self.assertIn(
            'interpreter_identity="$(realpath -e -- "$interpreter")"',
            self.runner_source,
        )

    def test_tool_selection_uses_the_dedicated_environment(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            environment_bin = root / "environment" / "bin"
            environment_bin.mkdir(parents=True)
            events = root / "events"
            tools = {}
            for name in ("meson", "cc", "ld.bfd", "ninja", "pkg-config"):
                tool = environment_bin / name
                if name == "cc":
                    script = (
                        "#!/bin/sh\n"
                        f"printf 'cc:%s:%s\\n' \"$CC_LD\" \"$COMPILER_PATH\" >>'{events}'\n"
                        "if test \"$1\" = -print-prog-name=ld.bfd; then "
                        "echo ld.bfd; else echo cc-version; fi\n"
                    )
                else:
                    script = (
                        "#!/bin/sh\n"
                        f"printf '{name}:%s:%s\\n' \"$CC_LD\" \"$COMPILER_PATH\" >>'{events}'\n"
                        f"echo {name}-version\n"
                    )
                tool.write_text(
                    script,
                    encoding="utf-8",
                )
                tool.chmod(0o700)
                tools[name] = tool
            command = (
                'source "$1"; TEST_BIN=$2/bin; '
                'canonical_tool() { printf "%s/%s\\n" "$TEST_BIN" '
                '"${1##*/}"; }; '
                'G1_BOOTSTRAP_ENVIRONMENT=(env -u MESON -u CC_LD '
                '-u COMPILER_PATH CC_LD=controlled COMPILER_PATH=controlled); '
                'ISOLATED_ENVIRONMENT=("${G1_BOOTSTRAP_ENVIRONMENT[@]}"); '
                'select_build_tools "$2"; '
                'printf "meson=%s\\n" "$G1_MESON_PATH"; '
                'printf "%s\\n" "${ISOLATED_ENVIRONMENT[@]}"'
            )
            inherited = dict(os.environ)
            inherited.update(CC_LD="host-linker", COMPILER_PATH="host-search",
                             G1_PROXY_PYTHON=sys.executable)
            result = subprocess.run(
                [
                    "bash", "-c", command, "gate-test",
                    str(self.runner), str(root / "environment"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=inherited,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"meson={tools['meson']}", result.stdout)
            self.assertIn(f"MESON={tools['meson']}", result.stdout)
            self.assertIn(f"PATH={environment_bin}:/usr/bin:/bin", result.stdout)
            self.assertIn("CC_LD=bfd", result.stdout)
            self.assertNotIn("CC_LD=/", result.stdout)
            self.assertNotIn("host-linker", events.read_text(encoding="utf-8"))
            self.assertNotIn("host-search", events.read_text(encoding="utf-8"))

    def test_compiler_and_linker_proxies_preserve_arguments_and_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real = root / "real"
            proxies = root / "proxies"
            real.mkdir()
            arguments = root / "arguments"
            driver_arguments = root / "driver-arguments"
            environment = root / "environment"
            (root / "object.o").write_bytes(b"object")
            cc = real / "cc"
            cc.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$@\" >'{driver_arguments}'\n"
                "prefix=\n"
                "forward=()\n"
                "for argument in \"$@\"; do\n"
                "  case $argument in\n"
                "    -B*) prefix=${argument#-B} ;;\n"
                "    -fuse-ld=bfd) ;;\n"
                "    -print-prog-name=ld.bfd) printf '%sld.bfd\\n' \"$prefix\"; exit 0 ;;\n"
                "    *) forward+=(\"$argument\") ;;\n"
                "  esac\n"
                "done\n"
                "\"${prefix}ld.bfd\" \"${forward[@]}\"\n",
                encoding="utf-8",
            )
            linker = real / "ld.bfd"
            linker.write_text(
                "#!/bin/sh\n"
                f"printf '%s|%s\\n' \"$CC_LD\" \"${{COMPILER_PATH:-}}\" >'{environment}'\n"
                f"printf '%s\\n' \"$@\" >'{arguments}'\nexit 23\n",
                encoding="utf-8",
            )
            for tool in (cc, linker):
                tool.chmod(0o700)
            trace = root / "trace"
            command = (
                'source "$1"; '
                'G1_BOOTSTRAP_ENVIRONMENT=(env -u CC_LD -u COMPILER_PATH); '
                'G1_CC_PATH=$2; G1_LD_PATH=$3; '
                'G1_MESON_PATH=/bin/true; G1_NINJA_PATH=/bin/true; '
                'G1_PKG_CONFIG_PATH=/bin/true; '
                'configure_traced_build_tools "$4" "$5"; set +e; '
                'cd "$6"; '
                '"${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=pycairo '
                'G1_BUILD_OPERATION=wheel "$4/cc" object.o '
                '"argument with space" -shared '
                '-o module.so; status=$?; '
                '[[ $status -eq 23 ]]'
            )
            inherited = dict(os.environ)
            inherited.update(
                CC_LD="host-linker", COMPILER_PATH="host-search",
                G1_PROXY_PYTHON=sys.executable,
            )
            result = subprocess.run(
                [
                    "bash", "-c", command, "gate-test", str(self.runner),
                    str(cc), str(linker), str(proxies), str(trace), str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=inherited,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                arguments.read_text(encoding="utf-8").splitlines(),
                ["object.o", "argument with space", "-shared", "-o", "module.so"],
            )
            self.assertEqual(
                driver_arguments.read_text(encoding="utf-8").splitlines(),
                [
                    f"-B{proxies}/",
                    "-fuse-ld=bfd",
                    "object.o",
                    "argument with space",
                    "-shared",
                    "-o",
                    "module.so",
                ],
            )
            self.assertEqual(
                trace.read_text(encoding="utf-8").splitlines(),
                [
                    mock.ANY,
                    mock.ANY,
                ],
            )
            trace_lines = trace.read_text(encoding="utf-8").splitlines()
            self.assertRegex(
                trace_lines[0], r"^result\|pycairo\|ld\|link\|23\|failed\|\d+\|-$"
            )
            self.assertRegex(
                trace_lines[1], r"^result\|pycairo\|cc\|link\|23\|failed\|\d+\|-$"
            )
            self.assertEqual(trace_lines[0].split("|")[6], trace_lines[1].split("|")[6])
            self.assertEqual(environment.read_text(encoding="utf-8"), "bfd|\n")

    def test_compiler_proxy_does_not_classify_version_queries_as_builds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            real = root / "real"
            proxies = root / "proxies"
            real.mkdir()
            (root / "source.c").write_text("int x;\n", encoding="utf-8")
            (root / "unused.o").write_bytes(b"object")
            cc = real / "cc"
            cc.write_text(
                "#!/usr/bin/env bash\n"
                "prefix=\n"
                "for argument in \"$@\"; do\n"
                "  case $argument in\n"
                "    -B*) prefix=${argument#-B} ;;\n"
                "    -print-prog-name=ld.bfd) printf '%sld.bfd\\n' \"$prefix\"; exit ;;\n"
                "    --version) printf 'gcc version fixture\\n'; exit ;;\n"
                "  esac\n"
                "done\n",
                encoding="utf-8",
            )
            linker = real / "ld.bfd"
            linker.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            for tool in (cc, linker):
                tool.chmod(0o700)
            trace = root / "trace"
            command = (
                'source "$1"; '
                'G1_BOOTSTRAP_ENVIRONMENT=(env); '
                'G1_CC_PATH=$2; G1_LD_PATH=$3; '
                'G1_MESON_PATH=/bin/true; G1_NINJA_PATH=/bin/true; '
                'G1_PKG_CONFIG_PATH=/bin/true; '
                'configure_traced_build_tools "$4" "$5"; cd "$6"; '
                '"${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=pycairo '
                'G1_BUILD_OPERATION=wheel "$4/cc" --version -c source.c -o query.o; '
                '"${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=pycairo '
                'G1_BUILD_OPERATION=wheel "$4/cc" --version unused.o '
                '-shared -o query.so'
            )
            result = subprocess.run(
                [
                    "bash", "-c", command, "gate-test", str(self.runner),
                    str(cc), str(linker), str(proxies), str(trace), str(root),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=dict(os.environ, G1_PROXY_PYTHON=sys.executable),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                trace.read_text(encoding="utf-8").splitlines(),
                [
                    "result|pycairo|cc|query|0|complete|-|-",
                    "result|pycairo|cc|query|0|complete|-|-",
                ],
            )

    def test_tool_proxy_preserves_signal_termination(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            proxy = root / "pkg-config"
            trace = root / "trace"
            Path(str(trace) + ".pending").mkdir()
            target.write_text("#!/bin/sh\nkill -TERM $$\n", encoding="utf-8")
            target.chmod(0o700)
            create = subprocess.run(
                [
                    "bash", "-c",
                    'source "$1"; write_tool_proxy "$2" pkg-config G1_TARGET',
                    "gate-test", str(self.runner), str(proxy),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(create.returncode, 0, create.stderr)
            environment = dict(os.environ)
            environment.update(
                G1_BUILD_BINDING="pycairo",
                G1_BUILD_OPERATION="wheel",
                G1_TARGET=str(target),
                G1_TOOL_TRACE=str(trace),
                G1_PROXY_PYTHON=sys.executable,
            )
            result = subprocess.run(
                [str(proxy), "--cflags", "cairo"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=environment,
            )
            self.assertEqual(result.returncode, -15)
            self.assertEqual(
                trace.read_text(encoding="utf-8"),
                "result|pycairo|pkg-config|run|143|failed|-|-\n",
            )

    def test_all_proxies_keep_ordinary_exit_143_distinct_from_sigterm(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            target.write_text("#!/bin/sh\nexit 143\n", encoding="utf-8")
            target.chmod(0o700)
            for tool, writer, variable, arguments in (
                ("pkg-config", 'write_tool_proxy "$2" pkg-config G1_TARGET',
                 "G1_TARGET", ["--cflags"]),
                ("cc", 'write_compiler_proxy "$2"', "G1_REAL_CC", ["--version"]),
                ("ld.bfd", 'write_linker_proxy "$2"', "G1_REAL_CC_LD", ["--version"]),
            ):
                with self.subTest(tool=tool):
                    proxy = root / tool
                    trace = root / f"{tool}.trace"
                    Path(str(trace) + ".pending").mkdir()
                    create = subprocess.run(
                        ["bash", "-c", f'source "$1"; {writer}',
                         "gate-test", str(self.runner), str(proxy)],
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(create.returncode, 0, create.stderr)
                    env = dict(os.environ, G1_BUILD_BINDING="pycairo",
                               G1_BUILD_OPERATION="wheel", G1_TOOL_TRACE=str(trace),
                               G1_PROXY_PYTHON=sys.executable,
                               G1_LINKER_PROXY_DIRECTORY=str(root),
                               G1_LINKER_SELECTOR="bfd")
                    env[variable] = str(target)
                    result = subprocess.run([str(proxy), *arguments], env=env,
                                            capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 143, result.stderr)
                    self.assertIn("|143|failed|", trace.read_text())

    def test_all_proxies_forward_term_and_reap_a_live_child(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            target.write_text(
                f"#!{sys.executable}\n"
                "import os, signal, sys, time\n"
                "from pathlib import Path\n"
                "def stop(_signal, _frame):\n"
                "    Path(os.environ['STOPPED']).write_text('stopped')\n"
                "    sys.exit(0)\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "Path(os.environ['READY']).write_text(str(os.getpid()))\n"
                "while True: time.sleep(0.1)\n",
                encoding="utf-8",
            )
            target.chmod(0o700)
            for tool, writer, variable in (
                ("pkg-config", 'write_tool_proxy "$2" pkg-config G1_TARGET', "G1_TARGET"),
                ("cc", 'write_compiler_proxy "$2"', "G1_REAL_CC"),
                ("ld.bfd", 'write_linker_proxy "$2"', "G1_REAL_CC_LD"),
            ):
                with self.subTest(tool=tool):
                    proxy = root / tool
                    ready, stopped = root / f"{tool}.ready", root / f"{tool}.stopped"
                    Path(str(root / f"{tool}.trace") + ".pending").mkdir()
                    create = subprocess.run(
                        ["bash", "-c", f'source "$1"; {writer}',
                         "gate-test", str(self.runner), str(proxy)],
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(create.returncode, 0, create.stderr)
                    env = dict(os.environ, G1_BUILD_BINDING="pycairo",
                               G1_BUILD_OPERATION="wheel",
                               G1_TOOL_TRACE=str(root / f"{tool}.trace"),
                               G1_PROXY_PYTHON=sys.executable,
                               G1_LINKER_PROXY_DIRECTORY=str(root),
                               G1_LINKER_SELECTOR="bfd", READY=str(ready),
                               STOPPED=str(stopped))
                    env[variable] = str(target)
                    process = subprocess.Popen([str(proxy), "--version"], env=env,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), f"{tool} never started its child")
                    child_pid = int(ready.read_text())
                    os.kill(process.pid, signal.SIGTERM)
                    stdout, stderr = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, -signal.SIGTERM, stderr)
                    self.assertEqual(stopped.read_text(), "stopped")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child_pid, 0)
                    self.assertIn("|143|failed|", (root / f"{tool}.trace").read_text())

    def test_matching_write_followed_by_inotify_overflow_is_not_fresh(self):
        self._assert_output_watch_result(0x00004000, -1, False)

    def test_matching_write_followed_by_ignored_watch_is_not_fresh(self):
        self._assert_output_watch_result(0x00008000, 1, False)

    def test_output_watch_rejects_malformed_and_premature_loss(self):
        provenance = self._load_module("malformed_watch", self.provenance_path)
        name = b"module.o\0\0\0\0"
        matching = struct.pack("iIII", 1, 0x8, 0, len(name)) + name
        self._assert_output_watch_result(0, 1, True)
        for batch in (
            matching + b"short",
            matching + struct.pack("iIII", 1, 0x8, 0, 4) + b"x",
            matching + struct.pack("iIII", 1, 0x8, 0, 4) + b"abcd",
            matching + struct.pack("iIII", -1, 0x8, 0, len(name)) + name,
            matching + struct.pack("iIII", 1, 0x400, 0, 0),
        ):
            with self.subTest(batch=batch[-16:]):
                with mock.patch.object(provenance.os, "read", side_effect=[batch, BlockingIOError()]):
                    with mock.patch.object(provenance.os, "close") as close:
                        self.assertFalse(provenance._proxy_output_produced(
                            123, Path("/tmp/module.o")
                        ))
                        close.assert_called_once_with(123)
        with mock.patch.object(provenance.os, "read", return_value=b""):
            with mock.patch.object(provenance.os, "close"):
                self.assertFalse(provenance._proxy_output_produced(
                    123, Path("/tmp/module.o")
                ))

    def test_trace_io_failure_preserves_all_proxy_child_dispositions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            target.write_text(
                "#!/bin/sh\n"
                "case $REVIEW_CHILD_MODE in\n"
                "  zero) exit 0 ;;\n"
                "  ordinary) exit 143 ;;\n"
                "  signal) kill -TERM $$ ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            target.chmod(0o700)
            for tool, writer, variable in (
                ("meson", 'write_tool_proxy "$2" meson G1_TARGET', "G1_TARGET"),
                ("cc", 'write_compiler_proxy "$2"', "G1_REAL_CC"),
                ("ld.bfd", 'write_linker_proxy "$2"', "G1_REAL_CC_LD"),
            ):
                proxy = root / tool
                create = subprocess.run(
                    ["bash", "-c", f'source "$1"; {writer}',
                     "gate-test", str(self.runner), str(proxy)],
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(create.returncode, 0, create.stderr)
                for mode, expected in (("zero", 74), ("ordinary", 143), ("signal", -15)):
                    with self.subTest(tool=tool, child=mode):
                        trace = root / f"{tool}-{mode}.trace"
                        trace.mkdir()
                        Path(str(trace) + ".pending").mkdir()
                        environment = dict(
                            os.environ, G1_BUILD_BINDING="PyGObject",
                            G1_BUILD_OPERATION="wheel", G1_TOOL_TRACE=str(trace),
                            G1_PROXY_PYTHON=sys.executable,
                            G1_LINKER_PROXY_DIRECTORY=str(root),
                            G1_LINKER_SELECTOR="bfd", REVIEW_CHILD_MODE=mode,
                        )
                        environment[variable] = str(target)
                        result = subprocess.run(
                            [str(proxy), "--version"], env=environment,
                            capture_output=True, timeout=5,
                        )
                        self.assertEqual(result.returncode, expected, result.stderr)
                        self.assertTrue(Path(str(trace) + ".failed").is_file())

    def test_failure_marker_blocks_complete_trace_and_g1_publication(self):
        provenance = self._load_module("failed_recording", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._valid_provenance_fixture(root / "validator", provenance)
            trace = Path(arguments.tool_trace)
            Path(str(trace) + ".failed").touch()
            with self.assertRaisesRegex(ValueError, "producer failure"):
                self._create_provenance(provenance, arguments)
            self.assertFalse(Path(arguments.output).exists())
            case = root / "orchestration"
            work = case / "work"
            result = self._run_stubbed_g1(case, work, "recording-failure")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("G1 passed", result.stdout)
            self.assertFalse((work / "reports" / "provenance.json").exists())
            self.assertTrue(
                (work / "tmp" / "build-tool-trace.txt.failed").is_file()
            )

    def test_pending_state_establishment_precedes_child_and_success_clears_it(self):
        provenance = self._load_module("pending_launch", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "harmless-tool"
            target.write_text(
                "#!/bin/sh\n: >\"$REVIEW_CHILD_STARTED\"\nexit 0\n",
                encoding="utf-8",
            )
            target.chmod(0o700)
            real_open = os.open
            for deny_entry in (True, False):
                with self.subTest(deny_entry=deny_entry):
                    trace = root / f"trace-{deny_entry}"
                    pending = Path(str(trace) + ".pending")
                    pending.mkdir()
                    started = root / f"started-{deny_entry}"
                    environment = dict(
                        G1_BUILD_BINDING="PyGObject", G1_BUILD_OPERATION="wheel",
                        G1_TOOL_TRACE=str(trace), G1_REAL_MESON=str(target),
                        REVIEW_CHILD_STARTED=str(started),
                    )

                    def open_record(path, flags, *args, **kwargs):
                        if deny_entry and str(path).startswith(str(pending) + os.sep):
                            raise PermissionError("Pending entry cannot be created.")
                        return real_open(path, flags, *args, **kwargs)

                    with mock.patch.dict(os.environ, environment):
                        with mock.patch.object(provenance.os, "open", side_effect=open_record):
                            status = provenance._run_proxy(
                                "meson", "G1_REAL_MESON", str(root / "proxy"), []
                            )
                    self.assertEqual(status, 74 if deny_entry else 0)
                    self.assertEqual(started.exists(), not deny_entry)
                    self.assertEqual(list(pending.iterdir()), [])
                    if deny_entry:
                        self.assertTrue(Path(str(trace) + ".failed").exists())
                    else:
                        self.assertIn("|meson|run|0|complete|", trace.read_text())

    def test_dual_trace_marker_failure_blocks_real_report_for_all_proxies(self):
        provenance = self._load_module("pending_dual_failure", self.provenance_path)
        real_open = os.open
        with tempfile.TemporaryDirectory() as temporary_directory:
            for tool, variable in (
                ("meson", "G1_REAL_MESON"),
                ("cc", "G1_REAL_CC"),
                ("ld", "G1_REAL_CC_LD"),
            ):
                with self.subTest(tool=tool):
                    root = Path(temporary_directory) / tool
                    arguments = self._valid_provenance_fixture(root, provenance)
                    trace = Path(arguments.tool_trace)
                    original = trace.read_bytes()
                    trace.write_bytes(b"".join(original.splitlines(keepends=True)[:-2]))
                    marker = str(trace) + ".failed"

                    def deny_recording(path, flags, *args, **kwargs):
                        if str(path) in {str(trace), marker} and flags & os.O_WRONLY:
                            raise PermissionError("Trace and marker are unavailable.")
                        return real_open(path, flags, *args, **kwargs)

                    environment = dict(
                        G1_BUILD_BINDING="PyGObject", G1_BUILD_OPERATION="wheel",
                        G1_TOOL_TRACE=str(trace), G1_LINKER_SELECTOR="bfd",
                        G1_LINKER_PROXY_DIRECTORY=str(root / "proxies"),
                    )
                    environment[variable] = "/bin/true"
                    with mock.patch.dict(os.environ, environment):
                        with mock.patch.object(provenance.os, "open", side_effect=deny_recording):
                            status = provenance._run_proxy(
                                tool, variable, str(root / "unused-proxy"),
                                ["-dumpversion"],
                            )
                    self.assertEqual(status, 74)
                    self.assertFalse(Path(marker).exists())
                    self.assertEqual(len(list(Path(str(trace) + ".pending").iterdir())), 1)
                    trace.write_bytes(original)
                    with mock.patch("sys.stderr"):
                        result = provenance.main(
                            self._provenance_argv(arguments),
                            distribution_version=provenance.EXPECTED_DISTRIBUTIONS.__getitem__,
                        )
                    self.assertEqual(result, 1)
                    self.assertFalse(Path(arguments.output).exists())

    def test_failed_pending_completion_survives_later_success(self):
        provenance = self._load_module("pending_completion", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._valid_provenance_fixture(root, provenance)
            trace = Path(arguments.tool_trace)
            original = trace.read_bytes()
            trace.write_bytes(b"".join(original.splitlines(keepends=True)[:-2]))
            marker = str(trace) + ".failed"
            real_open = os.open

            def deny_marker(path, flags, *args, **kwargs):
                if str(path) == marker and flags & os.O_WRONLY:
                    raise PermissionError("Failure marker is unavailable.")
                return real_open(path, flags, *args, **kwargs)

            environment = dict(
                G1_BUILD_BINDING="PyGObject", G1_BUILD_OPERATION="wheel",
                G1_TOOL_TRACE=str(trace), G1_REAL_MESON="/bin/true",
            )
            with mock.patch.dict(os.environ, environment):
                first = provenance._run_proxy(
                    "meson", "G1_REAL_MESON", str(root / "proxy"), []
                )
                with mock.patch.object(Path, "unlink", side_effect=PermissionError):
                    with mock.patch.object(provenance.os, "open", side_effect=deny_marker):
                        failed = provenance._run_proxy(
                            "meson", "G1_REAL_MESON", str(root / "proxy"), []
                        )
                last = provenance._run_proxy(
                    "meson", "G1_REAL_MESON", str(root / "proxy"), []
                )
            self.assertEqual((first, failed, last), (0, 74, 0))
            self.assertFalse(Path(marker).exists())
            self.assertEqual(len(list(Path(str(trace) + ".pending").iterdir())), 1)
            trace.write_bytes(original)
            with mock.patch("sys.stderr"):
                result = provenance.main(
                    self._provenance_argv(arguments),
                    distribution_version=provenance.EXPECTED_DISTRIBUTIONS.__getitem__,
                )
            self.assertEqual(result, 1)
            self.assertFalse(Path(arguments.output).exists())

    def test_parallel_proxy_completions_remove_only_their_own_entries(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "waiting-tool"
            target.write_text(
                "#!/bin/sh\n"
                ": >\"$REVIEW_READY\"\n"
                "while test ! -e \"$REVIEW_GO\"; do sleep 0.02; done\n"
                "exit 0\n",
                encoding="utf-8",
            )
            target.chmod(0o700)
            proxy = root / "meson"
            created = subprocess.run(
                ["bash", "-c", 'source "$1"; write_tool_proxy "$2" meson G1_REAL_MESON',
                 "gate-test", str(self.runner), str(proxy)],
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            for order in ((0, 1), (1, 0)):
                with self.subTest(order=order):
                    trace = root / f"trace-{order[0]}"
                    pending = Path(str(trace) + ".pending")
                    pending.mkdir()
                    processes = []
                    gates = []
                    try:
                        for index in range(2):
                            ready = root / f"{order[0]}-{index}.ready"
                            go = root / f"{order[0]}-{index}.go"
                            gates.append(go)
                            environment = dict(
                                os.environ, G1_BUILD_BINDING="PyGObject",
                                G1_BUILD_OPERATION="wheel", G1_TOOL_TRACE=str(trace),
                                G1_REAL_MESON=str(target),
                                G1_PROXY_PYTHON=sys.executable,
                                REVIEW_READY=str(ready), REVIEW_GO=str(go),
                            )
                            processes.append(subprocess.Popen(
                                [str(proxy)], env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            ))
                            deadline = time.monotonic() + 5
                            while not ready.exists() and time.monotonic() < deadline:
                                time.sleep(0.02)
                            self.assertTrue(ready.exists())
                        self.assertEqual(len(list(pending.iterdir())), 2)
                        gates[order[0]].touch()
                        _stdout, stderr = processes[order[0]].communicate(timeout=5)
                        self.assertEqual(processes[order[0]].returncode, 0, stderr)
                        self.assertEqual(len(list(pending.iterdir())), 1)
                        gates[order[1]].touch()
                        _stdout, stderr = processes[order[1]].communicate(timeout=5)
                        self.assertEqual(processes[order[1]].returncode, 0, stderr)
                        self.assertEqual(list(pending.iterdir()), [])
                    finally:
                        for process in processes:
                            if process.poll() is None:
                                process.terminate()
                            process.communicate(timeout=5)

    def test_work_root_trace_path_bound_precedes_builder_work(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            for root_bytes in (128, 129):
                with self.subTest(root_bytes=root_bytes):
                    candidate = base / ("x" * (root_bytes - len(str(base)) - 1))
                    self.assertEqual(len(os.fsencode(candidate)), root_bytes)
                    result = subprocess.run(
                        ["bash", "-c", 'source "$1"; validate_work_root "$2"',
                         "gate-test", str(self.runner), str(candidate)],
                        capture_output=True, text=True, timeout=5,
                    )
                    if root_bytes == 128:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), str(candidate))
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(b"128-byte trace path limit", result.stderr.encode())
                    self.assertFalse(candidate.exists())

    def test_work_root_rejects_encoded_expansion_before_builder_work(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            unsafe = base / "unsafe-\x01"
            unsafe.mkdir()
            alias = base / "safe-alias"
            alias.symlink_to(unsafe, target_is_directory=True)
            trailing_alias = base / "trailing-alias"
            trailing_alias.symlink_to(base / "new-root\n")
            for candidate in (
                "/tmp/" + "\x01" * 123,
                "/tmp/" + "é" * 61,
                "/tmp/lmt-trailing-newline\n",
                str(alias / "new-work-root"),
                str(trailing_alias),
            ):
                with self.subTest(candidate=repr(candidate)):
                    marker = base / "builder-called"
                    command = (
                        'source "$1"; REVIEW_MARKER=$2; '
                        'verify_builder_platform() { : >"$REVIEW_MARKER"; }; '
                        'run_g1 /never-used "$3"'
                    )
                    result = subprocess.run(
                        ["bash", "-c", command, "gate-test", str(self.runner),
                         str(marker), candidate],
                        capture_output=True, text=True, timeout=5,
                    )
                    self.assertEqual(result.returncode, 64, result.stderr)
                    self.assertIn("printable ASCII", result.stderr)
                    self.assertFalse(marker.exists())

            for character in ('"', "\\"):
                candidate = "/tmp/" + character * 123
                result = subprocess.run(
                    ["bash", "-c", 'source "$1"; validate_work_root "$2"',
                     "gate-test", str(self.runner), candidate],
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def _assert_output_watch_result(self, trailing_mask, trailing_watch, expected):
        provenance = self._load_module("watched_output", self.provenance_path)
        name = b"module.o\0\0\0\0"
        matching = struct.pack("iIII", 1, 0x8, 0, len(name)) + name
        trailing = (
            struct.pack("iIII", trailing_watch, trailing_mask, 0, 0)
            if trailing_mask else b""
        )
        with mock.patch.object(
            provenance.os, "read", side_effect=[matching + trailing, BlockingIOError()]
        ):
            with mock.patch.object(provenance.os, "close") as close:
                self.assertIs(
                    provenance._proxy_output_produced(123, Path("/tmp/module.o")),
                    expected,
                )
                close.assert_called_once_with(123)

    def test_direct_linker_proxy_call_is_unattributed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "real-ld.bfd"
            proxy = root / "ld.bfd"
            output = root / "module.so"
            trace = root / "trace"
            Path(str(trace) + ".pending").mkdir()
            (root / "unused.o").write_bytes(b"object")
            (root / "module-fixture.so").write_bytes(self._fake_elf())
            target.write_text(
                "#!/bin/sh\n"
                "previous=\n"
                "for argument in \"$@\"; do\n"
                f"  if test \"$previous\" = -o; then "
                f"cp '{root / 'module-fixture.so'}' \"$argument\"; fi\n"
                "  previous=$argument\n"
                "done\n",
                encoding="utf-8",
            )
            target.chmod(0o700)
            create = subprocess.run(
                [
                    "bash", "-c",
                    'source "$1"; write_linker_proxy "$2"',
                    "gate-test", str(self.runner), str(proxy),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(create.returncode, 0, create.stderr)
            environment = dict(os.environ)
            environment.update(
                G1_BUILD_BINDING="pycairo",
                G1_BUILD_OPERATION="wheel",
                G1_REAL_CC_LD=str(target),
                G1_TOOL_TRACE=str(trace),
                G1_PROXY_PYTHON=sys.executable,
            )
            result = subprocess.run(
                [str(proxy), str(root / "unused.o"), "-shared", "-o", str(output)],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertEqual(
                trace.read_text(encoding="utf-8"),
                "result|pycairo|ld|link|0|unattributed|-|-\n",
            )

    def test_provisioning_separates_build_and_native_lab_packages(self):
        self.assertIn("readonly BUILD_PACKAGES=(", self.provisioner_source)
        self.assertIn(
            "readonly NATIVE_LAB_PACKAGES=(",
            self.provisioner_source,
        )
        self.assertIn("--disposable-builder", self.provisioner_source)
        self.assertIn("--build)", self.provisioner_source)
        self.assertIn("--native-lab)", self.provisioner_source)
        self.assertIn("--no-install-recommends", self.provisioner_source)

    def test_binding_verifier_requires_versions_before_imports(self):
        verifier = self._load_module(
            "linux_tray_binding_verifier",
            self.verifier_path,
        )
        events = []

        class FakeGi:
            @staticmethod
            def require_version(namespace, version):
                events.append(("require", namespace, version))

        raw_modules = {
            "Gtk": types.SimpleNamespace(
                get_major_version=lambda: 3,
                get_minor_version=lambda: 24,
                get_micro_version=lambda: 0,
            ),
            "GdkPixbuf": types.SimpleNamespace(
                PIXBUF_MAJOR=2,
                PIXBUF_MINOR=42,
                PIXBUF_MICRO=10,
            ),
            "Gio": types.SimpleNamespace(
                MAJOR_VERSION=2,
                MINOR_VERSION=72,
                MICRO_VERSION=0,
            ),
            "GLib": types.SimpleNamespace(
                MAJOR_VERSION=2,
                MINOR_VERSION=72,
                MICRO_VERSION=0,
            ),
        }

        class FakeGiModule:
            @staticmethod
            def get_introspection_module(namespace):
                events.append(("raw-introspection", namespace))
                return raw_modules[namespace]

        def fake_import(name):
            events.append(("import", name))
            if name == "gi":
                return FakeGi()
            if name == "gi.module":
                return FakeGiModule()
            if name == "cairo":
                return types.SimpleNamespace(
                    cairo_version_string=lambda: "1.2.3"
                )
            if name.startswith("gi.repository") or name.startswith(
                "application"
            ):
                raise AssertionError("An initializing import was attempted.")
            raise AssertionError(f"Unexpected import: {name}")

        report = verifier.collect_binding_versions(
            import_module=fake_import,
            distribution_version=lambda name: {
                "PyGObject": "3.48.2",
                "pycairo": "1.26.1",
            }[name],
            python_version=lambda: "3.12.0",
            python_implementation=lambda: "CPython",
        )
        first_raw_lookup = next(
            index
            for index, event in enumerate(events)
            if event[0] == "raw-introspection"
        )
        self.assertEqual(
            events[1:first_raw_lookup],
            [
                ("require", "Gtk", "3.0"),
                ("require", "GdkPixbuf", "2.0"),
                ("require", "Gio", "2.0"),
                ("require", "GLib", "2.0"),
                ("import", "cairo"),
                ("import", "gi.module"),
            ],
        )
        self.assertEqual(report["bindings"]["PyGObject"], "3.48.2")
        self.assertEqual(
            [event[1] for event in events if event[0] == "raw-introspection"],
            ["Gtk", "GdkPixbuf", "Gio", "GLib"],
        )
        self.assertFalse(
            any(
                event[0] == "import"
                and (
                    event[1].startswith("gi.repository")
                    or event[1].startswith("application")
                )
                for event in events
            )
        )
        self.assertFalse(
            any("init" in str(event).lower() for event in events)
        )

    def test_provenance_accepts_complete_schema_faithful_evidence(self):
        provenance = self._load_module("linux_tray_provenance", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            arguments = self._valid_provenance_fixture(
                Path(temporary_directory), provenance
            )
            report = provenance.create_report(
                arguments,
                distribution_version=provenance.EXPECTED_DISTRIBUTIONS.__getitem__,
            )
            self.assertNotEqual(
                report["sources"]["pycairo"]["sha256"],
                report["wheels"]["pycairo"]["sha256"],
            )
            self.assertEqual(
                set(report["tool_trace_sections"]),
                {"driver-check", "pycairo", "PyGObject"},
            )
            self.assertEqual(
                report["tool_selection"]["linker_selector"], "bfd"
            )
            self.assertEqual(
                report["native_package_archives"]["required_before"],
                "G2-freeze",
            )

    def test_setuptools_build_evidence_has_no_meson_contract(self):
        provenance = self._load_module("setuptools_evidence", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            arguments = self._valid_provenance_fixture(
                Path(temporary_directory), provenance
            )
            report = self._create_provenance(provenance, arguments)
            self.assertEqual(
                report["sources"]["pycairo"]["build_backend"],
                "setuptools.build_meta",
            )
            events = report["tool_trace_sections"]["pycairo"]
            self.assertTrue(any("|cc|compile|0|complete|" in event for event in events))
            self.assertTrue(any("|cc|link|0|complete|" in event for event in events))
            self.assertFalse(any("|meson|" in event or "|ninja|" in event for event in events))

    def test_meson_build_evidence_uses_persistent_introspection(self):
        provenance = self._load_module("meson_evidence", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            arguments = self._valid_provenance_fixture(
                Path(temporary_directory), provenance
            )
            report = self._create_provenance(provenance, arguments)
            self.assertEqual(
                report["sources"]["PyGObject"]["build_backend"], "mesonpy"
            )
            self.assertEqual(set(report["compiler_evidence"]), {"PyGObject"})
            events = report["tool_trace_sections"]["PyGObject"]
            self.assertTrue(any("|meson|run|0|complete|" in event for event in events))
            self.assertTrue(any("|ninja|run|0|complete|" in event for event in events))

    def test_complete_pygobject_38_object_trace_at_documented_roots(self):
        provenance = self._load_module("full_gi_target", self.provenance_path)
        self.assertEqual(len(self.PYGOBJECT_GI_SOURCES), 38)
        for work_root in (
            "/var/tmp/lmt-g1-UNIQUE",
            "/var/tmp/lmt-tray-lab-UNIQUE",
            "/var/tmp/" + "x" * (128 - len("/var/tmp/")),
            "/var/tmp/" + '"' * (128 - len("/var/tmp/")),
            "/var/tmp/" + "\\" * (128 - len("/var/tmp/")),
        ):
            with self.subTest(work_root=work_root):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    arguments = self._valid_provenance_fixture(
                        Path(temporary_directory), provenance
                    )
                    source = Path(next(
                        item.split("=", 1)[1] for item in arguments.source
                        if item.startswith("PyGObject=")
                    ))
                    metadata = b"Metadata-Version: 2.1\nName: PyGObject\nVersion: 3.48.2\n\n"
                    project = b'[build-system]\nbuild-backend="mesonpy"\n'
                    source_bytes = {}
                    with tarfile.open(source, "w:gz") as archive:
                        for filename, content in (
                            ("PKG-INFO", metadata), ("pyproject.toml", project),
                            *((f"gi/{name}.c", f"int {name.replace('-', '_')}(void) {{ return {index}; }}\n".encode())
                              for index, name in enumerate(self.PYGOBJECT_GI_SOURCES)),
                        ):
                            info = tarfile.TarInfo(f"PyGObject-3.48.2/{filename}")
                            info.size = len(content)
                            archive.addfile(info, io.BytesIO(content))
                            if filename.endswith(".c"):
                                source_bytes[filename] = content
                    extension = (
                        work_root
                        + "/build/pygobject/gi/_gi.cpython-312-x86_64-linux-gnu.so"
                    )
                    linked_inputs = []
                    native_lines = []
                    for index, name in enumerate(self.PYGOBJECT_GI_SOURCES):
                        source_name = f"gi/{name}.c"
                        object_name = f"{extension}.p/{name}.c.o"
                        object_hash = hashlib.sha256(f"fixture-object-{index}".encode()).hexdigest()
                        linked_inputs.append([object_name, object_hash])
                        detail = provenance._encode_operation_detail(
                            [[work_root + "/sources/PyGObject-3.48.2/" + source_name,
                              hashlib.sha256(source_bytes[source_name]).hexdigest()]],
                            [object_name, object_hash], None, True,
                        )
                        native_lines.append(
                            f"result|PyGObject|cc|compile|0|complete|-|{detail}"
                        )
                    link_detail = provenance._encode_operation_detail(
                        linked_inputs,
                        [extension, hashlib.sha256(self._fake_elf()).hexdigest()],
                        hashlib.sha256(b"\x90\xc3").hexdigest(), True,
                    )
                    self.assertGreater(len(link_detail), 8192)
                    self.assertLess(len(link_detail), provenance.MAX_TRACE_DETAIL_BYTES)
                    for tool in ("ld", "cc"):
                        native_lines.append(
                            f"result|PyGObject|{tool}|link|0|complete|702|{link_detail}"
                        )
                    trace = Path(arguments.tool_trace)
                    lines = trace.read_text(encoding="utf-8").splitlines()
                    start = lines.index("phase|PyGObject|start")
                    wheel = next(i for i in range(start, len(lines))
                                 if lines[i].startswith("artifact|PyGObject|wheel|"))
                    lines = ([line for line in lines[:wheel]
                              if not line.startswith("result|PyGObject|cc|compile|")
                              and not line.startswith("result|PyGObject|cc|link|")
                              and not line.startswith("result|PyGObject|ld|link|")]
                             + native_lines + lines[wheel:])
                    trace.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    report = self._create_provenance(provenance, arguments)
                    self.assertTrue(report["wheels"]["PyGObject"])
                    self.assertEqual(
                        sum("|PyGObject|cc|compile|0|complete|" in line
                            for line in report["tool_trace_sections"]["PyGObject"]),
                        38,
                    )

    def test_native_detail_bounds_agree_for_producer_and_parser(self):
        provenance = self._load_module("trace_bounds", self.provenance_path)
        digest = "a" * 64
        output = ["/tmp/module.so", digest]

        def encoded_for(length):
            detail = {"inputs": [["/tmp/" + "x" * length, digest]],
                      "output": output, "text": digest, "produced": True}
            return base64.urlsafe_b64encode(
                json.dumps(detail, separators=(",", ":")).encode()
            ).decode()

        low, high = 0, provenance.MAX_TRACE_DETAIL_BYTES
        while low < high:
            middle = (low + high + 1) // 2
            if len(encoded_for(middle)) <= provenance.MAX_TRACE_DETAIL_BYTES:
                low = middle
            else:
                high = middle - 1
        boundary = encoded_for(low)
        self.assertEqual(len(boundary), provenance.MAX_TRACE_DETAIL_BYTES)
        line = f"result|PyGObject|cc|link|0|complete|702|{boundary}"
        self.assertTrue(provenance._trace_event(line, "PyGObject")[3])
        self.assertEqual(
            provenance._encode_operation_detail(
                [["/tmp/" + "x" * low, digest]], output, digest, True,
            ),
            boundary,
        )
        with self.assertRaisesRegex(ValueError, "trace detail limit"):
            provenance._encode_operation_detail(
                [["/tmp/" + "x" * (low + 3), digest]], output, digest, True,
            )
        with self.assertRaisesRegex(ValueError, "invalid event"):
            provenance._trace_event(
                f"result|PyGObject|cc|link|0|complete|702|{encoded_for(low + 3)}",
                "PyGObject",
            )

    def test_linker_proxy_records_all_38_pygobject_inputs(self):
        provenance = self._load_module("real_38_input_producer", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            objects = (
                root / "build" / "pygobject" / "gi"
                / "_gi.cpython-312-x86_64-linux-gnu.so.p"
            )
            objects.mkdir(parents=True)
            object_paths = []
            for index, name in enumerate(self.PYGOBJECT_GI_SOURCES):
                path = objects / f"{name}.c.o"
                path.write_bytes(f"object-{index}".encode())
                object_paths.append(str(path))
            fixture = root / "fixture.so"
            fixture.write_bytes(self._fake_elf())
            output = objects.parent / "_gi.cpython-312-x86_64-linux-gnu.so"
            target = root / "fake-linker"
            target.write_text(
                "#!/bin/sh\n"
                "previous=\n"
                "for argument in \"$@\"; do\n"
                "  if test \"$previous\" = -o; then "
                "cp -- \"$REVIEW_ELF\" \"$argument\"; fi\n"
                "  previous=$argument\n"
                "done\n",
                encoding="utf-8",
            )
            target.chmod(0o700)
            trace = root / "trace"
            Path(str(trace) + ".pending").mkdir()
            environment = dict(
                os.environ, G1_BUILD_BINDING="PyGObject",
                G1_BUILD_OPERATION="wheel", G1_TOOL_TRACE=str(trace),
                G1_REAL_CC_LD=str(target), G1_DRIVER_OPERATION_ID="702",
                REVIEW_ELF=str(fixture),
            )
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(self.provenance_path),
                 "--proxy", "ld", "G1_REAL_CC_LD", str(root / "unused-proxy"),
                 *object_paths, "-o", str(output)],
                env=environment, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(Path(str(trace) + ".failed").exists())
            line = trace.read_text(encoding="utf-8").strip()
            self.assertGreater(len(line.split("|")[7]), 8192)
            parsed = provenance._trace_event(line, "PyGObject")
            self.assertEqual(len(parsed[4]["inputs"]), 38)
            self.assertTrue(parsed[3])

    def test_wheel_copy_with_elf_metadata_edit_retains_code_identity(self):
        provenance = self._load_module("transformed_elf_wheel", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            arguments = self._valid_provenance_fixture(Path(temporary_directory), provenance)
            wheel = Path(arguments.wheel[0].split("=", 1)[1])
            with zipfile.ZipFile(wheel) as archive:
                members = [(item.filename, archive.read(item)) for item in archive.infolist()]
            with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in members:
                    if name.endswith("module.so"):
                        content = content[:7] + b"\x03" + content[8:]
                    archive.writestr(name, content)
            report = self._create_provenance(provenance, arguments)
            self.assertTrue(report["wheels"])

    def test_provenance_rejects_incomplete_or_wrong_backend_execution(self):
        provenance = self._load_module("invalid_execution", self.provenance_path)
        cases = {
            "failed": (
                "result|pycairo|cc|compile|0|complete|-",
                "result|pycairo|cc|compile|23|failed|-|-",
                "completed build operations",
            ),
            "driver-bypass": (
                "result|PyGObject|ld|link|0|complete|702",
                "result|PyGObject|ld|link|0|complete|703",
                "linker evidence",
            ),
            "wrong-backend": (
                "result|pycairo|pkg-config|run|0|complete|-|-",
                "result|pycairo|meson|run|0|complete|-|-",
                "wrong backend",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            for name, (old, new, message) in cases.items():
                with self.subTest(name=name):
                    arguments = self._valid_provenance_fixture(base / name, provenance)
                    trace = Path(arguments.tool_trace)
                    content = trace.read_text(encoding="utf-8")
                    self.assertIn(old, content)
                    if name == "failed":
                        content = "\n".join(
                            new if line.startswith(old) else line
                            for line in content.splitlines()
                        ) + "\n"
                    else:
                        content = content.replace(old, new, 1)
                    trace.write_text(content, encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        self._create_provenance(provenance, arguments)

            arguments = self._valid_provenance_fixture(base / "version-only", provenance)
            trace = Path(arguments.tool_trace)
            lines = trace.read_text(encoding="utf-8").splitlines()
            lines = [
                line for line in lines
                if not (
                    line.startswith("result|PyGObject|cc|compile|")
                    or line.startswith("result|PyGObject|cc|link|")
                    or line.startswith("result|PyGObject|ld|link|")
                )
            ]
            output_index = next(
                index for index, line in enumerate(lines)
                if line.startswith("artifact|PyGObject|wheel|")
            )
            lines[output_index:output_index] = [
                "result|PyGObject|cc|query|0|complete|-|-",
                "result|PyGObject|cc|query|0|complete|-|-",
            ]
            trace.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "completed build operations"):
                self._create_provenance(provenance, arguments)

            arguments = self._valid_provenance_fixture(base / "trace-bounds", provenance)
            with mock.patch.object(provenance, "MAX_TRACE_BYTES", 1):
                with self.assertRaisesRegex(ValueError, "bounded regular file"):
                    self._create_provenance(provenance, arguments)
            with mock.patch.object(provenance, "MAX_TRACE_RECORDS", 1):
                with self.assertRaisesRegex(ValueError, "record count"):
                    self._create_provenance(provenance, arguments)

    def test_archive_headers_and_source_budgets_are_enforced(self):
        provenance = self._load_module("bounded_archives", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for label, versions in {
                "repeated": ("1.0", "1.0"),
                "conflicting": ("1.0", "2.0"),
            }.items():
                with self.subTest(wheel_headers=label):
                    arguments = self._valid_provenance_fixture(
                        root / label, provenance
                    )
                    wheel = Path(arguments.wheel[0].split("=", 1)[1])
                    name, version = self._wheel_name_version(wheel)
                    self._write_wheel(
                        wheel,
                        name,
                        version,
                        str(next(sys_tags())),
                        wheel_versions=versions,
                    )
                    with self.assertRaisesRegex(ValueError, "Wheel format"):
                        self._create_provenance(provenance, arguments)

            source = root / "pycairo-1.26.1.tar.gz"
            self._write_sdist(source, "pycairo", "1.26.1")
            with mock.patch.object(provenance, "MAX_ARCHIVE_BYTES", 1):
                with mock.patch.object(provenance.gzip, "GzipFile") as gzip_open:
                    with self.assertRaisesRegex(ValueError, "bounded regular file"):
                        provenance._source_metadata(source, "pycairo", "1.26.1")
                    gzip_open.assert_not_called()
            with mock.patch.object(provenance, "MAX_ARCHIVE_MEMBERS", 1):
                with self.assertRaisesRegex(ValueError, "too many members"):
                    provenance._source_metadata(source, "pycairo", "1.26.1")
            with mock.patch.object(provenance, "MAX_SOURCE_STREAM_BYTES", 256):
                with self.assertRaisesRegex(ValueError, "traversal exceeded"):
                    provenance._source_metadata(source, "pycairo", "1.26.1")
            with mock.patch.object(provenance, "MAX_METADATA_BYTES", 8):
                with self.assertRaisesRegex(ValueError, "metadata is oversized"):
                    provenance._source_metadata(source, "pycairo", "1.26.1")
            self.assertNotIn("getmembers", self.provenance_path.read_text(encoding="utf-8"))

    def test_extended_tar_headers_consume_limits_before_decode(self):
        provenance = self._load_module("extended_tar_budget", self.provenance_path)
        metadata = b"Metadata-Version: 2.1\nName: pycairo\nVersion: 1.26.1\n\n"
        project = b'[build-system]\nbuild-backend="setuptools.build_meta"\n'
        with tempfile.TemporaryDirectory() as temporary_directory:
            for kind in ("pax-local", "pax-global", "gnu-name", "gnu-link"):
                with self.subTest(kind=kind):
                    path = Path(temporary_directory) / "pycairo-1.26.1.tar.gz"
                    archive_options = {"format": tarfile.GNU_FORMAT}
                    if kind.startswith("pax"):
                        archive_options["format"] = tarfile.PAX_FORMAT
                    if kind == "pax-global":
                        archive_options["pax_headers"] = {"comment": "x" * 1024}
                    with tarfile.open(path, "w:gz", **archive_options) as archive:
                        if kind in {"gnu-name", "gnu-link"}:
                            info = tarfile.TarInfo(
                                "pycairo-1.26.1/" + ("x" * 400 if kind == "gnu-name" else "alias")
                            )
                            if kind == "gnu-link":
                                info.type = tarfile.SYMTYPE
                                info.linkname = "x" * 400
                            archive.addfile(info)
                        for name, body in (("PKG-INFO", metadata), ("pyproject.toml", project)):
                            info = tarfile.TarInfo(f"pycairo-1.26.1/{name}")
                            info.size = len(body)
                            if kind == "pax-local" and name == "PKG-INFO":
                                info.pax_headers = {"comment": "x" * 1024}
                            archive.addfile(info, io.BytesIO(body))
                    self.assertLess(path.stat().st_size, 4096)
                    with mock.patch.object(provenance, "MAX_METADATA_BYTES", 256):
                        with self.assertRaisesRegex(ValueError, "extended metadata"):
                            provenance._source_metadata(path, "pycairo", "1.26.1")
                    with mock.patch.object(provenance, "MAX_ARCHIVE_MEMBERS", 2):
                        with self.assertRaisesRegex(ValueError, "too many members"):
                            provenance._source_metadata(path, "pycairo", "1.26.1")

    def test_provenance_rejects_disguised_archives_and_wrong_requirements(self):
        provenance = self._load_module("provenance_archives", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._valid_provenance_fixture(root, provenance)
            source = Path(arguments.source[0].split("=", 1)[1])
            source.write_text("not an archive\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Source artifact"):
                self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "wheel", provenance)
            wheel = Path(arguments.wheel[0].split("=", 1)[1])
            wheel.write_text("not an archive\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Wheel"):
                self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "second", provenance)
            requirement = next(
                Path(path) for path in arguments.requirements
                if Path(path).name == "requirements-linux-tray.txt"
            )
            requirement.write_text("example==1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Requirement contents"):
                self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "metadata", provenance)
            wheel_entry = arguments.wheel[0]
            wheel = Path(wheel_entry.split("=", 1)[1])
            _name, version = self._wheel_name_version(wheel)
            self._write_wheel(wheel, "substituted", version, str(next(sys_tags())))
            with self.assertRaisesRegex(ValueError, "archive metadata"):
                self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "versions", provenance)
            verification = Path(arguments.verification)
            content = json.loads(verification.read_text(encoding="utf-8"))
            content["python"]["version"] = "3.12.not-a-version"
            content["native"]["gtk"] = "not-a-version"
            verification.write_text(json.dumps(content), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "interpreter"):
                self._create_provenance(provenance, arguments)

    def test_provenance_rejects_duplicates_and_incompatible_wheels(self):
        provenance = self._load_module("provenance_inventory", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for attribute in ("requirements", "distribution"):
                arguments = self._valid_provenance_fixture(
                    root / attribute, provenance
                )
                values = getattr(arguments, attribute)
                setattr(arguments, attribute, [*values, values[0]])
                with self.assertRaisesRegex(ValueError, "duplicated|inconsistent"):
                    self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "wheel", provenance)
            old = Path(arguments.toolchain_artifact[0])
            incompatible = old.with_name(
                old.name.rsplit("-", 3)[0] + "-cp39-cp39-win_amd64.whl"
            )
            self._write_wheel(
                incompatible,
                *self._wheel_name_version(old),
                tag="cp39-cp39-win_amd64",
            )
            arguments.toolchain_artifact[0] = str(incompatible)
            with self.assertRaisesRegex(ValueError, "incompatible"):
                self._create_provenance(provenance, arguments)

    def test_provenance_rejects_empty_compilers_and_mesonly_trace(self):
        provenance = self._load_module("provenance_tools", self.provenance_path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            arguments = self._valid_provenance_fixture(root, provenance)
            evidence = Path(arguments.compiler_evidence[0].split("=", 1)[1])
            evidence.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Compiler evidence"):
                self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "mismatch", provenance)
            evidence = Path(arguments.compiler_evidence[0].split("=", 1)[1])
            content = json.loads(evidence.read_text(encoding="utf-8"))
            content["host"]["c"]["exelist"] = ["/unrelated/compiler"]
            evidence.write_text(json.dumps(content), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selected tools"):
                self._create_provenance(provenance, arguments)
            arguments = self._valid_provenance_fixture(root / "trace", provenance)
            Path(arguments.tool_trace).write_text(
                "phase|pycairo|start\nexec|meson|run\nphase|pycairo|end\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "trace"):
                self._create_provenance(provenance, arguments)

    def test_provenance_output_cannot_replace_existing_evidence(self):
        provenance = self._load_module(
            "linux_tray_provenance_exclusive",
            self.provenance_path,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "provenance.json"
            output.write_text("preserve\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                provenance.write_report_exclusively(
                    output,
                    {"new": "evidence"},
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve\n")

    def test_provenance_failure_cannot_create_success_evidence(self):
        provenance = self._load_module(
            "linux_tray_provenance_failure",
            self.provenance_path,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "provenance.json"
            with mock.patch("sys.stderr") as stderr:
                result = provenance.main(
                    [
                        "--output",
                        str(output),
                        "--interpreter",
                        sys.executable,
                        "--interpreter-invocation",
                        sys.executable,
                        "--verification",
                        str(Path(temporary_directory) / "missing.json"),
                        "--builder-os",
                        "ubuntu-22.04",
                        "--architecture",
                        "x86_64",
                        "--native-archive-provenance",
                        "unavailable",
                        "--linker-selector",
                        "bfd",
                        "--linker-discovery",
                        str(Path(temporary_directory) / "missing-linker"),
                        "--tool-trace",
                        str(Path(temporary_directory) / "missing-trace"),
                        "--compiler-evidence",
                        "PyGObject=" + str(Path(temporary_directory) / "missing-evidence"),
                    ]
                )
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertEqual(
                "".join(
                    call.args[0]
                    for call in stderr.write.call_args_list
                ),
                "Linux tray provenance failed: ValueError\n",
            )

    def test_documents_distinguish_planned_and_empirical_results(self):
        design = (
            self.project_root / "docs" / "linux-tray-design.md"
        ).read_text(encoding="utf-8")
        acceptance = (
            self.project_root / "docs" / "linux-tray-acceptance.md"
        ).read_text(encoding="utf-8")
        for required in (
            "CLEANUP_FAILED",
            "17,184 bytes",
            "PR_SET_PDEATHSIG",
            "PyInstaller",
            "Windows continues to use pystray",
            "Resource | Builder source and collection",
            "Dependency-ordered implementation slices",
        ):
            self.assertIn(required, design)
        self.assertIn("G1 has not run", acceptance)
        self.assertIn("G2 through G7", acceptance)
        self.assertIn("does not prove standalone", acceptance)
        self.assertIn("redistribution", acceptance.lower())
        self.assertIn("Gate execution matrix", acceptance)
        self.assertIn("G2–G7 currently reject", acceptance)
        for document in (design, acceptance):
            self.assertIn("proxy exit 74", document)
            self.assertIn("instrumentation failure", document)
            self.assertIn("printable ASCII", document)

    def _run_stubbed_g1(self, temporary_root, work_root, failure=None):
        temporary_root.mkdir(parents=True, exist_ok=True)
        provenance = self._load_module(
            "orchestration_provenance", self.provenance_path
        )
        fixture_root = temporary_root / "fixture"
        arguments = self._valid_provenance_fixture(fixture_root, provenance)
        for directory in ("sources", "wheels", "toolchain"):
            (fixture_root / directory).mkdir()
        for named in arguments.source:
            path = Path(named.split("=", 1)[1])
            (fixture_root / "sources" / path.name).write_bytes(path.read_bytes())
        for named in arguments.wheel:
            path = Path(named.split("=", 1)[1])
            (fixture_root / "wheels" / path.name).write_bytes(path.read_bytes())
        for value in arguments.toolchain_artifact:
            path = Path(value)
            (fixture_root / "toolchain" / path.name).write_bytes(path.read_bytes())
        compiler = json.loads(
            Path(arguments.compiler_evidence[0].split("=", 1)[1]).read_text(
                encoding="utf-8"
            )
        )
        compiler["host"]["c"]["exelist"] = [str(work_root / "tool-proxies" / "cc")]
        compiler["host"]["c"]["linker_exelist"] = [
            str(work_root / "tool-proxies" / "cc")
        ]
        (fixture_root / "compiler.json").write_text(
            json.dumps(compiler), encoding="utf-8"
        )
        tools = fixture_root / "fake-tools"
        tools.mkdir()
        (fixture_root / "module.so").write_bytes(self._fake_elf())
        linker = tools / "ld.bfd"
        linker.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ ${1:-} == --version ]]; then printf 'GNU ld 2.38\\n'; exit; fi\n"
            "output=\nprevious=\n"
            "for argument in \"$@\"; do\n"
            "  [[ $previous == -o ]] && output=$argument\n"
            "  previous=$argument\n"
            "done\n"
            "if [[ ${G1_FIXTURE_FAIL:-} != stale-output || "
            "${G1_BUILD_BINDING:-} != PyGObject ]]; then\n"
            "  [[ -z $output ]] || cp -- \"$G1_FIXTURE_ELF\" \"$output\"\n"
            "fi\n",
            encoding="utf-8",
        )
        linker.chmod(0o700)
        for name in ("ninja", "pkg-config"):
            script = tools / name
            script.write_text(
                "#!/bin/sh\n"
                f"if test \"${{1:-}}\" = --version; then printf '{name}-version\\n'; fi\n",
                encoding="utf-8",
            )
            script.chmod(0o700)
        cc = tools / "cc"
        cc.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'tool:cc:%s\\n' \"${1:-none}\" >>\"$G1_FIXTURE_EVENTS\"\n"
            "prefix=\noutput=\nprevious=\ncompile=0\nshared=0\nprint_linker=0\nquery_linker=0\n"
            "forward=()\n"
            "for argument in \"$@\"; do\n"
            "  [[ $previous == -o ]] && output=$argument\n"
            "  case $argument in\n"
            "    -B*) prefix=${argument#-B} ;;\n"
            "    -fuse-ld=bfd) ;;\n"
            "    -print-prog-name=ld.bfd) print_linker=1 ;;\n"
            "    -Wl,--version) query_linker=1 ;;\n"
            "    --version)\n"
            "      printf 'gcc version 11.4.0\\n'\n"
            "      [[ ${G1_FIXTURE_FAIL:-} != tool-identity ]] || exit 23\n"
            "      exit ;;\n"
            "    -c) compile=1; forward+=(\"$argument\") ;;\n"
            "    -shared) shared=1; forward+=(\"$argument\") ;;\n"
            "    *) forward+=(\"$argument\") ;;\n"
            "  esac\n"
            "  previous=$argument\n"
            "done\n"
            "if (( print_linker )); then\n"
            "  [[ -n $prefix ]] || prefix=$(dirname \"$0\")/\n"
            "  printf '%sld.bfd\\n' \"$prefix\"; exit\n"
            "fi\n"
            "if (( query_linker )); then \"${prefix}ld.bfd\" --version; exit; fi\n"
            "if (( compile )); then\n"
            "  if [[ ${G1_FIXTURE_FAIL:-} != stale-output || "
            "${G1_BUILD_BINDING:-} != PyGObject ]]; then\n"
            "    [[ -z $output ]] || printf 'fixture-object' >\"$output\"\n"
            "  fi\n"
            "  exit\n"
            "fi\n"
            "if (( shared )); then \"${prefix}ld.bfd\" \"${forward[@]}\"; exit; fi\n"
            "printf 'gcc version 11.4.0\\n'\n",
            encoding="utf-8",
        )
        cc.chmod(0o700)
        meson = tools / "meson"
        meson.write_text(
            "#!/bin/sh\n"
            "if test \"${1:-}\" = introspect; then "
            "printf 'introspect\\n' >>\"$G1_FIXTURE_EVENTS\"; "
            f"cat '{fixture_root / 'compiler.json'}'; "
            "elif test \"${1:-}\" = --version; then printf '1.4.1\\n'; fi\n",
            encoding="utf-8",
        )
        meson.chmod(0o700)
        helper = fixture_root / "collector-helper.py"
        helper.write_text(
            "import importlib.util, sys\n"
            "spec=importlib.util.spec_from_file_location('collector', sys.argv[1])\n"
            "module=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "raise SystemExit(module.main(sys.argv[2:], "
            "distribution_version=module.EXPECTED_DISTRIBUTIONS.__getitem__))\n",
            encoding="utf-8",
        )
        command = r'''
source "$1"
REAL_PYTHON=$2
WORK_ROOT=$3
FIXTURE=$4
VALID_TRACE=$5
EVENTS=$6
export G1_FIXTURE_FAIL=$VALID_TRACE G1_FIXTURE_EVENTS=$EVENTS
export G1_FIXTURE_ELF="$FIXTURE/module.so"
G1_PROXY_PYTHON=$REAL_PYTHON
record() { printf '%s\n' "$1" >>"$EVENTS"; }
verify_builder_platform() {
  record platform
  [[ $VALID_TRACE != platform ]] || return 23
}
verify_interpreter() { :; }
verify_build_prerequisites() { :; }
canonical_tool() { printf '%s/fake-tools/%s\n' "$FIXTURE" "${1##*/}"; }
run_isolated_pip() {
  record pip
  shift
  if [[ " $* " == *" download "* ]]; then
    local destination=""
    while [[ $# -gt 0 ]]; do
      if [[ $1 == --dest ]]; then destination=$2; break; fi
      shift
    done
    cp -- "$FIXTURE"/toolchain/*.whl "$destination/"
  fi
}
run_isolated_python() {
  shift
  if [[ " $* " == *" -m venv "* ]]; then
    local destination=${!#}
    mkdir -p -- "$destination/bin"
    cp -- "$FIXTURE/fake-tools/meson" "$destination/bin/meson"
    ln -s -- "$REAL_PYTHON" "$destination/bin/python"
  elif [[ " $* " == *" $BINDING_VERIFIER "* ]]; then
    record verifier
    cat -- "$FIXTURE/verification.json"
  elif [[ " $* " == *" $PROVENANCE_COLLECTOR "* ]]; then
    record collector
    if [[ $VALID_TRACE == recording-failure ]]; then
      : >"$G1_TOOL_TRACE.failed"
    fi
    "$REAL_PYTHON" -B "$FIXTURE/collector-helper.py" \
      "$PROVENANCE_COLLECTOR" "${@:4}"
  else
    return 97
  fi
}
run_binding_pip() {
  local binding=$1
  local operation=$2
  shift 3
  record "binding:$binding:$operation"
  local destination=
  local wheel_directory=
  local build_directory=
  local argument
  local previous=
  for argument in "$@"; do
    [[ $previous == --dest ]] && destination=$argument
    [[ $previous == --wheel-dir ]] && wheel_directory=$argument
    case $argument in
      --config-settings=build-dir=*) build_directory=${argument#*=build-dir=} ;;
    esac
    previous=$argument
  done
  if [[ $operation == metadata ]]; then
    [[ $binding != PyGObject || $VALID_TRACE != metadata ]] || return 23
    cp -- "$FIXTURE/sources/${binding,,}-"* "$destination/"
    return
  fi
  [[ $operation != wheel ]] || {
    local scratch="$WORK_ROOT/tmp/$binding-fixture"
    mkdir -p -- "$scratch"
    printf 'int fixture(void) { return 0; }\n' >"$scratch/source.c"
    if [[ $VALID_TRACE == stale-output || $VALID_TRACE == same-byte-rebuild ]] &&
       [[ $binding == PyGObject ]]; then
      printf 'fixture-object' >"$scratch/module.o"
      cp -- "$G1_FIXTURE_ELF" "$scratch/module.so"
    fi
    if [[ $binding == pycairo ]]; then
      [[ -z $build_directory ]] || return 91
      if [[ $VALID_TRACE == wrong-backend ]]; then
        "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
          G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/meson" \
          setup "$scratch" || return
      fi
    else
      [[ $build_directory == "$WORK_ROOT/build/pygobject" ]] || return 92
      mkdir -p -- "$build_directory/meson-info"
      "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
        G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/meson" \
        setup "$build_directory" || return
      "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
        G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/ninja" \
        -C "$build_directory" || return
      "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
        G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/cc" \
        -Wl,--version || return
    fi
    "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
      G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/pkg-config" \
      --cflags cairo || return
    if [[ $VALID_TRACE == version-only && $binding == PyGObject ]]; then
      "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
        G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/cc" \
        --version -c "$scratch/source.c" -o "$scratch/module.o" || return
      "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
        G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/cc" \
        --version unused.o -shared -o "$scratch/module.so" || return
      cp -- "$FIXTURE/wheels/${binding,,}-"*.whl "$wheel_directory/"
      return
    fi
    "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
      G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/cc" \
      -fPIC -c "$scratch/source.c" -o "$scratch/module.o" || return
    "${ISOLATED_ENVIRONMENT[@]}" G1_BUILD_BINDING=$binding \
      G1_BUILD_OPERATION=wheel "$WORK_ROOT/tool-proxies/cc" \
      -shared "$scratch/module.o" -o "$scratch/module.so" || return
    if [[ $VALID_TRACE == provenance && $binding == PyGObject ]]; then
      printf 'result|PyGObject|cc|compile|23|complete|-\n' >>"$G1_TOOL_TRACE"
    fi
    if [[ $VALID_TRACE == driver-bypass && $binding == PyGObject ]]; then
      printf 'result|PyGObject|ld|link|0|complete|999999\n' >>"$G1_TOOL_TRACE"
    fi
    cp -- "$FIXTURE/wheels/${binding,,}-"*.whl "$wheel_directory/"
  }
}
if [[ $VALID_TRACE == inventory ]]; then
  find() { printf 'partial\0'; return 23; }
fi
dpkg-query() { printf '1\n'; }
run_g1 "$REAL_PYTHON" "$WORK_ROOT"
'''
        return subprocess.run(
            [
                "bash", "-c", command, "gate-test", str(self.runner),
                sys.executable, str(work_root), str(fixture_root),
                failure or "success", str(temporary_root / "orchestration-events"),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def _valid_provenance_fixture(self, root, provenance):
        root.mkdir(parents=True, exist_ok=True)
        verification = root / "verification.json"
        verification.write_text(
            json.dumps(
                {
                    "bindings": {"PyGObject": "3.48.2", "pycairo": "1.26.1"},
                    "native": {
                        "cairo": "1.16.0",
                        "gdk_pixbuf": "2.42.8",
                        "glib": "2.72.4",
                        "gtk": "3.24.33",
                    },
                    "python": {"implementation": "CPython", "version": "3.12.0"},
                    "required_namespaces": provenance.EXPECTED_NAMESPACES,
                }
            ),
            encoding="utf-8",
        )
        requirements = []
        requirement_sets = {
            "requirements-linux-tray.txt": {
                name: provenance.EXPECTED_DISTRIBUTIONS[name]
                for name in provenance.REQUIRED_SOURCES
            },
            "requirements-linux-tray-build.txt": (
                provenance.EXPECTED_TOOLCHAIN_DISTRIBUTIONS
            ),
        }
        for filename, pins in requirement_sets.items():
            requirement = root / filename
            requirement.write_text(
                "".join(f"{name}=={version}\n" for name, version in sorted(pins.items())),
                encoding="utf-8",
            )
            requirements.append(str(requirement))
        sources = {}
        wheels = {}
        compatible_tag = str(next(sys_tags()))
        for name in ("PyGObject", "pycairo"):
            version = provenance.EXPECTED_DISTRIBUTIONS[name]
            normalized = name.replace("-", "_").lower()
            source = root / f"{normalized}-{version}.tar.gz"
            self._write_sdist(source, name, version)
            wheel = root / f"{normalized}-{version}-{compatible_tag}.whl"
            self._write_wheel(wheel, name, version, compatible_tag)
            sources[name] = source
            wheels[name] = wheel
        toolchain_artifacts = []
        for name, version in provenance.EXPECTED_TOOLCHAIN_DISTRIBUTIONS.items():
            artifact = root / f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
            self._write_wheel(artifact, name, version, "py3-none-any")
            toolchain_artifacts.append(str(artifact))
        real_directory = root / "tools"
        proxy_directory = root / "proxies"
        real_directory.mkdir()
        proxy_directory.mkdir()
        proxy_names = {
            "cc": "cc",
            "ld": "ld.bfd",
            "meson": "meson",
            "ninja": "ninja",
            "pkg-config": "pkg-config",
        }
        build_tools = {}
        tool_proxies = {}
        for name, filename in proxy_names.items():
            real = real_directory / filename
            proxy = proxy_directory / filename
            real.write_text(f"real {name}\n", encoding="utf-8")
            proxy.write_text(f"proxy {name}\n", encoding="utf-8")
            real.chmod(0o700)
            proxy.chmod(0o700)
            build_tools[name] = real
            tool_proxies[name] = proxy
        source_hash = hashlib.sha256(b"int fixture(void) { return 0; }\n").hexdigest()
        object_hash = hashlib.sha256(b"fixture-object").hexdigest()
        elf_hash = hashlib.sha256(self._fake_elf()).hexdigest()
        text_hash = hashlib.sha256(b"\x90\xc3").hexdigest()

        def native_line(binding, tool, action, token):
            phase_root = root / binding
            detail = {
                "inputs": [[str(phase_root / "source.c"), source_hash]]
                if action == "compile" else
                [[str(phase_root / "module.o"), object_hash]],
                "output": [str(phase_root / ("module.o" if action == "compile" else "module.so")),
                           object_hash if action == "compile" else elf_hash],
                "text": None if action == "compile" else text_hash,
                "produced": True,
            }
            encoded = base64.urlsafe_b64encode(
                json.dumps(detail, separators=(",", ":")).encode()
            ).decode()
            return f"result|{binding}|{tool}|{action}|0|complete|{token}|{encoded}\n"

        trace = root / "tool-trace.txt"
        Path(str(trace) + ".pending").mkdir()
        trace.write_text(
            "".join(
                [
                    "phase|driver-check|start\n",
                    native_line("driver-check", "cc", "compile", "-"),
                    native_line("driver-check", "ld", "link", "700"),
                    native_line("driver-check", "cc", "link", "700"),
                    "phase|driver-check|end\n",
                    "phase|pycairo|start\n",
                    f"artifact|pycairo|source|{sources['pycairo'].name}\n",
                    "result|pycairo|pkg-config|run|0|complete|-|-\n",
                    native_line("pycairo", "cc", "compile", "-"),
                    native_line("pycairo", "ld", "link", "701"),
                    native_line("pycairo", "cc", "link", "701"),
                    f"artifact|pycairo|wheel|{wheels['pycairo'].name}\n",
                    "phase|pycairo|end\n",
                    "phase|PyGObject|start\n",
                    f"artifact|PyGObject|source|{sources['PyGObject'].name}\n",
                    "result|PyGObject|meson|run|0|complete|-|-\n",
                    "result|PyGObject|ninja|run|0|complete|-|-\n",
                    "result|PyGObject|pkg-config|run|0|complete|-|-\n",
                    native_line("PyGObject", "cc", "compile", "-"),
                    native_line("PyGObject", "ld", "link", "702"),
                    native_line("PyGObject", "cc", "link", "702"),
                    f"artifact|PyGObject|wheel|{wheels['PyGObject'].name}\n",
                    "phase|PyGObject|end\n",
                ]
            ),
            encoding="utf-8",
        )
        compiler = {
            "default_suffix": "c",
            "exelist": [str(tool_proxies["cc"])],
            "file_suffixes": ["c"],
            "full_version": "gcc version 11.4.0",
            "id": "gcc",
            "linker_exelist": [str(tool_proxies["cc"])],
            "linker_id": "ld.bfd",
            "version": "11.4.0",
        }
        evidence = root / "PyGObject-compilers.json"
        evidence.write_text(
            json.dumps({"host": {"c": compiler}, "build": {}}),
            encoding="utf-8",
        )
        compiler_evidence = [f"PyGObject={evidence}"]
        interpreter = root / "python3.12"
        interpreter.write_text("interpreter\n", encoding="utf-8")
        return types.SimpleNamespace(
            output=str(root / "provenance.json"),
            interpreter=str(interpreter),
            interpreter_invocation=str(interpreter),
            verification=str(verification),
            requirements=requirements,
            source=[f"{name}={path}" for name, path in sources.items()],
            source_url=[
                f"{name}={url}"
                for name, url in provenance.EXPECTED_SOURCE_URLS.items()
            ],
            wheel=[f"{name}={path}" for name, path in wheels.items()],
            toolchain_artifact=toolchain_artifacts,
            tool_trace=str(trace),
            compiler_evidence=compiler_evidence,
            distribution=sorted(provenance.EXPECTED_DISTRIBUTIONS),
            native_package=[
                f"{name}=1" for name in sorted(provenance.REQUIRED_NATIVE_PACKAGES)
            ],
            build_tool=[f"{name}={path}" for name, path in build_tools.items()],
            build_tool_version=[
                f"{name}="
                + {
                    "cc": "gcc version 11.4.0",
                    "ld": "GNU ld 2.38",
                    "meson": "1.4.1",
                    "ninja": "1.10.1",
                    "pkg-config": "0.29.2",
                }[name]
                for name in build_tools
            ],
            tool_proxy=[f"{name}={path}" for name, path in tool_proxies.items()],
            linker_selector="bfd",
            linker_discovery=str(tool_proxies["ld"]),
            native_archive_provenance="unavailable",
            builder_os="ubuntu-22.04",
            architecture="x86_64",
        )

    @staticmethod
    def _create_provenance(provenance, arguments):
        return provenance.create_report(
            arguments,
            distribution_version=provenance.EXPECTED_DISTRIBUTIONS.__getitem__,
        )

    @staticmethod
    def _provenance_argv(arguments):
        values = []
        for name, supplied in vars(arguments).items():
            for value in supplied if isinstance(supplied, list) else [supplied]:
                values.extend(["--" + name.replace("_", "-"), str(value)])
        return values

    @staticmethod
    def _write_sdist(path, name, version, backend=None):
        metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode()
        backend = backend or {
            "PyGObject": "mesonpy",
            "pycairo": "setuptools.build_meta",
        }[name]
        project = (
            "[build-system]\n"
            f"build-backend = \"{backend}\"\n"
        ).encode()
        with tarfile.open(path, "w:gz") as archive:
            for filename, content in (
                ("PKG-INFO", metadata),
                ("pyproject.toml", project),
                ("source.c", b"int fixture(void) { return 0; }\n"),
            ):
                info = tarfile.TarInfo(f"{name}-{version}/{filename}")
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))

    @staticmethod
    def _write_wheel(path, name, version, tag, wheel_versions=("1.0",)):
        dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
        wheel_headers = "".join(
            f"Wheel-Version: {wheel_version}\n"
            for wheel_version in wheel_versions
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                f"{dist_info}/METADATA",
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
            )
            archive.writestr(
                f"{dist_info}/WHEEL",
                wheel_headers
                + "Generator: test\nRoot-Is-Purelib: false\n"
                f"Tag: {tag}\n\n",
            )
            if name in {"pycairo", "PyGObject"}:
                archive.writestr("fixture/module.so", LinuxTrayGateConfigurationTests._fake_elf())

    @staticmethod
    def _fake_elf():
        names = b"\0.text\0.shstrtab\0"
        code = b"\x90\xc3"
        section_offset = 88
        content = bytearray(section_offset + 3 * 64)
        content[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", content, 18, 62)
        struct.pack_into("<Q", content, 40, section_offset)
        struct.pack_into("<HHH", content, 58, 64, 3, 2)
        content[64:66] = code
        content[66:66 + len(names)] = names
        struct.pack_into("<IIQQQQIIQQ", content, section_offset + 64,
                         1, 1, 6, 0, 64, len(code), 0, 0, 16, 0)
        struct.pack_into("<IIQQQQIIQQ", content, section_offset + 128,
                         7, 3, 0, 0, 66, len(names), 0, 0, 1, 0)
        return bytes(content)

    @staticmethod
    def _wheel_name_version(path):
        name, version, _build, _tags = parse_wheel_filename(path.name)
        return str(name), str(version)

    @classmethod
    def _requirement_map(cls, file_name):
        requirements = {}
        for line in (cls.project_root / file_name).read_text(
            encoding="utf-8"
        ).splitlines():
            name, version = line.split("==", 1)
            requirements[name] = version
        return requirements

    @staticmethod
    def _load_module(name, path):
        specification = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
