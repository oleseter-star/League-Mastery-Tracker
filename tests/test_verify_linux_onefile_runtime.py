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

            with self.assertRaises(runtime.RuntimeAcceptanceError):
                runtime.validate_paths(
                    executable,
                    root,
                    root.parent / "runtime",
                )

    def test_layout_is_isolated_and_runtime_directory_is_owner_only(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            parent = Path(temporary_directory)
            executable = self._create_executable(parent)
            layout = runtime.create_runtime_layout(
                executable,
                parent / "runtime",
            )

            self.assertEqual(list(layout.program.iterdir()), [layout.executable])
            self.assertEqual(layout.executable.read_bytes(), executable.read_bytes())
            self.assertEqual(
                stat.S_IMODE(layout.xdg_runtime.stat().st_mode),
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
            timeout_seconds=0.1,
        )

        self.assertEqual(response.status, 200)
        process.return_code = 0
        runtime.wait_for_exit(process, timeout_seconds=0.1)

    def test_process_group_cleanup_reaps_started_process(self):
        process = _FakeProcess()

        with patch.object(os, "killpg") as kill_process_group:
            runtime.terminate_process_group(process)

        kill_process_group.assert_called_once_with(
            process.pid,
            runtime.signal.SIGTERM,
        )
        self.assertEqual(process.return_code, 0)

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
