"""Small offline inputs; no package installation, compiler, GI or application imports."""

import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native = load("native_inputs", ROOT / "packaging/linux/capture_tray_native_inputs.py")
g1_tests = load("g1_fixture_helpers", ROOT / "tests/test_linux_tray_gate_configuration.py")
COMMIT = "a" * 40


def paragraph(record):
    return ("\n".join(key + ": " + str(value).replace("\n", "\n ")
                      for key, value in record.items()) + "\n\n").encode()


def tar_bytes(files, extra=(), **options):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", **options) as archive:
        for name, content in files.items():
            header = tarfile.TarInfo(name)
            header.size = len(content)
            archive.addfile(header, io.BytesIO(content))
        for header in extra:
            archive.addfile(header)
    return stream.getvalue()


def deb_bytes(control, files, extra=()):
    # Construct a tiny Debian ar container directly; never run dpkg-deb --build.
    entries = {"debian-binary": b"2.0\n", "control.tar.gz": gzip.compress(tar_bytes({"control": paragraph(control)})),
               "data.tar.gz": gzip.compress(tar_bytes(files, extra))}
    output = bytearray(b"!<arch>\n")
    for name, content in entries.items():
        output.extend(f"{name:<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(content):<10}`\n".encode())
        output.extend(content)
        if len(content) % 2:
            output.extend(b"\n")
    return bytes(output)


class FixtureSystem(native.System):
    """Only installed-state, source-checkout and signature trust are synthetic."""
    def __init__(self, fixture):
        super().__init__(native.Budget())
        self.fixture = fixture
        self.authenticated = []

    def installed(self, package_id):
        return {"Status": "install ok installed", **self.fixture.controls[package_id]}

    def builder(self):
        return {"os_release": 'ID=ubuntu\nVERSION_ID="22.04"\n', "architecture": "x86_64",
                "glibc": "glibc 2.35", "implementation": "CPython", "version": "3.12.0",
                "interpreter": self.fixture.arguments.interpreter,
                "library": str(self.fixture.library)}

    def committed(self, project, commit, path):
        if commit != COMMIT:
            raise native.Invalid("Unexpected fixture commit")
        return self.fixture.committed[path]

    def authenticate(self, keyring, signature, release):
        self.authenticated.append(str(release))
        return ["A" * 40]


class Fixture:
    def __init__(self, root):
        self.root = root
        self.bundle = root / "bundle"
        self.bundle.mkdir()
        self.project = root / "project"
        self.project.mkdir()
        self.keyring = root / "trusted.gpg"
        self.keyring.write_bytes(b"external keyring fixture")
        self.output = root / "native.json"
        self.controls, self.payloads, self.extra = {}, {}, {}
        self.committed = {}
        self.g1 = native.load_g1()
        helper = g1_tests.LinuxTrayGateConfigurationTests()
        self.arguments = helper._valid_provenance_fixture(self.bundle / "g1", self.g1)
        self.report = helper._create_provenance(self.g1, self.arguments)
        self.report_path = Path(self.arguments.output)
        self.report_path.write_text(json.dumps(self.report))
        self.g1_hash = native.digest(self.report_path.read_bytes())
        self.library = root / "libpython3.12.so.1.0"
        self.library.write_bytes(b"trusted interpreter library fixture")
        self.system = FixtureSystem(self)

        def relative(path):
            return str(Path(path).relative_to(self.bundle))

        def named(values):
            return {name: relative(path) for name, path in (v.split("=", 1) for v in values)}

        self.document = {
            "schema_version": 1,
            "g1": {"report": relative(self.report_path),
                   "requirements": {Path(p).name: relative(p) for p in self.arguments.requirements},
                   "sources": named(self.arguments.source), "wheels": named(self.arguments.wheel),
                   "toolchain": {Path(p).name: relative(p) for p in self.arguments.toolchain_artifact},
                   "trace": relative(self.arguments.tool_trace), "verification": relative(self.arguments.verification),
                   "compiler_evidence": named(self.arguments.compiler_evidence), "proxies": named(self.arguments.tool_proxy)},
            "repositories": [{"id": "jammy", "uri": "https://archive.ubuntu.com/ubuntu",
                              "release": "Release", "signature": "Release.gpg",
                              "packages": "Packages", "sources": "Sources",
                              "packages_index": "main/binary-amd64/Packages", "sources_index": "main/source/Sources"}],
            "sources": [], "packages": [], "non_dpkg": [],
        }
        for p in self.arguments.requirements:
            self.committed[Path(p).name] = Path(p).read_bytes()
        for kind, path in (("cpython", Path(self.arguments.interpreter)), ("cpython-library", self.library)):
            target = self.bundle / ("copy-" + path.name)
            target.write_bytes(path.read_bytes())
            self.document["non_dpkg"].append({"kind": kind, "path": str(path), "bundle_path": relative(target),
                                             "transformation": "identity"})
        for index, resource in enumerate(sorted(native.PROJECT_RESOURCES)):
            path = self.project / resource
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"project resource fixture\n")
            self.committed[resource] = path.read_bytes()
            target = self.bundle / f"resource-{index}"
            target.write_bytes(path.read_bytes())
            self.document["non_dpkg"].append({"kind": "project-resource", "path": str(path),
                                             "bundle_path": relative(target), "project_path": resource,
                                             "transformation": "identity"})
        for name in sorted(self.g1.REQUIRED_NATIVE_PACKAGES):
            self.add_package(name)
        self.add_package("runtime-dependency", depends="", multi="allowed")
        self.controls["libgtk-3-dev:amd64"]["Depends"] = "missing-alternative | runtime-dependency:any (>= 1)"
        self.package("libgtk-3-dev")["selected"] = ["runtime-dependency:amd64"]
        for name in sorted(native.TYPELIBS):
            self.consume("libgtk-3-dev", "typelib:" + name, self.root / (name + ".typelib"), b"typelib fixture")
        for role, prefix in native.NATIVE_ROLES.items():
            self.consume("libgtk-3-dev", "native:" + role, self.root / (prefix + ".0"), b"native fixture")
        self.consume("fonts-dejavu-core", "font:dejavu-sans", self.root / "DejaVuSans.ttf", b"font fixture")
        for role, record in self.report["build_tools"].items():
            if role == "meson":
                continue
            path = Path(record["resolved_path"])
            self.consume("build-essential", "build:" + role, path, path.read_bytes())
        source_archive = self.bundle / "native-fixture_1.tar.gz"
        source_archive.write_bytes(gzip.compress(tar_bytes({"native-fixture/README": b"source"})))
        descriptor = self.bundle / "native-fixture_1.dsc"
        checksum = f"{native.digest(source_archive.read_bytes())} {source_archive.stat().st_size} {source_archive.name}"
        descriptor.write_bytes(paragraph({"Format": "3.0 (native)", "Source": "native-fixture", "Version": "1",
                                          "Checksums-Sha256": "\n" + checksum}))
        self.source_files = [source_archive, descriptor]
        self.document["sources"] = [{"repository": "jammy", "name": "native-fixture", "version": "1",
                                     "files": {p.name: p.name for p in self.source_files}}]
        (self.bundle / "Release.gpg").write_bytes(b"signature adapter fixture")
        self.refresh()

    def add_package(self, name, depends="", multi="no", arch="amd64"):
        package_id = name + ":" + arch
        self.controls[package_id] = {"Package": name, "Version": "1", "Architecture": arch,
                                     "Multi-Arch": multi, "Source": "native-fixture (1)"}
        if depends:
            self.controls[package_id]["Depends"] = depends
        self.payloads[package_id] = {}
        self.extra[package_id] = []
        self.document["packages"].append({"id": package_id, "repository": "jammy",
                                          "archive": f"{name}_1_{arch}.deb", "classification": "build-only",
                                          "selected": [], "consumed": []})

    def package(self, name):
        return next(p for p in self.document["packages"] if p["id"].split(":")[0] == name)

    def consume(self, package, role, path, content):
        path.write_bytes(content)
        entry = self.package(package)
        if role.startswith(("native:", "typelib:", "font:")):
            entry["classification"] = "bundled-runtime"
        entry["consumed"].append({"path": str(path), "archive_path": str(path)[1:], "role": role,
                                   "transformation": "identity"})
        self.payloads[entry["id"]][str(path)[1:]] = content

    def save(self):
        (self.bundle / "bundle.json").write_text(json.dumps(self.document))

    def refresh(self):
        package_rows = []
        for item in self.document["packages"]:
            control = self.controls[item["id"]]
            content = deb_bytes(control, self.payloads[item["id"]], self.extra[item["id"]])
            (self.bundle / item["archive"]).write_bytes(content)
            package_rows.append(paragraph({**control, "Filename": "pool/main/" + item["archive"],
                                           "Size": len(content), "SHA256": native.digest(content)}))
        (self.bundle / "Packages").write_bytes(b"".join(package_rows))
        source_row = {"Package": "native-fixture", "Version": "1", "Directory": "pool/main/n/native-fixture",
                      "Checksums-Sha256": "\n" + "\n".join(
                          f"{native.digest(p.read_bytes())} {p.stat().st_size} {p.name}" for p in self.source_files)}
        (self.bundle / "Sources").write_bytes(paragraph(source_row))
        self.release()
        self.save()

    def release(self):
        checksum_lines = []
        for name, remote in (("Packages", "main/binary-amd64/Packages"), ("Sources", "main/source/Sources")):
            data = (self.bundle / name).read_bytes()
            checksum_lines.append(f"{native.digest(data)} {len(data)} {remote}")
        (self.bundle / "Release").write_bytes(paragraph({"Origin": "Ubuntu", "Codename": "jammy", "Suite": "jammy",
                                                        "Architectures": "amd64", "Components": "main",
                                                        "Date": "Mon, 01 Jan 2024 00:00:00 +0000",
                                                        "SHA256": "\n" + "\n".join(checksum_lines)}))

    def validate(self):
        self.save()
        return native.validate(self.bundle, self.keyring, self.g1_hash, self.project, COMMIT, self.system)

    def cli(self):
        self.save()
        with mock.patch.object(native, "System", return_value=self.system):
            return native.main(["--bundle", str(self.bundle), "--trusted-keyring", str(self.keyring),
                                "--g1-sha256", self.g1_hash, "--project-root", str(self.project),
                                "--source-commit", COMMIT, "--output", str(self.output)])


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux offline inspection tools required")
class NativeInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lmt-native-test-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = Fixture(Path(self.temporary.name))

    def reject(self):
        with mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(self.fixture.cli(), 1)
        self.assertFalse(self.fixture.output.exists())

    def test_complete_closure_and_exclusive_publication(self):
        before = self.fixture.report_path.read_bytes()
        self.assertEqual(self.fixture.cli(), 0)
        report = json.loads(self.fixture.output.read_bytes())
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(len(report["packages"]), 13)
        self.assertEqual(report["dependency_edges"][0]["to"], "runtime-dependency:amd64")
        self.assertEqual(report["g1_report"]["sha256"], self.fixture.g1_hash)
        self.assertEqual(report["native_package_archives"]["availability"], "validated-offline")
        self.assertEqual(self.fixture.report_path.read_bytes(), before)
        self.assertTrue(self.fixture.system.authenticated)

    def test_versioned_virtual_provider_and_predepends(self):
        f = self.fixture
        f.controls["runtime-dependency:amd64"]["Provides"] = "virtual-api (= 2:1.0~rc1-2)"
        f.controls["libgtk-3-dev:amd64"].pop("Depends")
        f.controls["libgtk-3-dev:amd64"]["Pre-Depends"] = "virtual-api (>= 2:1.0~rc1-1)"
        f.refresh()
        self.assertEqual(f.validate()["dependency_edges"][0]["kind"], "Pre-Depends")

    def test_versions_use_real_dpkg_ordering(self):
        system = native.System(native.Budget())
        self.assertTrue(system.version("2:1.0~rc1-1", "<<", "2:1.0-1"))
        self.assertFalse(system.version("1.9", ">>", "1.10"))
        with self.assertRaises(native.Invalid):
            system.version("--help", "=", "1")

    def test_all_architecture_and_native_selection(self):
        f = self.fixture
        item = f.package("runtime-dependency")
        old = item["id"]
        item["id"] = "runtime-dependency:all"
        item["archive"] = "runtime-dependency_1_all.deb"
        for mapping in (f.controls, f.payloads, f.extra):
            mapping[item["id"]] = mapping.pop(old)
        f.controls[item["id"]]["Architecture"] = "all"
        f.controls["libgtk-3-dev:amd64"]["Depends"] = "runtime-dependency:native"
        f.package("libgtk-3-dev")["selected"] = [item["id"]]
        f.refresh()
        self.assertIn(item["id"], f.validate()["packages"])

    def test_any_requires_allowed_multiarch(self):
        self.fixture.controls["runtime-dependency:amd64"]["Multi-Arch"] = "same"
        self.fixture.refresh()
        self.reject()

    def test_explicit_architecture_and_native_foreign_rules(self):
        provider = {"Package": "some-package", "Version": "1", "Architecture": "all", "Multi-Arch": "foreign"}
        system = native.System(native.Budget())
        self.assertTrue(native.satisfies(("some-package", None, None, None), provider, system))
        self.assertFalse(native.satisfies(("some-package", "amd64", None, None), provider, system))
        self.assertFalse(native.satisfies(("some-package", "native", None, None), provider, system))
        provider.update({"Architecture": "amd64", "Multi-Arch": "same"})
        self.assertTrue(native.satisfies(("some-package", "amd64", None, None), provider, system))
        self.assertTrue(native.satisfies(("some-package", "native", None, None), provider, system))

    def test_unversioned_provides_cannot_satisfy_versioned_dependency(self):
        f = self.fixture
        f.controls["runtime-dependency:amd64"]["Provides"] = "virtual-api"
        f.controls["libgtk-3-dev:amd64"]["Depends"] = "virtual-api (>= 1)"
        f.refresh()
        self.reject()

    def test_missing_provider_and_bad_selection(self):
        for selected in (["missing:amd64"], [], ["fontconfig:amd64"]):
            with self.subTest(selected=selected):
                self.fixture.package("libgtk-3-dev")["selected"] = selected
                self.reject()

    def test_unrelated_whole_system_packages_rejected(self):
        self.fixture.add_package("unrelated-desktop")
        self.fixture.refresh()
        self.reject()

    def test_conflicting_or_foreign_package(self):
        f = self.fixture
        f.document["packages"].append(copy.deepcopy(f.document["packages"][0]))
        self.reject()
        f.document["packages"].pop()
        f.controls["runtime-dependency:amd64"]["Architecture"] = "arm64"
        f.refresh()
        self.reject()

    def test_missing_source_and_descriptor_mismatch(self):
        f = self.fixture
        original = copy.deepcopy(f.document["sources"])
        f.document["sources"] = []
        self.reject()
        f.document["sources"] = original
        descriptor = f.source_files[1]
        descriptor.write_bytes(descriptor.read_bytes().replace(b"Version: 1", b"Version: 2"))
        f.refresh()
        self.reject()

    def test_missing_index_and_release_hash_mismatch(self):
        f = self.fixture
        f.document["repositories"][0]["packages_index"] = "main/binary-amd64/Missing"
        self.reject()
        f.document["repositories"][0]["packages_index"] = "main/binary-amd64/Packages"
        with (f.bundle / "Packages").open("ab") as stream:
            stream.write(b"changed")
        self.reject()

    def test_archive_hash_checked_before_decompression(self):
        f = self.fixture
        path = f.bundle / f.package("libgtk-3-dev")["archive"]
        path.write_bytes(b"changed archive")
        with mock.patch.object(native, "inspect_deb", wraps=native.inspect_deb) as inspect:
            self.reject()
            self.assertNotIn(path, [call.args[0] for call in inspect.call_args_list])

    def test_index_archive_and_installed_metadata_must_agree(self):
        original = self.fixture.system.installed
        def changed(package_id):
            result = original(package_id)
            result["Depends"] = "hidden-dependency"
            return result
        with mock.patch.object(self.fixture.system, "installed", side_effect=changed):
            self.reject()

    def test_payload_bytes_and_symlink_targets(self):
        f = self.fixture
        use = f.package("fonts-dejavu-core")["consumed"][0]
        Path(use["path"]).write_bytes(b"changed font")
        self.reject()

    def test_relative_symlink_positive_and_changed_target(self):
        f = self.fixture
        path = f.root / "dependency-link"
        target = f.root / "dependency-real"
        target.write_bytes(b"same bytes")
        path.symlink_to(target.name)
        package = f.package("runtime-dependency")
        package["consumed"] = [{"path": str(path), "archive_path": str(path)[1:], "role": "dependency",
                                 "transformation": "identity"}]
        f.payloads[package["id"]][str(target)[1:]] = target.read_bytes()
        link = tarfile.TarInfo(str(path)[1:])
        link.type, link.linkname = tarfile.SYMTYPE, target.name
        f.extra[package["id"]] = [link]
        f.refresh()
        self.assertEqual(len(f.validate()["packages"]), 13)
        path.unlink()
        path.symlink_to("wrong-target")
        self.reject()

    def link_chain(self):
        f = self.fixture
        first, middle, real, unrelated = [f.root / n for n in ("first-link", "middle-link", "real-file", "unrelated-file")]
        real.write_bytes(b"identical bytes")
        unrelated.write_bytes(real.read_bytes())
        first.symlink_to(middle.name)
        middle.symlink_to(real.name)
        package = f.package("runtime-dependency")
        package["consumed"] = [{"path": str(first), "archive_path": str(first)[1:],
                                "role": "dependency", "transformation": "identity"}]
        f.payloads[package["id"]][str(real)[1:]] = real.read_bytes()
        for path, target in ((first, middle), (middle, real)):
            link = tarfile.TarInfo(str(path)[1:])
            link.type, link.linkname = tarfile.SYMTYPE, target.name
            f.extra[package["id"]].append(link)
        f.refresh()
        return first, middle, real, unrelated

    def test_regression_intermediate_link_same_bytes_cannot_publish(self):
        _, middle, _, unrelated = self.link_chain()
        middle.unlink()
        middle.symlink_to(unrelated.name)
        self.reject()

    def test_regression_intermediate_mutation_at_recheck_cannot_publish(self):
        _, middle, _, unrelated = self.link_chain()
        original = native.recheck_installed
        def mutate(*args):
            middle.unlink()
            middle.symlink_to(unrelated.name)
            return original(*args)
        with mock.patch.object(native, "recheck_installed", side_effect=mutate):
            self.reject()

    def test_multihop_chain_records_every_link_and_publishes(self):
        first, middle, real, _ = self.link_chain()
        self.assertEqual(self.fixture.cli(), 0)
        report = json.loads(self.fixture.output.read_bytes())
        chain = report["packages"]["runtime-dependency:amd64"]["consumed"][0]["chain"]
        self.assertEqual(chain["links"], [
            {"path": str(first), "target": middle.name, "resolved_path": str(real)},
            {"path": str(middle), "target": real.name, "resolved_path": str(real)},
        ])
        self.assertEqual(chain["terminal"], str(real))
        self.assertEqual(chain["records"][str(real)[1:]]["sha256"], native.digest(real.read_bytes()))

    def test_path_component_links_and_relative_parent_resolution(self):
        f = self.fixture
        directory = f.root / "real-directory"
        directory.mkdir()
        nested = directory / "nested"
        nested.mkdir()
        target = directory / "file"
        target.write_bytes(b"component target")
        alias = f.root / "directory-alias"
        alias.symlink_to("real-directory/nested", target_is_directory=True)
        first = f.root / "component-link"
        first.symlink_to("directory-alias/../file")
        package = f.package("runtime-dependency")
        package["consumed"] = [{"path": str(first), "archive_path": str(first)[1:],
                                "role": "dependency", "transformation": "identity"}]
        f.payloads[package["id"]][str(target)[1:]] = target.read_bytes()
        for path in (alias, first):
            header = tarfile.TarInfo(str(path)[1:])
            header.type, header.linkname = tarfile.SYMTYPE, os.readlink(path)
            f.extra[package["id"]].append(header)
        f.refresh()
        report = f.validate()
        chain = report["packages"][package["id"]]["consumed"][0]["chain"]
        self.assertEqual(chain["terminal"], str(target))
        self.assertEqual(chain["links"][1]["resolved_path"], str(nested))
        alias.unlink()
        alias.symlink_to("real-directory", target_is_directory=True)
        self.reject()

    def test_chain_cycle_missing_hop_cross_package_and_limit_rejected(self):
        first, middle, real, _ = self.link_chain()
        f = self.fixture
        package = f.package("runtime-dependency")
        with mock.patch.object(native, "MAX_LINK_HOPS", 1):
            self.reject()
        middle.unlink()
        middle.symlink_to(first.name)
        f.extra[package["id"]][-1].linkname = first.name
        f.refresh()
        self.reject()
        middle.unlink()
        middle.symlink_to(real.name)
        f.extra[package["id"]][-1].linkname = real.name
        # Another validated package cannot supply a target under the schema's
        # explicitly same-package consumed-link policy.
        content = f.payloads[package["id"]].pop(str(real)[1:])
        f.payloads["fontconfig:amd64"][str(real)[1:]] = content
        f.refresh()
        self.reject()
        f.payloads[package["id"]][str(real)[1:]] = content
        f.extra[package["id"]].pop()
        f.refresh()
        self.reject()

    def test_invalid_or_missing_signature_cannot_publish(self):
        for failure in (native.Invalid("bad signature"), OSError("missing keyring")):
            with self.subTest(failure=failure), mock.patch.object(self.fixture.system, "authenticate", side_effect=failure):
                self.reject()

    def test_real_gpgv_rejects_invalid_signature(self):
        f = self.fixture
        with self.assertRaises(native.Invalid):
            native.System(native.Budget()).authenticate(f.keyring, f.bundle / "Release.gpg", f.bundle / "Release")

    def test_signature_status_requires_validsig_and_strong_digest(self):
        system = native.System(native.Budget())
        f = self.fixture
        status = b"[GNUPG:] VALIDSIG " + b"A" * 40 + b" 2026-01-01 1767225600 0 4 0 1 8 00\n"
        with mock.patch.object(system, "run", return_value=(status, 0)) as run:
            self.assertEqual(system.authenticate(f.keyring, f.bundle / "Release.gpg", f.bundle / "Release"), ["A" * 40])
            self.assertIn(str(f.keyring), run.call_args.args[0])
        for invalid in (b"[GNUPG:] GOODSIG claimed-key Claimed Identity\n", status.replace(b" 8 00", b" 2 00")):
            with self.subTest(status=invalid), mock.patch.object(system, "run", return_value=(invalid, 0)):
                with self.assertRaises(native.Invalid):
                    system.authenticate(f.keyring, f.bundle / "Release.gpg", f.bundle / "Release")

    def test_expired_release_and_wrong_component_rejected(self):
        f = self.fixture
        release = f.bundle / "Release"
        original = release.read_bytes()
        release.write_bytes(original.replace(b"Origin: Ubuntu\n", b"Origin: Ubuntu\nValid-Until: Tue, 02 Jan 2024 00:00:00 +0000\n"))
        with self.assertRaisesRegex(native.Invalid, "Expired repository metadata"):
            f.validate()
        self.reject()
        release.write_bytes(original.replace(b"Components: main", b"Components: restricted"))
        self.reject()

    def test_claimed_authentication_and_closure_flags_are_not_schema(self):
        self.fixture.document["authenticated"] = True
        self.fixture.document["dependency_complete"] = True
        self.reject()

    def test_preinspection_document_index_and_bundle_bounds(self):
        f = self.fixture
        with mock.patch.object(native, "MAX_JSON", 32), mock.patch.object(f.system, "builder") as builder:
            self.reject()
            builder.assert_not_called()
        with mock.patch.object(native, "MAX_INDEX", 32), mock.patch.object(native, "inspect_deb") as archive:
            self.reject()
            archive.assert_not_called()
        with mock.patch.object(native, "MAX_BUNDLE", 32):
            self.reject()
        with mock.patch.object(native, "MAX_PACKAGES", 1), mock.patch.object(native, "inspect_deb") as archive:
            self.reject()
            archive.assert_not_called()

    def test_index_package_version_cannot_disagree_with_archive(self):
        f = self.fixture
        packages = f.bundle / "Packages"
        original = packages.read_bytes()
        changed = original.replace(b"Version: 1\n", b"Version: 99\n", 1)
        self.assertNotEqual(original, changed)
        packages.write_bytes(changed)
        release = f.bundle / "Release"
        release.write_bytes(release.read_bytes().replace(native.digest(original).encode(), native.digest(changed).encode())
                            .replace((str(len(original)) + " main/binary-amd64/Packages").encode(),
                                     (str(len(changed)) + " main/binary-amd64/Packages").encode()))
        self.reject()

    def test_missing_exact_version_and_source_file_hash_rejected(self):
        f = self.fixture
        control = f.controls["runtime-dependency:amd64"]
        control["Version"] = ""
        f.refresh()
        self.reject()
        control["Version"] = "1"
        f.refresh()
        f.source_files[0].write_bytes(b"changed source material")
        self.reject()

    def test_changed_installed_metadata_at_final_recheck_blocks_publication(self):
        original = self.fixture.system.installed
        calls = {}
        def changed(package_id):
            result = original(package_id)
            calls[package_id] = calls.get(package_id, 0) + 1
            if calls[package_id] > 1:
                result["Version"] = "99"
            return result
        with mock.patch.object(self.fixture.system, "installed", side_effect=changed):
            self.reject()

    def test_bundle_cannot_supply_trusted_keyring(self):
        self.fixture.keyring = self.fixture.bundle / "Release.gpg"
        self.reject()

    def test_changed_g1_report_and_wheel(self):
        f = self.fixture
        original = f.report_path.read_bytes()
        f.report_path.write_bytes(original + b" ")
        self.reject()
        f.report_path.write_bytes(original)
        wheel = f.bundle / f.document["g1"]["wheels"]["pycairo"]
        wheel.write_bytes(b"different wheel")
        self.reject()

    def test_g1_recording_loss_remains_rejected(self):
        trace = self.fixture.bundle / self.fixture.document["g1"]["trace"]
        Path(str(trace) + ".pending", "unfinished").touch()
        self.reject()

    def test_cpython_and_project_resources_match_independent_inputs(self):
        f = self.fixture
        f.library.write_bytes(b"changed CPython library")
        self.reject()
        f.library.write_bytes(b"trusted interpreter library fixture")
        resource = next(iter(native.PROJECT_RESOURCES))
        f.committed[resource] = b"different commit"
        self.reject()

    def test_missing_required_resource_role(self):
        self.fixture.package("fonts-dejavu-core")["consumed"][0]["role"] = "dependency"
        self.reject()

    def test_unsupported_transformations_and_host_classification(self):
        use = self.fixture.package("fonts-dejavu-core")["consumed"][0]
        use["transformation"] = "trust-me"
        self.reject()
        use["transformation"] = "identity"
        self.fixture.package("fonts-dejavu-core")["classification"] = "declared-host"
        self.reject()

    def test_unsafe_bundle_paths_and_json_duplicates(self):
        with self.assertRaises(native.Invalid):
            native.json_data(b'{"schema_version":1,"schema_version":1}')
        for path in ("../Release", "/Release", "a\\b", "a//b"):
            with self.subTest(path=path):
                self.fixture.document["repositories"][0]["release"] = path
                self.reject()

    def test_symlinked_bundle_input_rejected(self):
        f = self.fixture
        (f.bundle / "alias").symlink_to(f.bundle / "Release")
        f.document["repositories"][0]["release"] = "alias"
        self.reject()

    def test_tar_traversal_links_and_concatenation(self):
        bad_link = tarfile.TarInfo("link")
        bad_link.type, bad_link.linkname = tarfile.SYMTYPE, "../../escape"
        directory_link = tarfile.TarInfo("dir")
        directory_link.type, directory_link.linkname = tarfile.SYMTYPE, "other"
        for data in (tar_bytes({"../escape": b"x"}), tar_bytes({}, [bad_link]),
                     tar_bytes({"dir/file": b"x"}, [directory_link]),
                     tar_bytes({"one": b"x"}) + tar_bytes({"two": b"x"})):
            with self.subTest(length=len(data)), self.assertRaises(native.Invalid):
                native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_package_absolute_links_are_root_relative_not_host_reads(self):
        link = tarfile.TarInfo("lib64/loader.so")
        link.type, link.linkname = tarfile.SYMTYPE, "/lib/loader.so"
        data = tar_bytes({"lib/loader.so": b"archive bytes, no host read"}, [link])
        members, _ = native.inspect_tar(io.BytesIO(data), native.Budget(), allow_absolute_links=True)
        self.assertEqual(native.payload_file(members, "lib64/loader.so")["sha256"],
                         native.digest(b"archive bytes, no host read"))
        with self.assertRaises(native.Invalid):
            native.inspect_tar(io.BytesIO(data), native.Budget())
        link.linkname = "/../../escape"
        with self.assertRaises(native.Invalid):
            native.inspect_tar(io.BytesIO(tar_bytes({}, [link])), native.Budget(), allow_absolute_links=True)

    def test_tar_truncation_and_duplicate_members(self):
        data = tar_bytes({"one": b"x"})
        duplicate = tarfile.TarInfo("one")
        duplicate.type = tarfile.DIRTYPE
        for bad in (data[:513], data[:1024], tar_bytes({"one": b"x"}, [duplicate])):
            with self.subTest(length=len(bad)), self.assertRaises((native.Invalid, tarfile.TarError)):
                native.inspect_tar(io.BytesIO(bad), native.Budget())

    def test_extended_header_limits_before_decode(self):
        data = tar_bytes({"one": b"x"}, format=tarfile.PAX_FORMAT, pax_headers={"comment": "x" * 2048})
        with mock.patch.object(native, "MAX_METADATA", 128), self.assertRaises(native.Invalid):
            native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_regression_gnu_sparse_rejected_before_extension_parser(self):
        header = tarfile.TarInfo("sparse")
        header.type = tarfile.GNUTYPE_SPARSE
        raw = bytearray(header.tobuf(format=tarfile.GNU_FORMAT))
        raw[482] = 1
        raw[148:156] = b" " * 8
        raw[148:156] = ("%06o\0 " % sum(raw)).encode()
        data = bytes(raw) + b"\0" * 1536
        with mock.patch.object(native, "MAX_METADATA", 32), mock.patch.object(native, "MAX_MEMBERS", 1):
            with mock.patch.object(tarfile.TarInfo, "_proc_sparse", side_effect=AssertionError("sparse parser reached")):
                with self.assertRaises(native.Invalid):
                    native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_regression_empty_pax_sparse_rejected_before_map_parser(self):
        data = tar_bytes({"hole": b"0\n" + b"\0" * 510}, format=tarfile.PAX_FORMAT,
                         pax_headers={"GNU.sparse.major": "1", "GNU.sparse.minor": "0", "GNU.sparse.realsize": "8"})
        with mock.patch.object(tarfile.TarInfo, "_proc_gnusparse_10", side_effect=AssertionError("sparse map reached")):
            with self.assertRaises(native.Invalid):
                native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_pax_sparse_markers_rejected_before_internal_decode(self):
        markers = {"GNU.sparse.map": "", "GNU.sparse.numblocks": "0",
                   "GNU.sparse.size": "8", "GNU.sparse.name": "hole",
                   "SCHILY.realsize": "8", "SCHILY.holesdata": "",
                   "SCHILY.filetype": "sparse"}
        for key, value in markers.items():
            for local in (False, True):
                with self.subTest(key=key, local=local):
                    if local:
                        header = tarfile.TarInfo("hole")
                        header.pax_headers = {key: value}
                        data = tar_bytes({}, [header], format=tarfile.PAX_FORMAT)
                    else:
                        data = tar_bytes({"hole": b""}, format=tarfile.PAX_FORMAT, pax_headers={key: value})
                    with mock.patch.object(tarfile.TarInfo, "_proc_pax", side_effect=AssertionError("PAX decoder reached")):
                        with self.assertRaises(native.Invalid):
                            native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_ordinary_pax_and_record_limit_before_decode(self):
        header = tarfile.TarInfo("long-name")
        header.pax_headers = {"path": "ordinary-file", "comment": "ordinary metadata"}
        data = tar_bytes({}, [header], format=tarfile.PAX_FORMAT, pax_headers={"uname": "builder"})
        members, _ = native.inspect_tar(io.BytesIO(data), native.Budget())
        self.assertEqual(members["ordinary-file"]["size"], 0)
        data = tar_bytes({"one": b"x"}, format=tarfile.PAX_FORMAT,
                         pax_headers={"comment": "a", "uname": "b"})
        with mock.patch.object(native, "MAX_RECORDS", 1):
            with mock.patch.object(tarfile.TarInfo, "_proc_pax", side_effect=AssertionError("PAX decoder reached")):
                with self.assertRaises(native.Invalid):
                    native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_malformed_pax_length_rejected_before_decode(self):
        data = bytearray(tar_bytes({"one": b"x"}, format=tarfile.PAX_FORMAT, pax_headers={"comment": "a"}))
        data[512:514] = b"99"
        with mock.patch.object(tarfile.TarInfo, "_proc_pax", side_effect=AssertionError("PAX decoder reached")):
            with self.assertRaises(native.Invalid):
                native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_regression_control_records_do_not_eagerly_split(self):
        class NoSplit(str):
            def splitlines(self, *args, **kwargs):
                raise AssertionError("entire index enumerated")
        class Content(bytes):
            def decode(self, *args, **kwargs):
                return NoSplit(super().decode(*args, **kwargs))
        with mock.patch.object(native, "MAX_RECORDS", 1), self.assertRaises(native.Invalid):
            native.deb822(Content(b"Package: aa\n\n" * 100))

    def test_control_continuations_crlf_and_final_record(self):
        expected = [{"Package": "aa", "Description": "first\nsecond\n.\nthird"}, {"Package": "bb"}]
        content = b"Package: aa\nDescription: first\n second\n .\n\tthird\n\nPackage: bb"
        self.assertEqual(native.deb822(content), expected)
        self.assertEqual(native.deb822(content.replace(b"\n", b"\r\n") + b"\r\n"), expected)
        self.assertEqual(native.deb822(b"\n\n"), [])
        with mock.patch.object(native, "MAX_METADATA", 6):
            self.assertEqual(native.deb822(b"A: x\r\n"), [{"A": "x"}])
        with mock.patch.object(native, "MAX_METADATA", 5), self.assertRaises(native.Invalid):
            native.deb822(b"A: x\r\n")

    def test_control_limits_precede_slicing_or_later_records(self):
        slices = []
        class Watched(bytes):
            def __getitem__(self, key):
                if isinstance(key, slice):
                    slices.append((key.start, key.stop))
                return super().__getitem__(key)
        with mock.patch.object(native, "MAX_METADATA", 16):
            with self.assertRaises(native.Invalid):
                native.deb822(Watched(b"Field: " + b"x" * 100))
            self.assertEqual(slices, [])
            with self.assertRaises(native.Invalid):
                native.deb822(b"Field: abcdef\n xyz\n")
            with self.assertRaises(native.Invalid):
                native.deb822("Field: ééééé\n".encode())
        with mock.patch.object(native, "MAX_RECORDS", 1), self.assertRaises(native.Invalid):
            native.deb822(Watched(b"Package: aa\n\n" * 100))
        self.assertLessEqual(max(end for _, end in slices), 24)
        slices.clear()
        with mock.patch.object(native, "MAX_INDEX", 8), self.assertRaises(native.Invalid):
            native.deb822(Watched(b"Package: aa\n"))
        self.assertEqual(slices, [])
        with self.assertRaises(native.Invalid):
            native.deb822(b"".join(f"Field{i}: x\n".encode() for i in range(257)))

    def test_regression_large_json_value_rejected_before_encoding(self):
        encode = json.encoder.encode_basestring_ascii
        seen = []
        def observe(value):
            seen.append(len(value))
            return encode(value)
        with mock.patch.object(native, "MAX_JSON", 32), mock.patch.object(json.encoder, "encode_basestring_ascii", side_effect=observe):
            with self.assertRaises(native.Invalid):
                native.publish(self.fixture.output, {"data": "x" * 2048})
        self.assertFalse(self.fixture.output.exists())
        self.assertEqual(list(self.fixture.root.glob(".lmt-native-*")), [])
        self.assertNotIn(2048, seen)

    def test_json_exact_encoded_limit_and_deterministic_output(self):
        report = {"z": [True, None, 3, 1.5], "escaped": '"\\\n\x01éU0001f680'}
        expected = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
        with mock.patch.object(native, "MAX_JSON", len(expected)):
            native.publish(self.fixture.output, report)
        self.assertEqual(self.fixture.output.read_bytes(), expected)
        self.fixture.output.unlink()
        with mock.patch.object(native, "MAX_JSON", len(expected) - 1), self.assertRaises(native.Invalid):
            native.publish(self.fixture.output, report)
        self.assertFalse(self.fixture.output.exists())
        self.assertEqual(list(self.fixture.root.glob(".lmt-native-*")), [])

    def test_json_escaping_and_large_keys_rejected_before_encoding(self):
        for report in ({"data": "\x01" * 8}, {"data": "é" * 8}, {"data": "U0001f680" * 4}, {"x" * 100: 1}):
            with self.subTest(report=report), mock.patch.object(native, "MAX_JSON", 32):
                with mock.patch.object(json.encoder, "encode_basestring_ascii", side_effect=AssertionError("value encoded")):
                    with self.assertRaises(native.Invalid):
                        native.publish(self.fixture.output, report)
            self.assertFalse(self.fixture.output.exists())
            self.assertEqual(list(self.fixture.root.glob(".lmt-native-*")), [])

    def test_json_stream_overflow_preserves_existing_evidence(self):
        report = {"items": [0] * 10}
        # Compact content fits; pretty-print whitespace crosses this limit.
        with mock.patch.object(native, "MAX_JSON", 48):
            native.check_json_size(report)
            self.fixture.output.write_bytes(b"existing evidence")
            with self.assertRaises(native.Invalid):
                native.publish(self.fixture.output, report)
        self.assertEqual(self.fixture.output.read_bytes(), b"existing evidence")
        self.assertEqual(list(self.fixture.root.glob(".lmt-native-*")), [])

    def test_member_and_file_limits(self):
        data = tar_bytes({"one": b"x", "two": b"xx"})
        with mock.patch.object(native, "MAX_MEMBERS", 1), self.assertRaises(native.Invalid):
            native.inspect_tar(io.BytesIO(data), native.Budget())
        with mock.patch.object(native, "MAX_FILE", 1), self.assertRaises(native.Invalid):
            native.inspect_tar(io.BytesIO(data), native.Budget())

    def test_source_expansion_is_bounded_before_tar_parser(self):
        path = self.fixture.root / "bomb.tar.gz"
        path.write_bytes(gzip.compress(b"\0" * 8192))
        budget = native.Budget()
        with mock.patch.object(native, "MAX_STREAM", 1024), mock.patch.object(native, "inspect_tar") as inspect:
            with self.assertRaises(native.Invalid):
                native.inspect_source(path, budget, native.System(budget))
            inspect.assert_not_called()

    def test_external_producer_failure_timeout_and_output_bound(self):
        system = native.System(native.Budget())
        commands = [[sys.executable, "-I", "-B", "-c", "raise SystemExit(23)"],
                    [sys.executable, "-I", "-B", "-c", "print('x'*2048)"]]
        for command in commands:
            with self.subTest(command=command), self.assertRaises(native.Invalid):
                system.run(command, limit=1024)
        with mock.patch.object(native, "COMMAND_SECONDS", 0.1), self.assertRaises(native.Invalid):
            system.run([sys.executable, "-I", "-B", "-c", "import time; time.sleep(5)"])

    def test_real_archive_producer_rejects_malformed_deb(self):
        path = self.fixture.root / "broken.deb"
        path.write_bytes(b"!<arch>\ntruncated")
        with self.assertRaises(native.Invalid):
            native.inspect_deb(path, native.System(native.Budget()), native.Budget())

    def test_failed_producer_cannot_publish(self):
        with mock.patch.object(self.fixture.system, "installed", side_effect=native.Invalid("producer failed")):
            self.reject()

    def test_preserves_existing_output_and_publish_failure(self):
        f = self.fixture
        f.output.write_bytes(b"existing evidence")
        with mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(f.cli(), 1)
        self.assertEqual(f.output.read_bytes(), b"existing evidence")
        with self.assertRaises(FileExistsError):
            native.publish(f.output, {"new": True})
        f.output.unlink()
        with mock.patch.object(native.os, "fsync", side_effect=OSError("disk failed")), self.assertRaises(OSError):
            native.publish(f.output, {"new": True})
        self.assertFalse(f.output.exists())
        self.assertEqual(list(f.root.glob(".lmt-native-*")), [])


if __name__ == "__main__":
    unittest.main()
