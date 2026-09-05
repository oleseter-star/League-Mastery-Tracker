"""Run isolated runtime acceptance against a built Linux onefile executable."""

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


LOOPBACK_HOST = "127.0.0.1"
APPLICATION_PORT = 5000
APPLICATION_URL = f"http://{LOOPBACK_HOST}:{APPLICATION_PORT}"
READY_TIMEOUT_SECONDS = 20.0
PROCESS_EXIT_TIMEOUT_SECONDS = 12.0
POLL_INTERVAL_SECONDS = 0.1
MAX_DIAGNOSTIC_BYTES = 4096
MAX_DIAGNOSTIC_LINES = 12
MAX_CHILD_LOG_BYTES = 8192
PERSON_NAME = "Linux Onefile Runtime Person"
CHAMPION_IMAGE_PATH = "/champions/images/Annie.png"


class RuntimeAcceptanceError(RuntimeError):
    """Raised when isolated executable acceptance cannot be proved."""


@dataclass(frozen=True)
class RuntimeLayout:
    """Paths used exclusively by one isolated executable acceptance run."""

    root: Path
    program: Path
    working: Path
    home: Path
    xdg_data: Path
    xdg_runtime: Path
    xdg_config: Path
    xdg_cache: Path
    temporary: Path
    executable: Path
    browser_handler: Path
    process_log: Path


@dataclass(frozen=True)
class HttpResponse:
    """One local HTTP response and its decoded metadata."""

    status: int
    headers: dict
    body: bytes


class LocalHttpSession:
    """Minimal cookie-aware HTTP client for the loopback application."""

    def __init__(self, host=LOOPBACK_HOST, port=APPLICATION_PORT):
        self.host = host
        self.port = port
        self.cookies = {}

    def request(self, method, path, body=None, headers=None):
        if not path.startswith("/"):
            raise RuntimeAcceptanceError("Local request path is invalid.")

        request_headers = dict(headers or {})

        if self.cookies:
            request_headers["Cookie"] = "; ".join(
                f"{name}={value}"
                for name, value in sorted(self.cookies.items())
            )

        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=2.0,
        )

        try:
            connection.request(
                method,
                path,
                body=body,
                headers=request_headers,
            )
            response = connection.getresponse()
            response_headers = {
                key.lower(): value
                for key, value in response.getheaders()
            }
            set_cookie_headers = [
                value
                for key, value in response.getheaders()
                if key.lower() == "set-cookie"
            ]
            response_body = response.read()
        finally:
            connection.close()

        for set_cookie in set_cookie_headers:
            name_value = set_cookie.split(";", 1)[0]

            if "=" not in name_value:
                continue

            name, value = name_value.split("=", 1)
            self.cookies[name] = value

        return HttpResponse(
            status=response.status,
            headers=response_headers,
            body=response_body,
        )


class _ProxyRequestHandler(socketserver.BaseRequestHandler):
    """Record proxy traffic while refusing every forwarded request."""

    def handle(self):
        self.server.request_count += 1
        self.request.recv(4096)
        self.request.sendall(
            b"HTTP/1.1 502 Runtime acceptance proxy\r\n"
            b"Content-Length: 0\r\n"
            b"Connection: close\r\n\r\n"
        )


class ProxySentinel:
    """A loopback-only proxy listener that detects outbound requests."""

    def __init__(self):
        self.server = socketserver.ThreadingTCPServer(
            (LOOPBACK_HOST, 0),
            _ProxyRequestHandler,
        )
        self.server.daemon_threads = True
        self.server.request_count = 0
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        return False


def parse_arguments(arguments=None):
    """Parse explicit paths required for one isolated acceptance run."""

    parser = argparse.ArgumentParser(
        description=(
            "Verify the built Linux onefile executable outside the "
            "repository."
        )
    )
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--temporary-root", required=True, type=Path)
    return parser.parse_args(arguments)


def _resolve(path):
    return Path(path).expanduser().resolve(strict=False)


def _is_within(path, parent):
    return path == parent or parent in path.parents


def validate_paths(executable, repository_root, temporary_root):
    """Validate immutable input and reject repository-contained runtime roots."""

    executable = _resolve(executable)
    repository_root = _resolve(repository_root)
    temporary_root = _resolve(temporary_root)

    if not repository_root.is_dir():
        raise RuntimeAcceptanceError("Repository root is not a directory.")

    if executable.is_symlink() or not executable.is_file():
        raise RuntimeAcceptanceError("Built executable is not a regular file.")

    if not os.access(executable, os.X_OK):
        raise RuntimeAcceptanceError("Built executable is not executable.")

    if _is_within(temporary_root, repository_root):
        raise RuntimeAcceptanceError(
            "Runtime temporary root must be outside the repository."
        )

    if temporary_root.exists():
        raise RuntimeAcceptanceError("Runtime temporary root must not exist.")

    return executable, repository_root, temporary_root


def create_runtime_layout(executable, temporary_root):
    """Create an owner-only runtime layout below one approved temporary root."""

    temporary_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(temporary_root, 0o700)

    program = temporary_root / "program"
    working = temporary_root / "working"
    home = temporary_root / "home"
    xdg_data = temporary_root / "xdg-data"
    xdg_runtime = temporary_root / "xdg-runtime"
    xdg_config = temporary_root / "xdg-config"
    xdg_cache = temporary_root / "xdg-cache"
    temporary = temporary_root / "tmp"

    for directory in (
        program,
        working,
        home,
        xdg_data,
        xdg_runtime,
        xdg_config,
        xdg_cache,
        temporary,
    ):
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)

    executable_copy = program / executable.name
    shutil.copy2(executable, executable_copy)
    os.chmod(
        executable_copy,
        stat.S_IMODE(executable.stat().st_mode),
    )

    browser_handler = temporary_root / "browser-handler.sh"
    browser_handler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(browser_handler, 0o700)

    return RuntimeLayout(
        root=temporary_root,
        program=program,
        working=working,
        home=home,
        xdg_data=xdg_data,
        xdg_runtime=xdg_runtime,
        xdg_config=xdg_config,
        xdg_cache=xdg_cache,
        temporary=temporary,
        executable=executable_copy,
        browser_handler=browser_handler,
        process_log=temporary_root / "application.log",
    )


def build_child_environment(layout, proxy_url):
    """Build a headless, trayless, proxy-observed child environment."""

    environment = os.environ.copy()

    for variable_name in (
        "RIOT_API_KEY",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "PYTHONPATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        environment.pop(variable_name, None)

    environment.update(
        {
            "HOME": str(layout.home),
            "XDG_DATA_HOME": str(layout.xdg_data),
            "XDG_RUNTIME_DIR": str(layout.xdg_runtime),
            "XDG_CONFIG_HOME": str(layout.xdg_config),
            "XDG_CACHE_HOME": str(layout.xdg_cache),
            "TMPDIR": str(layout.temporary),
            "TMP": str(layout.temporary),
            "TEMP": str(layout.temporary),
            "PYSTRAY_BACKEND": "dummy",
            "BROWSER": str(layout.browser_handler),
            "HTTP_PROXY": proxy_url,
            "HTTPS_PROXY": proxy_url,
            "http_proxy": proxy_url,
            "https_proxy": proxy_url,
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )

    return environment


def snapshot_file(file_path):
    """Return immutable content and mode metadata for one regular file."""

    digest = hashlib.sha256()

    with Path(file_path).open("rb") as file_stream:
        for block in iter(lambda: file_stream.read(65536), b""):
            digest.update(block)

    metadata = Path(file_path).stat()
    return (
        digest.hexdigest(),
        metadata.st_size,
        stat.S_IMODE(metadata.st_mode),
    )


def snapshot_tree(root, excluded_directories=()):
    """Hash a source tree without descending into explicit excluded roots."""

    root = Path(root)
    excluded = set(excluded_directories)
    snapshot = {}

    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)

        if relative_path.parts and relative_path.parts[0] in excluded:
            continue

        if path.is_file():
            snapshot[relative_path.as_posix()] = snapshot_file(path)

    return snapshot


def launch_executable(layout, environment, log_name="application.log"):
    """Launch the copied executable in its own process group."""

    stdout_log, stderr_log = _child_log_paths(layout, log_name)
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()

    try:
        process = subprocess.Popen(
            [str(layout.executable)],
            cwd=str(layout.working),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_write,
            stderr=stderr_write,
            start_new_session=True,
        )
    except BaseException:
        os.close(stdout_read)
        os.close(stderr_read)
        raise
    finally:
        os.close(stdout_write)
        os.close(stderr_write)

    captures = (
        _BoundedLogCapture(stdout_log),
        _BoundedLogCapture(stderr_log),
    )
    threads = (
        _start_log_capture(captures[0], stdout_read),
        _start_log_capture(captures[1], stderr_read),
    )
    process._child_log_threads = threads
    return process


def _child_log_paths(layout, log_name):
    log_stem = Path(log_name).stem
    return (
        layout.temporary / f"{log_stem}.stdout.log",
        layout.temporary / f"{log_stem}.stderr.log",
    )


class _BoundedLogCapture:
    """Retain only the deterministic final bytes from one child stream."""

    def __init__(self, log_path):
        self.log_path = log_path
        self.lock = threading.Lock()
        self.tail = bytearray()

    def append(self, output):
        with self.lock:
            self.tail.extend(output)

            if len(self.tail) > MAX_CHILD_LOG_BYTES:
                del self.tail[:-MAX_CHILD_LOG_BYTES]

            self.log_path.write_bytes(self.tail)


def _start_log_capture(capture, file_descriptor):
    thread = threading.Thread(
        target=_capture_child_stream,
        args=(capture, file_descriptor),
        daemon=True,
    )
    thread.start()
    return thread


def _capture_child_stream(capture, file_descriptor):
    with os.fdopen(file_descriptor, "rb", closefd=True) as stream:
        while output := stream.read(1024):
            capture.append(output)


def _read_child_log_tail(log_path, repository_root, layout):
    try:
        with log_path.open("rb") as log_stream:
            log_stream.seek(0, os.SEEK_END)
            byte_count = log_stream.tell()
            log_stream.seek(max(0, byte_count - MAX_DIAGNOSTIC_BYTES))
            output = log_stream.read(MAX_DIAGNOSTIC_BYTES)
    except OSError:
        return "<unavailable>"

    text = output.decode("utf-8", errors="replace")
    text = _sanitize_child_diagnostic_text(
        text,
        repository_root,
        layout,
    )
    rendered_tail = _limit_rendered_child_tail(text)

    if not rendered_tail:
        return "<empty>"

    return rendered_tail


def _limit_rendered_child_tail(text):
    """Keep the final diagnostic text within its rendered UTF-8 budget."""

    rendered_tail = "\n".join(
        text.splitlines()[-MAX_DIAGNOSTIC_LINES:]
    )
    encoded_tail = rendered_tail.encode("utf-8")

    if len(encoded_tail) <= MAX_DIAGNOSTIC_BYTES:
        return rendered_tail

    return encoded_tail[-MAX_DIAGNOSTIC_BYTES:].decode(
        "utf-8",
        errors="ignore",
    )


def _sanitize_child_diagnostic_text(text, repository_root, layout):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character
        if character == "\n" or character.isprintable()
        else "?"
        for character in text
    )

    for path, placeholder in (
        (_resolve(layout.root), "<isolated-root>"),
        (_resolve(repository_root), "<repository-root>"),
    ):
        text = text.replace(str(path), placeholder)

    text = text.replace(PERSON_NAME, "<redacted>")
    return re.sub(
        r"(?i)\b(?:"
        r"(?:riot[_ -]?api[_ -]?key|api[_ -]?key|csrf[_ -]?token|"
        r"session(?:id)?|cookie|password|secret)\s*[:=]\s*[^\s,;]+"
        r"|(?:authorization\s*:\s*)?bearer\s+[^\s,;]+"
        r")",
        "<redacted>",
        text,
    )


def _child_diagnostics(repository_root, layout, log_name):
    stdout_log, stderr_log = _child_log_paths(layout, log_name)
    return "\n".join(
        (
            "stdout tail:",
            _read_child_log_tail(stdout_log, repository_root, layout),
            "stderr tail:",
            _read_child_log_tail(stderr_log, repository_root, layout),
        )
    )


def _cleanup_child_logs(layout):
    for log_path in layout.temporary.glob("*.log"):
        if log_path.is_file():
            log_path.unlink()


def _join_child_loggers(process):
    for thread in getattr(process, "_child_log_threads", ()):
        thread.join(timeout=1.0)


def terminate_process_group(process, timeout_seconds=3.0):
    """Terminate and reap every process in one started process group."""

    try:
        if process.poll() is not None:
            process.wait(timeout=timeout_seconds)
            return

        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

        try:
            process.wait(timeout=timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        process.wait(timeout=timeout_seconds)
    finally:
        _join_child_loggers(process)


def wait_for_exit(process, timeout_seconds=PROCESS_EXIT_TIMEOUT_SECONDS):
    """Wait under a monotonic deadline and require a clean executable exit."""

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        return_code = process.poll()

        if return_code is not None:
            if return_code != 0:
                raise RuntimeAcceptanceError(
                    "Executable exited with a non-zero status."
                )

            _join_child_loggers(process)
            return

        time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeAcceptanceError("Executable did not exit before the deadline.")


def wait_for_ready(
    process,
    session,
    repository_root,
    layout,
    log_name="application.log",
    timeout_seconds=READY_TIMEOUT_SECONDS,
):
    """Poll the documented loopback endpoint under a bounded deadline."""

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        return_code = process.poll()

        if return_code is not None:
            _join_child_loggers(process)
            raise RuntimeAcceptanceError(
                "Executable exited before loopback readiness "
                f"(exit code {return_code}).\n"
                + _child_diagnostics(
                    repository_root,
                    layout,
                    log_name,
                )
            )

        try:
            response = session.request("GET", "/")
        except (ConnectionError, OSError, http.client.HTTPException):
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if 100 <= response.status < 500:
            return response

        time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeAcceptanceError(
        "Loopback readiness timeout: process still running at deadline; "
        f"expected loopback {LOOPBACK_HOST}:{APPLICATION_PORT}.\n"
        + _child_diagnostics(repository_root, layout, log_name)
    )


def _html_response(response):
    content_type = response.headers.get("content-type", "")

    if "text/html" not in content_type:
        raise RuntimeAcceptanceError("Expected an HTML response.")

    return response.body.decode("utf-8", errors="replace")


def extract_csrf_token(html):
    """Extract the existing form or lifecycle CSRF token from rendered HTML."""

    patterns = (
        r'name="_csrf_token"\s+value="([^"]+)"',
        r'data-csrf-token="([^"]+)"',
    )

    for pattern in patterns:
        match = re.search(pattern, html)

        if match:
            return match.group(1)

    raise RuntimeAcceptanceError("Rendered HTML did not expose a CSRF token.")


def discover_asset_paths(html):
    """Discover actual local static paths rendered by the application."""

    return tuple(
        path
        for path in re.findall(r'(?:href|src)="([^"]+)"', html)
        if path.startswith("/")
    )


def _require_asset(session, path, expected_content_type):
    response = session.request("GET", path)

    if response.status != 200:
        raise RuntimeAcceptanceError("A rendered local asset was unavailable.")

    content_type = response.headers.get("content-type", "")

    if expected_content_type not in content_type:
        raise RuntimeAcceptanceError("A local asset had an unexpected content type.")


def verify_rendered_assets(session, home_html):
    """Fetch CSS, JavaScript, favicon, and bundled champion image assets."""

    asset_paths = discover_asset_paths(home_html)

    css_path = next(
        (path for path in asset_paths if path.endswith(".css")),
        None,
    )
    javascript_path = next(
        (path for path in asset_paths if path.endswith(".js")),
        None,
    )
    icon_path = next(
        (path for path in asset_paths if "favicon" in path),
        None,
    )

    if not all((css_path, javascript_path, icon_path)):
        raise RuntimeAcceptanceError("Rendered HTML omitted required local assets.")

    _require_asset(session, css_path, "text/css")
    _require_asset(session, javascript_path, "javascript")
    _require_asset(session, icon_path, "image/svg+xml")
    _require_asset(session, CHAMPION_IMAGE_PATH, "image/png")


def verify_home_page(response):
    """Validate documented local HTML, version, language, and bundled data state."""

    html = _html_response(response)

    for expected_text in (
        "League Mastery Tracker",
        "2.0.0",
        'html lang="en"',
        "The application is using the bundled dataset.",
    ):
        if expected_text not in html:
            raise RuntimeAcceptanceError("Core local HTML contract was missing.")

    return html


def create_person(session, csrf_token):
    """Create a local Person only through the documented JSON route."""

    request_body = json.dumps(
        {"display_name": PERSON_NAME}
    ).encode("utf-8")
    response = session.request(
        "POST",
        "/persons",
        body=request_body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(request_body)),
            "X-CSRF-Token": csrf_token,
        },
    )

    if response.status != 201:
        raise RuntimeAcceptanceError("Local Person creation was not accepted.")

    result = json.loads(response.body.decode("utf-8"))

    if result.get("person", {}).get("display_name") != PERSON_NAME:
        raise RuntimeAcceptanceError("Created Person response was invalid.")


def request_shutdown(session, csrf_token):
    """Request documented controlled shutdown with the real session token."""

    request_body = f"_csrf_token={csrf_token}".encode("utf-8")
    response = session.request(
        "POST",
        "/application/shutdown",
        body=request_body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(request_body)),
        },
    )

    if response.status != 202:
        raise RuntimeAcceptanceError("Controlled shutdown was not accepted.")

    if b"Application is shutting down" not in response.body:
        raise RuntimeAcceptanceError("Controlled shutdown response was invalid.")


def verify_persisted_person(session):
    """Confirm the locally created Person remains visible after restart."""

    response = session.request("GET", "/persons")

    if response.status != 200:
        raise RuntimeAcceptanceError("Persistent Person page was unavailable.")

    if PERSON_NAME.encode("utf-8") not in response.body:
        raise RuntimeAcceptanceError("Persistent Person data was unavailable.")


def assert_no_proxy_requests(proxy_sentinel):
    """Reject any startup request observed by the loopback proxy sentinel."""

    if proxy_sentinel.server.request_count:
        raise RuntimeAcceptanceError("Startup attempted an outbound request.")


def verify_second_instance(layout, environment, first_process):
    """Require the existing local single-instance lifecycle contract."""

    second_process = launch_executable(
        layout,
        environment,
        log_name="second-instance.log",
    )

    try:
        wait_for_exit(second_process, timeout_seconds=8.0)
    finally:
        terminate_process_group(second_process)

    if first_process.poll() is not None:
        raise RuntimeAcceptanceError("First executable stopped during second launch.")

    response = LocalHttpSession().request("GET", "/")

    if response.status != 200:
        raise RuntimeAcceptanceError("First loopback server became unhealthy.")


def verify_filesystem_containment(
    layout,
    source_executable,
    executable_snapshot,
):
    """Verify mutable state and onefile extraction remained inside isolation roots."""

    if list(layout.program.iterdir()) != [layout.executable]:
        raise RuntimeAcceptanceError("Program directory contains unexpected files.")

    if any(layout.working.iterdir()):
        raise RuntimeAcceptanceError("Working directory received mutable writes.")

    if any(layout.home.iterdir()):
        raise RuntimeAcceptanceError("Home directory received mutable writes.")

    if snapshot_file(layout.executable) != executable_snapshot:
        raise RuntimeAcceptanceError("Copied executable changed during acceptance.")

    if snapshot_file(source_executable) != executable_snapshot:
        raise RuntimeAcceptanceError("Built executable changed during acceptance.")

    if any(layout.temporary.rglob("_MEI*")):
        raise RuntimeAcceptanceError("Onefile extraction directory survived shutdown.")

    if not (layout.xdg_data / "LeagueMasteryTracker").is_dir():
        raise RuntimeAcceptanceError("Persistent application data was not isolated.")

    runtime_lock_files = tuple(layout.xdg_runtime.rglob("*.lock"))

    if not runtime_lock_files:
        raise RuntimeAcceptanceError("Expected runtime lock material was not isolated.")

    _reject_persistent_state_outside_xdg_data(layout)


def _reject_persistent_state_outside_xdg_data(layout):
    """Reject persistent application state outside its permitted data root."""

    persistent_directory_names = {
        "backup",
        "backups",
        "config",
        "configuration",
        "data",
        "database",
        "key",
        "keys",
        "staging",
    }
    persistent_suffixes = {".db", ".json", ".key", ".sqlite", ".sqlite3"}

    for root in (
        layout.program,
        layout.working,
        layout.home,
        layout.xdg_config,
        layout.xdg_cache,
        layout.xdg_runtime,
        layout.temporary,
    ):
        for path in root.rglob("*"):
            relative_path = path.relative_to(root)

            if (
                path.suffix.lower() in persistent_suffixes
                or any(
                    part.lower() in persistent_directory_names
                    for part in relative_path.parts
                )
            ):
                raise RuntimeAcceptanceError(
                    "Persistent application state escaped XDG data isolation."
                )


def _assert_repository_unchanged(repository_root, snapshot):
    current_snapshot = snapshot_tree(
        repository_root,
        excluded_directories=(".git", ".venv", "data", "build", "dist"),
    )

    if current_snapshot != snapshot:
        raise RuntimeAcceptanceError("Repository source changed during acceptance.")


def run_acceptance(executable, repository_root, temporary_root):
    """Run the complete isolated runtime acceptance lifecycle."""

    executable, repository_root, temporary_root = validate_paths(
        executable,
        repository_root,
        temporary_root,
    )
    repository_snapshot = snapshot_tree(
        repository_root,
        excluded_directories=(".git", ".venv", "data", "build", "dist"),
    )
    executable_snapshot = snapshot_file(executable)
    layout = create_runtime_layout(executable, temporary_root)
    first_process = None
    restarted_process = None

    try:
        with ProxySentinel() as proxy_sentinel:
            environment = build_child_environment(layout, proxy_sentinel.url)
            first_process = launch_executable(layout, environment)
            first_session = LocalHttpSession()
            home_html = verify_home_page(
                wait_for_ready(
                    first_process,
                    first_session,
                    repository_root,
                    layout,
                )
            )
            verify_rendered_assets(first_session, home_html)
            csrf_token = extract_csrf_token(home_html)
            create_person(first_session, csrf_token)
            verify_second_instance(layout, environment, first_process)
            request_shutdown(first_session, csrf_token)
            wait_for_exit(first_process)
            first_process = None

            restarted_process = launch_executable(
                layout,
                environment,
                log_name="restart.log",
            )
            restarted_session = LocalHttpSession()
            restarted_html = verify_home_page(
                wait_for_ready(
                    restarted_process,
                    restarted_session,
                    repository_root,
                    layout,
                    log_name="restart.log",
                )
            )

            verify_persisted_person(restarted_session)

            request_shutdown(
                restarted_session,
                extract_csrf_token(restarted_html),
            )
            wait_for_exit(restarted_process)
            restarted_process = None

            assert_no_proxy_requests(proxy_sentinel)

        verify_filesystem_containment(
            layout,
            executable,
            executable_snapshot,
        )
        _assert_repository_unchanged(repository_root, repository_snapshot)
    finally:
        for process in (first_process, restarted_process):
            if process is not None:
                terminate_process_group(process)

        _cleanup_child_logs(layout)

    return "Linux onefile runtime acceptance passed."


def _redact_failure(message, temporary_root):
    return str(message).replace(str(_resolve(temporary_root)), "<isolated-root>")


def main(arguments=None):
    """Run the CLI without performing work when the module is imported."""

    parsed_arguments = parse_arguments(arguments)

    try:
        summary = run_acceptance(
            executable=parsed_arguments.executable,
            repository_root=parsed_arguments.repository_root,
            temporary_root=parsed_arguments.temporary_root,
        )
    except RuntimeAcceptanceError as error:
        print(
            "Linux onefile runtime acceptance failed: "
            + _redact_failure(error, parsed_arguments.temporary_root),
            file=sys.stderr,
        )
        return 1

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
