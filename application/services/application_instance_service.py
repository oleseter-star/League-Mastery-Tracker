import ctypes
import errno
import hashlib
import os
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path


class ApplicationInstanceError(OSError):
    """
    Raised when the application-instance lock cannot be created,
    released, or closed safely.
    """


class ApplicationInstanceService:
    """
    Prevents multiple League Mastery Tracker server processes from
    running simultaneously for the current user session.

    Windows uses a named local mutex. POSIX systems use a non-blocking
    advisory lock on a file in a per-user runtime directory. Both
    operating systems release the lock if the owning process exits.
    """

    DEFAULT_MUTEX_NAME = (
        "Local\\LeagueMasteryTracker."
        "ApplicationInstance"
    )

    ERROR_ALREADY_EXISTS = 183

    POSIX_RUNTIME_DIRECTORY_NAME = (
        "LeagueMasteryTracker"
    )

    def __init__(
        self,
        mutex_name=DEFAULT_MUTEX_NAME,
    ):
        normalized_mutex_name = str(
            mutex_name or ""
        ).strip()

        if not normalized_mutex_name:
            raise ValueError(
                "The application mutex name cannot be empty."
            )

        self.mutex_name = normalized_mutex_name
        self._mutex_handle = None
        self._lock_file = None

    @property
    def is_acquired(self):
        """Return whether this service instance owns the lock."""

        return (
            self._mutex_handle is not None
            or self._lock_file is not None
        )

    def acquire(self):
        """
        Acquire the application-instance lock without blocking.

        Returns True when this is the first running application
        instance. Returns False when another process or service
        instance already owns the lock.
        """

        if self.is_acquired:
            return True

        if os.name == "nt":
            return self._acquire_windows()

        if os.name == "posix":
            return self._acquire_posix()

        raise ApplicationInstanceError(
            "Application instance locking is not supported on "
            "this operating system."
        )

    def _acquire_windows(self):
        """Acquire the existing Windows named mutex."""

        kernel32 = self._get_kernel32()

        ctypes.set_last_error(0)

        mutex_handle = kernel32.CreateMutexW(
            None,
            True,
            self.mutex_name,
        )

        if not mutex_handle:
            raise ApplicationInstanceError(
                "The application instance lock could not be "
                "created."
            ) from ctypes.WinError(
                ctypes.get_last_error()
            )

        if ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS:
            close_succeeded = kernel32.CloseHandle(
                mutex_handle
            )

            if not close_succeeded:
                raise ApplicationInstanceError(
                    "The existing application instance lock "
                    "could not be closed safely."
                ) from ctypes.WinError(
                    ctypes.get_last_error()
                )

            return False

        self._mutex_handle = mutex_handle

        return True

    def _acquire_posix(self):
        """Acquire a non-blocking POSIX advisory file lock."""

        import fcntl

        lock_file_path = self._get_posix_lock_file_path()

        try:
            lock_file_path.parent.mkdir(
                mode=0o700,
                parents=True,
                exist_ok=True,
            )
            lock_file = open(lock_file_path, "a+b")
        except OSError as error:
            raise ApplicationInstanceError(
                "The application instance lock file could not be "
                "opened."
            ) from error

        try:
            fcntl.flock(
                lock_file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except OSError as error:
            try:
                lock_file.close()
            except OSError as close_error:
                raise ApplicationInstanceError(
                    "The application instance lock file could not "
                    "be closed after acquisition failed."
                ) from close_error

            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False

            raise ApplicationInstanceError(
                "The application instance lock could not be "
                "acquired."
            ) from error

        self._lock_file = lock_file

        return True

    def release(self):
        """
        Release and close the owned application-instance lock.

        Calling release repeatedly is safe.
        """

        if self._mutex_handle is not None:
            self._release_windows()
        elif self._lock_file is not None:
            self._release_posix()

    def _release_windows(self):
        """Release and close the existing Windows named mutex."""

        kernel32 = self._get_kernel32()
        mutex_handle = self._mutex_handle
        self._mutex_handle = None

        release_error = None
        close_error = None

        if not kernel32.ReleaseMutex(mutex_handle):
            release_error = ctypes.WinError(
                ctypes.get_last_error()
            )

        if not kernel32.CloseHandle(mutex_handle):
            close_error = ctypes.WinError(
                ctypes.get_last_error()
            )

        if release_error is not None:
            raise ApplicationInstanceError(
                "The application instance lock could not be "
                "released safely."
            ) from release_error

        if close_error is not None:
            raise ApplicationInstanceError(
                "The application instance lock handle could not "
                "be closed safely."
            ) from close_error

    def _release_posix(self):
        """Unlock and close the retained POSIX lock descriptor."""

        import fcntl

        lock_file = self._lock_file
        self._lock_file = None

        unlock_error = None
        close_error = None

        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError as error:
            unlock_error = error

        try:
            lock_file.close()
        except OSError as error:
            close_error = error

        if unlock_error is not None:
            raise ApplicationInstanceError(
                "The application instance lock could not be "
                "released safely."
            ) from unlock_error

        if close_error is not None:
            raise ApplicationInstanceError(
                "The application instance lock file could not be "
                "closed safely."
            ) from close_error

    def __enter__(self):
        if not self.acquire():
            raise ApplicationInstanceError(
                "Another League Mastery Tracker instance is "
                "already running."
            )

        return self

    def __exit__(
        self,
        exception_type,
        exception_value,
        traceback,
    ):
        self.release()
        return False

    def _get_posix_lock_file_path(self):
        """Return a stable per-user path for the POSIX lock file."""

        lock_name_digest = hashlib.sha256(
            self.mutex_name.encode("utf-8")
        ).hexdigest()[:16]

        return (
            self._get_posix_runtime_directory()
            / f"application-instance-{lock_name_digest}.lock"
        )

    @classmethod
    def _get_posix_runtime_directory(cls):
        """Resolve a runtime directory outside source/package trees."""

        xdg_runtime_directory = str(
            os.environ.get("XDG_RUNTIME_DIR", "") or ""
        ).strip()

        if xdg_runtime_directory:
            xdg_candidate = (
                cls._normalize_posix_runtime_candidate(
                    xdg_runtime_directory
                )
            )

            if xdg_candidate is not None:
                return xdg_candidate

        fallback_base_directory = (
            Path(tempfile.gettempdir())
            / f"league-mastery-tracker-{os.getuid()}"
        )

        fallback_candidate = (
            cls._normalize_posix_runtime_candidate(
                fallback_base_directory
            )
        )

        if fallback_candidate is None:
            raise ApplicationInstanceError(
                "A safe per-user application runtime directory "
                "could not be resolved."
            )

        return fallback_candidate

    @classmethod
    def _normalize_posix_runtime_candidate(
        cls,
        base_directory,
    ):
        """Normalize and validate one possible POSIX runtime path."""

        try:
            supplied_path = Path(base_directory)

            if not supplied_path.is_absolute():
                return None

            application_runtime_directory = (
                supplied_path.expanduser()
                / cls.POSIX_RUNTIME_DIRECTORY_NAME
            ).resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return None

        if cls._is_forbidden_posix_runtime_directory(
            application_runtime_directory
        ):
            return None

        return application_runtime_directory

    @classmethod
    def _is_forbidden_posix_runtime_directory(
        cls,
        candidate,
    ):
        """Reject runtime paths in source or extraction trees."""

        forbidden_roots = [
            Path(__file__).resolve(strict=False).parents[2],
        ]

        pyinstaller_directory = getattr(
            sys,
            "_MEIPASS",
            None,
        )

        if pyinstaller_directory:
            try:
                forbidden_roots.append(
                    Path(pyinstaller_directory)
                    .expanduser()
                    .resolve(strict=False)
                )
            except (OSError, RuntimeError, ValueError):
                pass

        return any(
            candidate == forbidden_root
            or forbidden_root in candidate.parents
            for forbidden_root in forbidden_roots
        )

    @staticmethod
    def _get_kernel32():
        """Load Kernel32 and configure mutex function signatures."""

        kernel32 = ctypes.WinDLL(
            "kernel32.dll",
            use_last_error=True,
        )

        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        return kernel32
