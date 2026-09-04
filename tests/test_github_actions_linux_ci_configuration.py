import re
import unittest
from pathlib import Path


class GitHubActionsLinuxCiConfigurationTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.project_root = (
            Path(__file__)
            .resolve()
            .parent
            .parent
        )
        cls.workflow_file = (
            cls.project_root
            / ".github"
            / "workflows"
            / "linux-ci.yml"
        )
        cls.workflow_source = cls.workflow_file.read_text(
            encoding="utf-8"
        )

    def test_workflow_exists_with_safe_triggers(self):
        self.assertTrue(self.workflow_file.is_file())
        self.assertRegex(
            self.workflow_source,
            r"(?m)^on:\n",
        )
        self.assertIn("  push:\n", self.workflow_source)
        self.assertIn("      - linux-compatibility\n", self.workflow_source)
        self.assertIn("      - main\n", self.workflow_source)
        self.assertIn("  pull_request:\n", self.workflow_source)
        self.assertIn("  workflow_dispatch:\n", self.workflow_source)
        self.assertNotIn("pull_request_target", self.workflow_source)

    def test_permissions_and_concurrency_are_restricted(self):
        self.assertIn(
            "permissions:\n  contents: read\n",
            self.workflow_source,
        )
        self.assertIn(
            "group: ${{ github.workflow }}-${{ github.ref }}",
            self.workflow_source,
        )
        self.assertIn(
            "cancel-in-progress: true",
            self.workflow_source,
        )

    def test_exact_job_contract_uses_expected_runners(self):
        self.assertEqual(
            set(self._job_names()),
            {
                "ubuntu-tests",
                "windows-regression",
                "linux-onefile",
            },
        )
        self.assertIn("runs-on: ubuntu-22.04", self._job("ubuntu-tests"))
        self.assertIn(
            "runs-on: windows-2022",
            self._job("windows-regression"),
        )
        self.assertIn("runs-on: ubuntu-22.04", self._job("linux-onefile"))

    def test_all_jobs_use_python_312_and_required_environment(self):
        self.assertIn(
            'PYTHONDONTWRITEBYTECODE: "1"',
            self.workflow_source,
        )
        self.assertIn("PYSTRAY_BACKEND: dummy", self.workflow_source)
        self.assertIn(
            "PYTHONWARNINGS: error::ResourceWarning",
            self.workflow_source,
        )
        windows_job = self._job("windows-regression")
        self.assertNotRegex(
            windows_job,
            r"(?m)^    env:",
        )
        windows_unittest_step = self._step_named(
            windows_job,
            "Run full unittest suite",
        )
        self.assertRegex(
            windows_unittest_step,
            r"env:\n\s+TEMP: \$\{\{ runner\.temp \}\}\n"
            r"\s+TMP: \$\{\{ runner\.temp \}\}",
        )
        self.assertEqual(
            self.workflow_source.count("${{ runner.temp }}"),
            2,
        )
        for job_name in self._job_names():
            self.assertIn(
                "actions/setup-python@v5",
                self._job(job_name),
            )
            self.assertIn(
                'python-version: "3.12"',
                self._job(job_name),
            )

    def test_regression_jobs_run_documented_suite_and_audit(self):
        for job_name in ("ubuntu-tests", "windows-regression"):
            job_source = self._job(job_name)
            self.assertIn(
                "python -B -m unittest discover -s tests -v",
                job_source,
            )
            self.assertIn(
                "python -B audit_repository_language.py",
                job_source,
            )
            self.assertIn("-r requirements.txt", job_source)

    def test_linux_build_waits_for_both_regression_jobs(self):
        linux_job = self._job("linux-onefile")
        self.assertRegex(
            linux_job,
            r"needs:\n\s+- ubuntu-tests\n\s+- windows-regression",
        )

    def test_linux_build_targets_only_linux_spec(self):
        linux_job = self._job("linux-onefile")
        self.assertIn("-r requirements-build.txt", linux_job)
        self.assertIn(
            "python -m PyInstaller --clean --noconfirm "
            "LeagueMasteryTracker-linux-onefile.spec",
            linux_job,
        )
        self.assertNotIn(
            "LeagueMasteryTracker.spec",
            linux_job,
        )
        self.assertNotIn(
            "LeagueMasteryTracker-onefile.spec",
            linux_job,
        )

    def test_linux_builder_and_executable_contract(self):
        linux_job = self._job("linux-onefile")
        self.assertIn('test "$(uname -m)" = "x86_64"', linux_job)
        self.assertIn("ldd --version", linux_job)
        self.assertIn("2\\.35", linux_job)
        self.assertIn("test -f dist/LeagueMasteryTracker", linux_job)
        self.assertIn("test -x dist/LeagueMasteryTracker", linux_job)
        self.assertIn("test ! -e dist/LeagueMasteryTracker.exe", linux_job)
        self.assertIn("ELF 64-bit.*x86-64", linux_job)

    def test_checksum_and_artifact_contract(self):
        linux_job = self._job("linux-onefile")
        self.assertRegex(
            linux_job,
            r"working-directory: dist\n\s+run: sha256sum "
            r"LeagueMasteryTracker > LeagueMasteryTracker\.sha256",
        )
        self.assertIn("actions/upload-artifact@v4", linux_job)
        self.assertIn("name: LeagueMasteryTracker-linux-x86_64", linux_job)
        self.assertRegex(
            linux_job,
            r"path: \|\n\s+dist/LeagueMasteryTracker\n"
            r"\s+dist/LeagueMasteryTracker\.sha256",
        )
        self.assertIn("if-no-files-found: error", linux_job)

    def test_workflow_has_no_remote_or_unsafe_operations(self):
        for prohibited_text in (
            "secrets.",
            "contents: write",
            "pull_request_target",
            "continue-on-error",
            "curl ",
            "wget ",
            "sudo ",
            "git push",
            "git commit",
            "gh release",
            "docker ",
        ):
            self.assertNotIn(prohibited_text, self.workflow_source)

    def test_source_inspection_test_does_not_execute_workflow_tools(self):
        test_source = Path(__file__).read_text(encoding="utf-8")
        for prohibited_text in (
            "import " + "subprocess",
            "subprocess" + ".",
            "os" + ".system",
            "PyInstaller" + "(",
            "pip" + " install",
            "requests" + ".",
        ):
            self.assertNotIn(prohibited_text, test_source)

    def _job_names(self):
        jobs_source = self.workflow_source.split("jobs:\n", 1)[1]
        return re.findall(r"(?m)^  ([a-z][a-z-]+):\n", jobs_source)

    def _job(self, job_name):
        jobs_source = self.workflow_source.split("jobs:\n", 1)[1]
        match = re.search(
            rf"(?ms)^  {re.escape(job_name)}:\n(.*?)(?=^  [a-z][a-z-]+:\n|\Z)",
            jobs_source,
        )
        self.assertIsNotNone(match, msg=f"Missing job: {job_name}")
        return match.group(0)

    def _step_named(self, job_source, step_name):
        match = re.search(
            rf"(?ms)^      - name: {re.escape(step_name)}\n"
            r"(.*?)(?=^      - (?:name:|uses:)|\Z)",
            job_source,
        )
        self.assertIsNotNone(match, msg=f"Missing step: {step_name}")
        return match.group(0)


if __name__ == "__main__":
    unittest.main()
