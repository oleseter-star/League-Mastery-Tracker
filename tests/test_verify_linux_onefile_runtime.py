import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import verify_linux_onefile_runtime as runtime


class _FakeProcess:
    def __init__(self, return_code=None):
        self.return_code = return_code
        self.pid = 4321
        self.wait_calls = []

    def poll(self):
        return self.return_code

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self.return_code = 0
        return self.return_code


class _FakeConnection:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self.responses.pop(0)

    def close(self):
        return None


class _FakeHttpResponse:
    status = 200

    def getheaders(self):
        return [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Set-Cookie", "session=value; HttpOnly"),
        ]

    def read(self):
        return b"<html lang=\"en\"></html>"


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))
        return self.responses.pop(0)


class VerifyLinuxOnefileRuntimeTests(unittest.TestCase):
    def _create_executable(self, directory):
        executable = Path(directory) / "LeagueMasteryTracker"
        executable.write_bytes(b"onefile test executable")
        executable.chmod(0o700)
        return executable

    def test_cli_requires_explicit_runtime_paths(self):
        arguments = runtime.parse_arguments(
            [
                "--executable",
                "/tmp/executable",
                "--repository-root",
                "/tmp/repository",
                "--temporary-root",
                "/tmp/runtime",
            ]
        )

        self.assertEqual(arguments.executable, Path("/tmp/executable"))
        self.assertEqual(
            arguments.repository_root,
            Path("/tmp/repository"),
        )
        self.assertEqual(arguments.temporary_root, Path("/tmp/runtime"))

    def test_repository_contained_runtime_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = self._create_executable(root)

            with self.assertRaises(runtime.RuntimeAcceptanceError):
                runtime.validate_paths(
                    executable,
                    root,
                    root / "runtime",
                )

    def test_missing_or_non_executable_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "LeagueMasteryTracker"
            executable.write_bytes(b"not executable")

            with patch.object(
                runtime.os,
                "access",
                return_value=False,
            ) as executable_access:
                with self.assertRaises(runtime.RuntimeAcceptanceError):
                    runtime.validate_paths(
                        executable,
                        root,
                        root.parent / "runtime",
                    )

            executable_access.assert_called_once_with(
                executable.resolve(),
                runtime.os.X_OK,
            )

    def test_layout_is_isolated_and_runtime_directory_is_owner_only(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)

            with patch.object(runtime.os, "chmod") as set_permissions:
                layout = runtime.create_runtime_layout(
                    executable,
                    parent / "runtime",
                )

            self.assertEqual(list(layout.program.iterdir()), [layout.executable])
            self.assertEqual(layout.executable.read_bytes(), executable.read_bytes())
            set_permissions.assert_any_call(
                layout.xdg_runtime,
                0o700,
            )
            self.assertTrue(layout.working.is_dir())
            self.assertTrue(layout.xdg_data.is_dir())

    def test_child_environment_is_headless_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )

            with patch.dict(
                os.environ,
                {
                    "RIOT_API_KEY": "not-retained",
                    "DISPLAY": ":0",
                    "WAYLAND_DISPLAY": "wayland-0",
                },
                clear=False,
            ):
                environment = runtime.build_child_environment(
                    layout,
                    "http://127.0.0.1:8123",
                )

            self.assertNotIn("RIOT_API_KEY", environment)
            self.assertNotIn("DISPLAY", environment)
            self.assertNotIn("WAYLAND_DISPLAY", environment)
            self.assertEqual(environment["PYSTRAY_BACKEND"], "dummy")
            self.assertEqual(environment["HOME"], str(layout.home))
            self.assertEqual(environment["TMPDIR"], str(layout.temporary))
            self.assertEqual(environment["NO_PROXY"], "127.0.0.1,localhost")

    def test_harness_has_no_application_source_import(self):
        source = Path(runtime.__file__).read_text(encoding="utf-8")

        self.assertNotRegex(source, r"(?m)^\s*from\s+application")
        self.assertNotRegex(source, r"(?m)^\s*import\s+application")
        self.assertIn('if __name__ == "__main__"', source)

    def test_readiness_and_clean_exit_are_bounded(self):
        process = _FakeProcess()
        session = _FakeSession(
            [
                runtime.HttpResponse(
                    status=200,
                    headers={"content-type": "text/html"},
                    body=b"ready",
                )
            ]
        )

        response = runtime.wait_for_ready(
            process,
            session,
            Path("/repository"),
            MagicMock(),
            timeout_seconds=0.1,
        )

        self.assertEqual(response.status, 200)
        process.return_code = 0
        runtime.wait_for_exit(process, timeout_seconds=0.1)

    def test_process_group_cleanup_reaps_started_process(self):
        process = _FakeProcess()

        with patch.object(
            runtime.os,
            "killpg",
            create=True,
        ) as kill_process_group:
            runtime.terminate_process_group(process)

        kill_process_group.assert_called_once_with(
            process.pid,
            runtime.signal.SIGTERM,
        )
        self.assertEqual(process.return_code, 0)

    def test_early_exit_readiness_diagnostic_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )
            stdout_log, stderr_log = runtime._child_log_paths(
                layout,
                "application.log",
            )
            stdout_log.write_bytes(
                (
                    b"line\x00with invalid \xff bytes\n" * 1000
                    + b"RIOT_API_KEY=not-safe\r\n"
                    + str(parent).encode("utf-8")
                    + b"/source.py\n"
                    + str(layout.root).encode("utf-8")
                    + b"/application.log\n"
                )
            )
            stderr_log.write_text(
                "session=not-safe\n"
                "Authorization: Bearer not-safe\n"
                "Linux Onefile Runtime Person\n"
                "RuntimeError: useful failure\n",
                encoding="utf-8",
            )

            with self.assertRaises(runtime.RuntimeAcceptanceError) as raised:
                runtime.wait_for_ready(
                    _FakeProcess(return_code=17),
                    _FakeSession([]),
                    parent,
                    layout,
                )

            message = str(raised.exception)
            self.assertIn("exited before loopback readiness", message)
            self.assertIn("exit code 17", message)
            self.assertIn("RuntimeError: useful failure", message)
            self.assertIn("<repository-root>", message)
            self.assertIn("<isolated-root>", message)
            self.assertNotIn(str(parent), message)
            self.assertNotIn("not-safe", message)
            self.assertNotIn(runtime.PERSON_NAME, message)
            self.assertNotIn("\r", message)
            self.assertNotIn("\x00", message)
            self.assertLessEqual(len(message.encode("utf-8")), 2 * runtime.MAX_DIAGNOSTIC_BYTES)

    def test_alive_readiness_timeout_has_distinct_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )

            with self.assertRaises(runtime.RuntimeAcceptanceError) as raised:
                runtime.wait_for_ready(
                    _FakeProcess(),
                    _FakeSession([]),
                    parent,
                    layout,
                    timeout_seconds=0.0,
                )

            self.assertIn("process still running at deadline", str(raised.exception))
            self.assertIn("expected loopback 127.0.0.1:5000", str(raised.exception))

    def test_ready_process_does_not_read_child_diagnostics(self):
        process = _FakeProcess()
        session = _FakeSession(
            [runtime.HttpResponse(200, {"content-type": "text/html"}, b"ready")]
        )

        with patch.object(runtime, "_child_diagnostics") as diagnostics:
            runtime.wait_for_ready(
                process,
                session,
                Path("/repository"),
                MagicMock(),
                timeout_seconds=0.1,
            )

        diagnostics.assert_not_called()

    def test_child_diagnostic_logs_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )
            stdout_log, stderr_log = runtime._child_log_paths(
                layout,
                "application.log",
            )
            stdout_log.write_text("output", encoding="utf-8")
            stderr_log.write_text("failure", encoding="utf-8")

            runtime._cleanup_child_logs(layout)

            self.assertFalse(stdout_log.exists())
            self.assertFalse(stderr_log.exists())

    def test_child_log_capture_retains_only_bounded_tail(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / "child.log"
            capture = runtime._BoundedLogCapture(log_path)
            capture.append(b"discarded\n" * runtime.MAX_CHILD_LOG_BYTES)
            capture.append(b"final traceback line\n")

            self.assertLessEqual(
                log_path.stat().st_size,
                runtime.MAX_CHILD_LOG_BYTES,
            )
            self.assertIn(
                b"final traceback line",
                log_path.read_bytes(),
            )

    def test_long_malformed_diagnostic_tail_respects_rendered_budget(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )
            stdout_log, _ = runtime._child_log_paths(
                layout,
                "application.log",
            )
            stdout_log.write_bytes(
                b"\xff" * runtime.MAX_CHILD_LOG_BYTES
                + b" session=not-safe "
                + str(parent).encode("utf-8")
                + b" "
                + str(layout.root).encode("utf-8")
                + b" "
                + runtime.PERSON_NAME.encode("utf-8")
                + b" RuntimeError: final actionable tail"
            )

            rendered_tail = runtime._read_child_log_tail(
                stdout_log,
                parent,
                layout,
            )

            self.assertLessEqual(
                len(rendered_tail.encode("utf-8")),
                runtime.MAX_DIAGNOSTIC_BYTES,
            )
            self.assertEqual(
                rendered_tail.encode("utf-8").decode("utf-8"),
                rendered_tail,
            )
            self.assertTrue(rendered_tail.endswith("RuntimeError: final actionable tail"))
            self.assertLessEqual(
                len(rendered_tail.splitlines()),
                runtime.MAX_DIAGNOSTIC_LINES,
            )
            self.assertIn("<repository-root>", rendered_tail)
            self.assertIn("<isolated-root>", rendered_tail)
            self.assertNotIn("not-safe", rendered_tail)
            self.assertNotIn(str(parent), rendered_tail)
            self.assertNotIn(runtime.PERSON_NAME, rendered_tail)

    def test_rendered_tail_truncation_preserves_complete_unicode(self):
        rendered_tail = runtime._limit_rendered_child_tail(
            "X" + "€" * 1366
        )

        self.assertEqual(rendered_tail, "€" * 1365)
        self.assertLessEqual(
            len(rendered_tail.encode("utf-8")),
            runtime.MAX_DIAGNOSTIC_BYTES,
        )
        self.assertEqual(
            rendered_tail.encode("utf-8").decode("utf-8"),
            rendered_tail,
        )

    def test_acceptance_failure_terminates_started_process_group(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )
            process = _FakeProcess()
            proxy_sentinel = MagicMock()
            proxy_sentinel.url = "http://127.0.0.1:8123"
            proxy_sentinel.__enter__.return_value = proxy_sentinel

            with patch.object(
                runtime,
                "validate_paths",
                return_value=(executable, parent, parent / "requested-runtime"),
            ), patch.object(
                runtime,
                "snapshot_tree",
                return_value={},
            ), patch.object(
                runtime,
                "snapshot_file",
                return_value=("digest", 1, 0o700),
            ), patch.object(
                runtime,
                "create_runtime_layout",
                return_value=layout,
            ), patch.object(
                runtime,
                "ProxySentinel",
                return_value=proxy_sentinel,
            ), patch.object(
                runtime,
                "build_child_environment",
                return_value={},
            ), patch.object(
                runtime,
                "launch_executable",
                return_value=process,
            ), patch.object(
                runtime,
                "wait_for_ready",
                side_effect=runtime.RuntimeAcceptanceError("not ready"),
            ), patch.object(
                runtime,
                "terminate_process_group",
            ) as terminate_process_group:
                with self.assertRaises(runtime.RuntimeAcceptanceError):
                    runtime.run_acceptance(
                        executable,
                        parent,
                        parent / "requested-runtime",
                    )

            terminate_process_group.assert_called_once_with(process)

    def test_cookie_session_and_csrf_contract_are_supported(self):
        connection = _FakeConnection([_FakeHttpResponse()])

        with patch.object(
            runtime.http.client,
            "HTTPConnection",
            return_value=connection,
        ):
            session = runtime.LocalHttpSession()
            response = session.request("GET", "/")

        self.assertEqual(response.status, 200)
        self.assertEqual(session.cookies, {"session": "value"})
        self.assertEqual(
            runtime.extract_csrf_token(
                '<script data-csrf-token="token-value"></script>'
            ),
            "token-value",
        )

    def test_rendered_local_assets_require_expected_content_types(self):
        session = _FakeSession(
            [
                runtime.HttpResponse(200, {"content-type": "text/css"}, b""),
                runtime.HttpResponse(200, {"content-type": "application/javascript"}, b""),
                runtime.HttpResponse(200, {"content-type": "image/svg+xml"}, b""),
                runtime.HttpResponse(200, {"content-type": "image/png"}, b""),
            ]
        )
        html = (
            '<link href="/static/app.css">'
            '<script src="/static/application_tab_lifecycle.js"></script>'
            '<link href="/static/favicon.svg">'
        )

        runtime.verify_rendered_assets(session, html)

        self.assertEqual(
            [request[1] for request in session.requests],
            [
                "/static/app.css",
                "/static/application_tab_lifecycle.js",
                "/static/favicon.svg",
                runtime.CHAMPION_IMAGE_PATH,
            ],
        )

    def test_second_instance_contract_keeps_first_server_healthy(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )
            first_process = _FakeProcess()
            second_process = _FakeProcess(return_code=0)
            healthy_session = _FakeSession(
                [runtime.HttpResponse(200, {}, b"healthy")]
            )

            with patch.object(
                runtime,
                "launch_executable",
                return_value=second_process,
            ), patch.object(
                runtime,
                "LocalHttpSession",
                return_value=healthy_session,
            ):
                runtime.verify_second_instance(
                    layout,
                    {},
                    first_process,
                )

            self.assertIsNone(first_process.poll())

    def test_proxy_sentinel_detection_rejects_outbound_requests(self):
        proxy_sentinel = MagicMock()
        proxy_sentinel.server.request_count = 1

        with self.assertRaises(runtime.RuntimeAcceptanceError):
            runtime.assert_no_proxy_requests(proxy_sentinel)

    def test_filesystem_containment_and_persistence_marker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )
            (layout.xdg_data / "LeagueMasteryTracker").mkdir()
            (layout.xdg_runtime / "instance.lock").write_bytes(b"")
            executable_snapshot = runtime.snapshot_file(executable)

            runtime.verify_filesystem_containment(
                layout,
                executable,
                executable_snapshot,
            )

            (layout.xdg_config / "escaped.db").write_bytes(b"")

            with self.assertRaises(runtime.RuntimeAcceptanceError):
                runtime.verify_filesystem_containment(
                    layout,
                    executable,
                    executable_snapshot,
                )

        session = _FakeSession(
            [
                runtime.HttpResponse(
                    200,
                    {"content-type": "text/html"},
                    runtime.PERSON_NAME.encode("utf-8"),
                )
            ]
        )
        runtime.verify_persisted_person(session)

    def test_failure_output_is_concise_and_redacted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            failure_output = runtime._redact_failure(
                temporary_directory,
                temporary_directory,
            )

            self.assertIn("<isolated-root>", failure_output)
            self.assertNotIn(temporary_directory, failure_output)


if __name__ == "__main__":
    unittest.main()
